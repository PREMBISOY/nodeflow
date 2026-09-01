"""Platform identity and tenant context, intentionally outside Core Intelligence.

The active team is embedded in a signed session token after membership is
verified; team identifiers are never trusted from ordinary resource requests.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models import Project
from app.schemas.intelligence import GitHubEventCreate


def utc_now() -> datetime: return datetime.now(timezone.utc)
def _b64(value: bytes) -> str: return base64.urlsafe_b64encode(value).decode().rstrip("=")
def _unb64(value: str) -> bytes: return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class User(BaseModel):
    id: UUID = Field(default_factory=uuid4); name: str; email: str; auth_subject: str; created_at: datetime = Field(default_factory=utc_now)
class Team(BaseModel):
    id: UUID = Field(default_factory=uuid4); name: str; team_code: str; created_by: UUID; created_at: datetime = Field(default_factory=utc_now)
class Membership(BaseModel):
    id: UUID = Field(default_factory=uuid4); team_id: UUID; user_id: UUID; role: str = "MEMBER"; joined_at: datetime = Field(default_factory=utc_now)
class RegisterRequest(BaseModel): name: str; email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"); password: str = Field(min_length=8)
class LoginRequest(BaseModel): email: str; password: str
class TeamCreateRequest(BaseModel): name: str
class JoinTeamRequest(BaseModel): team_code: str
class ActiveTeamRequest(BaseModel): team_id: UUID
class ProjectCreateRequest(BaseModel): name: str; purpose: str; technology_stack: list[str] = Field(default_factory=list)
class GitHubRepositoryConnectRequest(BaseModel):
    project_id: UUID
    repository: str = Field(min_length=3, max_length=300)
class GitHubRepository(BaseModel):
    id: UUID = Field(default_factory=uuid4); team_id: UUID; project_id: UUID; full_name: str; html_url: str; default_branch: str = "main"; connected_by: UUID; connected_at: datetime = Field(default_factory=utc_now)


class PlatformStore:
    """Development/test store. Production storage is defined by migration 002."""
    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}; self.by_email: dict[str, tuple[UUID, str]] = {}
        self.teams: dict[UUID, Team] = {}; self.memberships: dict[tuple[UUID, UUID], Membership] = {}
        self.project_teams: dict[UUID, UUID] = {}; self.revoked: set[str] = set()
        self.projects: dict[UUID, Project] = {}
        self.github_users: dict[str, UUID] = {}; self.github_repositories: dict[tuple[UUID, UUID], GitHubRepository] = {}
        self.oauth_states: set[str] = set()
    @staticmethod
    def _hash(password: str, salt: bytes | None = None) -> str:
        salt = salt or secrets.token_bytes(16)
        return _b64(salt) + "$" + _b64(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000))
    @staticmethod
    def _verify(password: str, stored: str) -> bool:
        salt, digest = stored.split("$"); return hmac.compare_digest(PlatformStore._hash(password, _unb64(salt)), stored)
    def register(self, request: RegisterRequest) -> User:
        email = request.email.lower()
        if email in self.by_email: raise ValueError("An account with this email already exists")
        user = User(name=request.name, email=email, auth_subject=str(uuid4())); self.users[user.id] = user; self.by_email[email] = (user.id, self._hash(request.password)); return user
    def login(self, request: LoginRequest) -> User:
        entry = self.by_email.get(request.email.lower())
        if not entry or not self._verify(request.password, entry[1]): raise PermissionError("Invalid email or password")
        return self.users[entry[0]]
    def github_user(self, github_id: str, login: str, name: str | None, email: str | None) -> User:
        subject = f"github:{github_id}"
        if subject in self.github_users: return self.users[self.github_users[subject]]
        safe_email = (email or f"{login}@users.noreply.github.com").lower()
        existing = self.by_email.get(safe_email)
        if existing:
            user = self.users[existing[0]]; self.github_users[subject] = user.id; return user
        user = User(name=name or login, email=safe_email, auth_subject=subject)
        self.users[user.id] = user; self.by_email[safe_email] = (user.id, ""); self.github_users[subject] = user.id; return user
    def create_team(self, user: User, name: str) -> Team:
        normalized_name = " ".join(name.split())
        if not normalized_name: raise ValueError("Team name is required")
        existing = next((team for team in self.teams.values() if team.created_by == user.id and team.name.casefold() == normalized_name.casefold()), None)
        if existing: return existing
        code = "NF-" + "".join(ch for ch in normalized_name.upper() if ch.isalnum())[:4].ljust(2, "X") + "-" + secrets.token_hex(2).upper()
        team = Team(name=normalized_name, team_code=code, created_by=user.id); self.teams[team.id] = team; self.memberships[(user.id, team.id)] = Membership(team_id=team.id, user_id=user.id, role="OWNER"); return team
    def join(self, user: User, code: str) -> Team:
        team = next((team for team in self.teams.values() if team.team_code == code.upper()), None)
        if not team: raise LookupError("Team not found")
        self.memberships.setdefault((user.id, team.id), Membership(team_id=team.id, user_id=user.id)); return team
    def require_member(self, user_id: UUID, team_id: UUID) -> Membership:
        membership = self.memberships.get((user_id, team_id))
        if not membership: raise PermissionError("Not a member of the active team")
        return membership
    def teams_for(self, user_id: UUID) -> list[Team]: return [self.teams[key[1]] for key in self.memberships if key[0] == user_id]
    def get_user(self, user_id: UUID) -> User: return self.users[user_id]
    def get_team(self, team_id: UUID) -> Team: return self.teams[team_id]
    def members_for(self, team_id: UUID) -> list[Membership]: return [m for m in self.memberships.values() if m.team_id == team_id]
    def leave(self, user_id: UUID, team_id: UUID) -> None: del self.memberships[(user_id, team_id)]
    def revoke(self, jti: str) -> None: self.revoked.add(jti)
    def is_revoked(self, jti: str) -> bool: return jti in self.revoked
    def require_project(self, user_id: UUID, team_id: UUID, project_id: UUID) -> None:
        self.require_member(user_id, team_id)
        if self.project_teams.get(project_id) != team_id: raise PermissionError("Project is outside the active team")
    def create_project(self, user_id: UUID, team_id: UUID, project: Project) -> Project:
        self.require_member(user_id, team_id); self.project_teams[project.id] = team_id; return project
    def list_projects(self, user_id: UUID, team_id: UUID, projects: list[Project]) -> list[Project]:
        self.require_member(user_id, team_id); return [project for project in projects if self.project_teams.get(project.id) == team_id]
    def connect_github_repository(self, user_id: UUID, team_id: UUID, request: GitHubRepositoryConnectRequest, metadata: dict) -> GitHubRepository:
        self.require_project(user_id, team_id, request.project_id)
        repo = GitHubRepository(team_id=team_id, project_id=request.project_id, full_name=metadata["full_name"], html_url=metadata["html_url"], default_branch=metadata.get("default_branch") or "main", connected_by=user_id)
        self.github_repositories[(team_id, request.project_id)] = repo; return repo
    def github_repositories_for(self, user_id: UUID, team_id: UUID) -> list[GitHubRepository]:
        self.require_member(user_id, team_id); return [repo for repo in self.github_repositories.values() if repo.team_id == team_id]
    def github_repository_for(self, full_name: str) -> GitHubRepository | None:
        matches = [repo for repo in self.github_repositories.values() if repo.full_name.lower() == full_name.lower()]
        if len(matches) > 1: raise ValueError("Repository is connected to more than one project")
        return matches[0] if matches else None
    def remember_oauth_state(self, nonce: str) -> None: self.oauth_states.add(nonce)
    def consume_oauth_state(self, nonce: str) -> bool:
        if nonce not in self.oauth_states: return False
        self.oauth_states.remove(nonce); return True


class SqlPlatformStore:
    """Production store mapped directly to the Supabase schema via DATABASE_URL."""
    def __init__(self, session: Session) -> None: self.session = session
    @staticmethod
    def _user(row) -> User: return User(id=row.id, name=row.name, email=row.email, auth_subject=row.auth_subject, created_at=row.created_at)
    @staticmethod
    def _team(row) -> Team: return Team(id=row.id, name=row.name, team_code=row.team_code, created_by=row.created_by, created_at=row.created_at)
    @staticmethod
    def _membership(row) -> Membership: return Membership(id=row.id, team_id=row.team_id, user_id=row.user_id, role=row.role, joined_at=row.joined_at)
    def register(self, request: RegisterRequest) -> User:
        email=request.email.lower(); existing=self.session.execute(text("select id from users where email=:email"), {"email":email}).first()
        if existing: raise ValueError("An account with this email already exists")
        user=User(name=request.name,email=email,auth_subject=str(uuid4())); password_hash=PlatformStore._hash(request.password)
        self.session.execute(text("insert into users (id,name,email,auth_subject,created_at,updated_at) values (:id,:name,:email,:subject,:created,:created)"), {"id":str(user.id),"name":user.name,"email":user.email,"subject":user.auth_subject,"created":user.created_at})
        self.session.execute(text("insert into user_credentials (user_id,password_hash,updated_at) values (:id,:hash,:at)"), {"id":str(user.id),"hash":password_hash,"at":user.created_at}); self.session.commit(); return user
    def login(self, request: LoginRequest) -> User:
        row=self.session.execute(text("select u.id,u.name,u.email,u.auth_subject,u.created_at,c.password_hash from users u join user_credentials c on c.user_id=u.id where u.email=:email"), {"email":request.email.lower()}).first()
        if not row or not PlatformStore._verify(request.password,row.password_hash): raise PermissionError("Invalid email or password")
        return self._user(row)
    def github_user(self, github_id: str, login: str, name: str | None, email: str | None) -> User:
        subject = f"github:{github_id}"
        row = self.session.execute(text("select id,name,email,auth_subject,created_at from users where auth_subject=:subject"), {"subject": subject}).first()
        if row: return self._user(row)
        safe_email = (email or f"{login}@users.noreply.github.com").lower()
        row = self.session.execute(text("select id,name,email,auth_subject,created_at from users where email=:email"), {"email": safe_email}).first()
        if row: return self._user(row)
        user = User(name=name or login, email=safe_email, auth_subject=subject)
        self.session.execute(text("insert into users (id,name,email,auth_subject,created_at,updated_at) values (:id,:name,:email,:subject,:created,:created)"), {"id":str(user.id),"name":user.name,"email":user.email,"subject":subject,"created":user.created_at})
        self.session.commit(); return user
    def get_user(self, user_id: UUID) -> User:
        row=self.session.execute(text("select id,name,email,auth_subject,created_at from users where id=:id"), {"id":str(user_id)}).first()
        if not row: raise KeyError(user_id)
        return self._user(row)
    def create_team(self, user: User, name: str) -> Team:
        normalized_name = " ".join(name.split())
        if not normalized_name: raise ValueError("Team name is required")
        row = self.session.execute(text("select id,name,team_code,created_by,created_at from teams where created_by=:owner and lower(btrim(name))=lower(:name) order by created_at limit 1"), {"owner":str(user.id),"name":normalized_name}).first()
        if row: return self._team(row)
        team=Team(name=normalized_name,team_code="NF-"+"".join(c for c in normalized_name.upper() if c.isalnum())[:4].ljust(2,"X")+"-"+secrets.token_hex(2).upper(),created_by=user.id)
        self.session.execute(text("insert into teams (id,name,team_code,created_by,created_at,updated_at) values (:id,:name,:code,:owner,:at,:at)"), {"id":str(team.id),"name":team.name,"code":team.team_code,"owner":str(user.id),"at":team.created_at})
        self.session.execute(text("insert into team_members (id,team_id,user_id,role,joined_at) values (:id,:team,:user,'OWNER',:at)"), {"id":str(uuid4()),"team":str(team.id),"user":str(user.id),"at":team.created_at}); self.session.commit(); return team
    def join(self, user: User, code: str) -> Team:
        row=self.session.execute(text("select id,name,team_code,created_by,created_at from teams where team_code=:code"), {"code":code.upper()}).first()
        if not row: raise LookupError("Team not found")
        team=self._team(row); self.session.execute(text("insert into team_members (id,team_id,user_id,role,joined_at) values (:id,:team,:user,'MEMBER',now()) on conflict (team_id,user_id) do nothing"), {"id":str(uuid4()),"team":str(team.id),"user":str(user.id)}); self.session.commit(); return team
    def require_member(self, user_id: UUID, team_id: UUID) -> Membership:
        row=self.session.execute(text("select id,team_id,user_id,role,joined_at from team_members where user_id=:user and team_id=:team"), {"user":str(user_id),"team":str(team_id)}).first()
        if not row: raise PermissionError("Not a member of the active team")
        return self._membership(row)
    def teams_for(self,user_id: UUID) -> list[Team]: return [self._team(row) for row in self.session.execute(text("select t.id,t.name,t.team_code,t.created_by,t.created_at from teams t join team_members m on m.team_id=t.id where m.user_id=:user order by t.created_at"), {"user":str(user_id)})]
    def get_team(self,team_id: UUID) -> Team:
        row=self.session.execute(text("select id,name,team_code,created_by,created_at from teams where id=:id"), {"id":str(team_id)}).first()
        if not row: raise KeyError(team_id)
        return self._team(row)
    def members_for(self,team_id: UUID) -> list[Membership]: return [self._membership(row) for row in self.session.execute(text("select id,team_id,user_id,role,joined_at from team_members where team_id=:team"), {"team":str(team_id)})]
    def leave(self,user_id: UUID,team_id: UUID) -> None: self.session.execute(text("delete from team_members where user_id=:user and team_id=:team"), {"user":str(user_id),"team":str(team_id)}); self.session.commit()
    def revoke(self,jti: str) -> None: self.session.execute(text("insert into auth_sessions (id,user_id,jti,revoked_at,created_at,expires_at) values (:id,null,:jti,now(),now(),now()) on conflict (jti) do update set revoked_at=now()"), {"id":str(uuid4()),"jti":jti}); self.session.commit()
    def is_revoked(self,jti: str) -> bool: return self.session.execute(text("select 1 from auth_sessions where jti=:jti and revoked_at is not null"), {"jti":jti}).first() is not None
    def require_project(self,user_id: UUID,team_id: UUID,project_id: UUID) -> None:
        self.require_member(user_id,team_id)
        row=self.session.execute(text("select 1 from projects where id=:project and team_id=:team"), {"project":str(project_id),"team":str(team_id)}).first()
        if not row: raise PermissionError("Project is outside the active team")
    def create_project(self,user_id: UUID,team_id: UUID,project: Project) -> Project:
        self.require_member(user_id,team_id)
        self.session.execute(text("insert into projects (id,team_id,name,purpose,technology_stack,status,created_at) values (:id,:team,:name,:purpose,:stack,:status,:created)"), {"id":str(project.id),"team":str(team_id),"name":project.name,"purpose":project.purpose,"stack":json.dumps(project.technology_stack),"status":project.status,"created":project.created_at})
        self.session.commit(); return project
    def list_projects(self,user_id: UUID,team_id: UUID,projects: list[Project] | None = None) -> list[Project]:
        self.require_member(user_id,team_id)
        rows=self.session.execute(text("select id,name,purpose,technology_stack,status,created_at from projects where team_id=:team order by created_at"), {"team":str(team_id)})
        return [Project(id=row.id,name=row.name,purpose=row.purpose,technology_stack=row.technology_stack,status=row.status,created_at=row.created_at) for row in rows]
    def connect_github_repository(self, user_id: UUID, team_id: UUID, request: GitHubRepositoryConnectRequest, metadata: dict) -> GitHubRepository:
        self.require_project(user_id, team_id, request.project_id)
        repo = GitHubRepository(team_id=team_id, project_id=request.project_id, full_name=metadata["full_name"], html_url=metadata["html_url"], default_branch=metadata.get("default_branch") or "main", connected_by=user_id)
        self.session.execute(text("insert into team_github_repositories (id,team_id,project_id,full_name,html_url,default_branch,connected_by,connected_at) values (:id,:team,:project,:name,:url,:branch,:user,:at) on conflict (team_id,project_id) do update set full_name=excluded.full_name,html_url=excluded.html_url,default_branch=excluded.default_branch,connected_by=excluded.connected_by,connected_at=excluded.connected_at"), {"id":str(repo.id),"team":str(team_id),"project":str(request.project_id),"name":repo.full_name,"url":repo.html_url,"branch":repo.default_branch,"user":str(user_id),"at":repo.connected_at})
        self.session.commit(); return repo
    def github_repositories_for(self, user_id: UUID, team_id: UUID) -> list[GitHubRepository]:
        self.require_member(user_id, team_id)
        rows = self.session.execute(text("select id,team_id,project_id,full_name,html_url,default_branch,connected_by,connected_at from team_github_repositories where team_id=:team order by connected_at"), {"team":str(team_id)})
        return [GitHubRepository(id=row.id,team_id=row.team_id,project_id=row.project_id,full_name=row.full_name,html_url=row.html_url,default_branch=row.default_branch,connected_by=row.connected_by,connected_at=row.connected_at) for row in rows]
    def github_repository_for(self, full_name: str) -> GitHubRepository | None:
        rows = list(self.session.execute(text("select id,team_id,project_id,full_name,html_url,default_branch,connected_by,connected_at from team_github_repositories where lower(full_name)=lower(:name)"), {"name":full_name}))
        if len(rows) > 1: raise ValueError("Repository is connected to more than one project")
        if not rows: return None
        row = rows[0]; return GitHubRepository(id=row.id,team_id=row.team_id,project_id=row.project_id,full_name=row.full_name,html_url=row.html_url,default_branch=row.default_branch,connected_by=row.connected_by,connected_at=row.connected_at)
    def remember_oauth_state(self, nonce: str) -> None:
        self.session.execute(text("insert into oauth_login_states (nonce,expires_at) values (:nonce,now() + interval '10 minutes')"), {"nonce":nonce}); self.session.commit()
    def consume_oauth_state(self, nonce: str) -> bool:
        row = self.session.execute(text("delete from oauth_login_states where nonce=:nonce and expires_at > now() returning nonce"), {"nonce":nonce}).first(); self.session.commit(); return row is not None


class SessionCodec:
    def __init__(self) -> None:
        secret = os.getenv("JWT_SECRET")
        if os.getenv("DATABASE_URL") and (not secret or secret == "development-only-change-me"):
            raise RuntimeError("JWT_SECRET must be set to a secure value when DATABASE_URL is configured")
        self.secret = (secret or "development-only-change-me").encode()
    def issue(self, user_id: UUID, active_team_id: UUID | None = None) -> str:
        payload = {"sub": str(user_id), "team": str(active_team_id) if active_team_id else None, "exp": int((utc_now() + timedelta(hours=12)).timestamp()), "jti": secrets.token_urlsafe(16)}
        body = _b64(json.dumps(payload, separators=(",", ":")).encode()); signature = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest()); return body + "." + signature
    def read(self, token: str) -> dict:
        body, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())): raise PermissionError("Invalid session")
        data = json.loads(_unb64(body));
        if data["exp"] < int(utc_now().timestamp()): raise PermissionError("Session expired")
        return data
    def issue_oauth_state(self, nonce: str) -> str:
        payload = {"typ":"github_oauth", "exp": int((utc_now() + timedelta(minutes=10)).timestamp()), "nonce": nonce}
        body = _b64(json.dumps(payload, separators=(",", ":")).encode()); return body + "." + _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
    def read_oauth_state(self, state: str) -> str:
        data = self.read(state)
        if data.get("typ") != "github_oauth": raise PermissionError("Invalid OAuth state")
        return data["nonce"]


router = APIRouter(prefix="/api/v1")
def platform(request: Request): return request.app.state.platform_store
def codec(request: Request) -> SessionCodec: return request.app.state.session_codec
def envelope(data): return {"success": True, "data": data, "error": None}
def token_from(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Authentication required")
    return authorization.removeprefix("Bearer ")
def current(request: Request, authorization: str | None = Header(default=None)) -> tuple[User, UUID | None, dict]:
    try: data = codec(request).read(token_from(authorization)); user = platform(request).get_user(UUID(data["sub"]))
    except (ValueError, KeyError, PermissionError): raise HTTPException(401, "Invalid session")
    if platform(request).is_revoked(data["jti"]): raise HTTPException(401, "Session revoked")
    return user, UUID(data["team"]) if data.get("team") else None, data

def require_project_access(request: Request, project_id: UUID, authorization: str | None = None) -> None:
    """Production-only boundary used by Prem's existing routes.

    Tests and local engine development remain explicitly unguarded unless a
    DATABASE_URL-backed deployment has enabled tenant enforcement.
    """
    if not request.app.state.enforce_tenants: return
    user, active_team, _ = current(request, authorization)
    if active_team is None: raise HTTPException(403, "Select an active team")
    try: platform(request).require_project(user.id, active_team, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")

def github_configuration() -> tuple[str, str, str]:
    client_id, client_secret = os.getenv("GITHUB_OAUTH_CLIENT_ID"), os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
    redirect_uri = os.getenv("GITHUB_OAUTH_REDIRECT_URI", "https://nodeflow.up.railway.app/api/v1/auth/github/callback")
    if not client_id or not client_secret: raise HTTPException(503, "GitHub sign-in is not configured")
    return client_id, client_secret, redirect_uri

def public_repository_metadata(value: str) -> dict:
    name = value.strip().removeprefix("https://github.com/").removesuffix("/").removesuffix(".git")
    if name.count("/") != 1: raise HTTPException(422, "Repository must be in owner/repository format")
    try:
        response = httpx.get(f"https://api.github.com/repos/{name}", headers={"Accept": "application/vnd.github+json"}, timeout=10)
    except httpx.HTTPError as exc: raise HTTPException(502, "Could not verify the GitHub repository") from exc
    if response.status_code == 404: raise HTTPException(404, "Public GitHub repository not found")
    if response.status_code != 200: raise HTTPException(502, "Could not verify the GitHub repository")
    data = response.json()
    if data.get("private") is not False: raise HTTPException(422, "Only public GitHub repositories can be connected")
    return {"full_name": data["full_name"], "html_url": data["html_url"], "default_branch": data.get("default_branch") or "main"}

def code_challenge(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode()).digest())

def github_webhook_event(payload: dict, event_name: str, project_id: UUID) -> GitHubEventCreate | None:
    repository = payload.get("repository", {}).get("full_name")
    if not repository: return None
    sender = payload.get("sender", {}).get("login")
    if event_name == "push":
        commits = payload.get("commits", [])
        files = [path for commit in commits for key in ("added", "modified", "removed") for path in commit.get(key, [])]
        return GitHubEventCreate(project_id=project_id, event_type="commit", action="updated", repository=repository, summary=f"Push to {payload.get('ref', 'repository')} by {sender or 'unknown'}", changed_files=list(dict.fromkeys(files)), ref=payload.get("ref"), commit_sha=payload.get("after"), actor_name=sender)
    if event_name == "pull_request":
        pull_request, action = payload.get("pull_request", {}), payload.get("action")
        normalized = "merged" if action == "closed" and pull_request.get("merged") else {"synchronize":"synchronized", "reopened":"opened"}.get(action, action)
        if normalized not in {"opened", "synchronized", "merged", "closed"}: return None
        return GitHubEventCreate(project_id=project_id, event_type="pull_request", action=normalized, repository=repository, summary=f"Pull request #{payload.get('number')} {normalized}", changed_files=[], ref=pull_request.get("head", {}).get("ref"), commit_sha=pull_request.get("head", {}).get("sha"), pull_request_number=payload.get("number"), actor_name=sender)
    return None

@router.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, request: Request):
    try: user = platform(request).register(payload)
    except ValueError as exc: raise HTTPException(409, str(exc))
    return envelope({"user": user, "access_token": codec(request).issue(user.id), "token_type": "bearer"})
@router.post("/auth/login")
def login(payload: LoginRequest, request: Request):
    try: user = platform(request).login(payload)
    except PermissionError as exc: raise HTTPException(401, str(exc))
    teams = platform(request).teams_for(user.id); active = teams[0].id if teams else None
    return envelope({"user": user, "access_token": codec(request).issue(user.id, active), "token_type": "bearer"})
@router.get("/auth/github")
def github_login(request: Request):
    client_id, _client_secret, redirect_uri = github_configuration()
    nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    platform(request).remember_oauth_state(nonce)
    query = urlencode({"client_id":client_id, "redirect_uri":redirect_uri, "scope":"read:user user:email", "state":codec(request).issue_oauth_state(nonce), "code_challenge":code_challenge(verifier), "code_challenge_method":"S256"})
    response = RedirectResponse(f"https://github.com/login/oauth/authorize?{query}")
    response.set_cookie("nodeflow_oauth", f"{nonce}.{verifier}", max_age=600, httponly=True, secure=True, samesite="lax", path="/api/v1/auth/github")
    return response
@router.get("/auth/github/callback")
def github_callback(code: str, state: str, request: Request, nodeflow_oauth: str | None = Cookie(default=None)):
    try:
        nonce = codec(request).read_oauth_state(state)
        cookie_nonce, verifier = (nodeflow_oauth or "").split(".", 1)
        if not hmac.compare_digest(nonce, cookie_nonce) or not platform(request).consume_oauth_state(nonce): raise PermissionError("OAuth state was already used")
    except (ValueError, PermissionError): raise HTTPException(400, "Invalid or expired GitHub OAuth state")
    client_id, client_secret, redirect_uri = github_configuration()
    try:
        token_response = httpx.post("https://github.com/login/oauth/access_token", data={"client_id":client_id,"client_secret":client_secret,"code":code,"redirect_uri":redirect_uri,"code_verifier":verifier}, headers={"Accept":"application/json"}, timeout=15)
        access_token = token_response.json().get("access_token") if token_response.is_success else None
        if not access_token: raise HTTPException(401, "GitHub sign-in was rejected")
        profile_response = httpx.get("https://api.github.com/user", headers={"Authorization":f"Bearer {access_token}","Accept":"application/vnd.github+json"}, timeout=15)
        if not profile_response.is_success: raise HTTPException(401, "Could not read the GitHub profile")
        profile = profile_response.json()
        emails_response = httpx.get("https://api.github.com/user/emails", headers={"Authorization":f"Bearer {access_token}","Accept":"application/vnd.github+json"}, timeout=15)
        emails = emails_response.json() if emails_response.is_success else []
    except httpx.HTTPError as exc: raise HTTPException(502, "GitHub sign-in is temporarily unavailable") from exc
    email = profile.get("email") or next((item["email"] for item in emails if item.get("primary") and item.get("verified")), None)
    user = platform(request).github_user(str(profile["id"]), profile["login"], profile.get("name"), email)
    teams = platform(request).teams_for(user.id); active = teams[0].id if teams else None
    token = codec(request).issue(user.id, active)
    response = RedirectResponse("/#access_token=" + token, status_code=303); response.delete_cookie("nodeflow_oauth", path="/api/v1/auth/github"); return response
@router.post("/auth/logout")
def logout(request: Request, authorization: str | None = Header(default=None)):
    _user, _team, data = current(request, authorization); platform(request).revoke(data["jti"]); return envelope({"logged_out": True})
@router.get("/me")
def me(request: Request, authorization: str | None = Header(default=None)):
    user, active, _ = current(request, authorization); return envelope({"user": user, "teams": platform(request).teams_for(user.id), "active_team_id": active})
@router.post("/me/active-team")
def switch_team(payload: ActiveTeamRequest, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization); platform(request).require_member(user.id, payload.team_id); return envelope({"access_token": codec(request).issue(user.id, payload.team_id), "active_team_id": payload.team_id})
@router.post("/teams", status_code=201)
def create_team(payload: TeamCreateRequest, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    try: team = platform(request).create_team(user, payload.name)
    except ValueError as exc: raise HTTPException(422, str(exc))
    return envelope({**team.model_dump(mode="json"), "access_token": codec(request).issue(user.id, team.id), "active_team_id": team.id})
@router.get("/teams")
def teams(request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization); return envelope(platform(request).teams_for(user.id))
@router.get("/teams/{team_id}")
def get_team(team_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    try: platform(request).require_member(user.id, team_id); return envelope(platform(request).get_team(team_id))
    except (KeyError, PermissionError): raise HTTPException(404, "Team not found")
@router.post("/teams/join")
def join_team(payload: JoinTeamRequest, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    try:
        team = platform(request).join(user, payload.team_code)
        return envelope({**team.model_dump(mode="json"), "access_token": codec(request).issue(user.id, team.id), "active_team_id": team.id})
    except LookupError: raise HTTPException(404, "Team not found")
@router.post("/teams/{team_id}/leave")
def leave_team(team_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    try: membership = platform(request).require_member(user.id, team_id)
    except PermissionError: raise HTTPException(404, "Team not found")
    if membership.role == "OWNER":
        owners = [m for m in platform(request).members_for(team_id) if m.role == "OWNER"]
        if len(owners) == 1: raise HTTPException(409, "Transfer ownership before leaving the team")
    platform(request).leave(user.id, team_id)
    return envelope({"left": True})
@router.get("/teams/{team_id}/members")
def members(team_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    try: platform(request).require_member(user.id, team_id)
    except PermissionError: raise HTTPException(403, "Forbidden")
    return envelope(platform(request).members_for(team_id))

def active_team_for(request: Request, team_id: UUID, authorization: str | None):
    user, active, _ = current(request, authorization)
    if active != team_id: raise HTTPException(403, "Select the requested team as active")
    try: platform(request).require_member(user.id, team_id)
    except PermissionError: raise HTTPException(404, "Team not found")
    return user

@router.get("/teams/{team_id}/projects")
def list_team_projects(team_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    user = active_team_for(request, team_id, authorization)
    repository = request.app.state.container.repository
    projects = list(repository.projects.values()) if hasattr(repository, "projects") else []
    return envelope(platform(request).list_projects(user.id, team_id, projects))

@router.post("/teams/{team_id}/projects", status_code=201)
def create_team_project(team_id: UUID, payload: ProjectCreateRequest, request: Request, authorization: str | None = Header(default=None)):
    user = active_team_for(request, team_id, authorization)
    project = Project(name=payload.name, purpose=payload.purpose, technology_stack=payload.technology_stack)
    saved = platform(request).create_project(user.id, team_id, project)
    repository = request.app.state.container.repository
    if isinstance(platform(request), PlatformStore):
        repository.projects[saved.id] = saved
    return envelope(saved)

@router.get("/teams/{team_id}/github/repositories")
def list_github_repositories(team_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    user = active_team_for(request, team_id, authorization)
    return envelope(platform(request).github_repositories_for(user.id, team_id))

@router.post("/teams/{team_id}/github/repositories", status_code=201)
def connect_github_repository(team_id: UUID, payload: GitHubRepositoryConnectRequest, request: Request, authorization: str | None = Header(default=None)):
    user = active_team_for(request, team_id, authorization)
    try: platform(request).require_project(user.id, team_id, payload.project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    metadata = public_repository_metadata(payload.repository)
    try: existing = platform(request).github_repository_for(metadata["full_name"])
    except ValueError: raise HTTPException(409, "Repository connection is ambiguous")
    if existing and existing.project_id != payload.project_id:
        raise HTTPException(409, "This GitHub repository is already connected to another project")
    connected = platform(request).connect_github_repository(user.id, team_id, payload, metadata)
    return envelope({"repository": connected, "webhook_url": str(request.base_url).rstrip("/") + "/api/v1/integrations/github/webhook"})

@router.post("/integrations/github/webhook", status_code=202)
async def ingest_github_webhook(request: Request, x_github_event: str | None = Header(default=None), x_hub_signature_256: str | None = Header(default=None)):
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret: raise HTTPException(503, "GitHub webhooks are not configured")
    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256): raise HTTPException(401, "Invalid GitHub webhook signature")
    try: payload = json.loads(body)
    except json.JSONDecodeError: raise HTTPException(400, "Invalid GitHub webhook payload")
    full_name = payload.get("repository", {}).get("full_name")
    if not full_name: raise HTTPException(400, "GitHub webhook repository is required")
    try: repository = platform(request).github_repository_for(full_name)
    except ValueError: raise HTTPException(409, "Repository connection is ambiguous")
    if repository is None: raise HTTPException(404, "GitHub repository is not connected")
    event = github_webhook_event(payload, x_github_event or "", repository.project_id)
    if event is None: return envelope({"ignored": True})
    return envelope(request.app.state.container.git.ingest(event))
