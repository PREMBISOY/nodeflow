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
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models import Project


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


class PlatformStore:
    """Development/test store. Production storage is defined by migration 002."""
    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}; self.by_email: dict[str, tuple[UUID, str]] = {}
        self.teams: dict[UUID, Team] = {}; self.memberships: dict[tuple[UUID, UUID], Membership] = {}
        self.project_teams: dict[UUID, UUID] = {}; self.revoked: set[str] = set()
        self.projects: dict[UUID, Project] = {}
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
    def create_team(self, user: User, name: str) -> Team:
        code = "NF-" + "".join(ch for ch in name.upper() if ch.isalnum())[:4].ljust(2, "X") + "-" + secrets.token_hex(2).upper()
        team = Team(name=name, team_code=code, created_by=user.id); self.teams[team.id] = team; self.memberships[(user.id, team.id)] = Membership(team_id=team.id, user_id=user.id, role="OWNER"); return team
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
    def create_project(self, team_id: UUID, request: ProjectCreateRequest) -> Project:
        project = Project(name=request.name, purpose=request.purpose, technology_stack=request.technology_stack)
        self.projects[project.id] = project; self.project_teams[project.id] = team_id
        return project
    def projects_for(self, team_id: UUID) -> list[Project]:
        return [project for project_id, project in self.projects.items() if self.project_teams.get(project_id) == team_id]


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
    def get_user(self, user_id: UUID) -> User:
        row=self.session.execute(text("select id,name,email,auth_subject,created_at from users where id=:id"), {"id":str(user_id)}).first()
        if not row: raise KeyError(user_id)
        return self._user(row)
    def create_team(self, user: User, name: str) -> Team:
        team=Team(name=name,team_code="NF-"+"".join(c for c in name.upper() if c.isalnum())[:4].ljust(2,"X")+"-"+secrets.token_hex(2).upper(),created_by=user.id)
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
    def create_project(self, team_id: UUID, request: ProjectCreateRequest) -> Project:
        project = Project(name=request.name, purpose=request.purpose, technology_stack=request.technology_stack)
        self.session.execute(text("insert into projects (id,name,purpose,technology_stack,status,created_at,team_id) values (:id,:name,:purpose,:stack,:status,:created,:team)"), {"id":str(project.id),"name":project.name,"purpose":project.purpose,"stack":json.dumps(project.technology_stack),"status":project.status,"created":project.created_at,"team":str(team_id)})
        self.session.commit()
        return project
    def projects_for(self, team_id: UUID) -> list[Project]:
        rows = self.session.execute(text("select id,name,purpose,technology_stack,status,created_at from projects where team_id=:team order by created_at"), {"team":str(team_id)})
        return [Project.model_validate(dict(row._mapping)) for row in rows]


class SessionCodec:
    def __init__(self) -> None: self.secret = os.getenv("JWT_SECRET", "development-only-change-me").encode()
    def issue(self, user_id: UUID, active_team_id: UUID | None = None) -> str:
        payload = {"sub": str(user_id), "team": str(active_team_id) if active_team_id else None, "exp": int((utc_now() + timedelta(hours=12)).timestamp()), "jti": secrets.token_urlsafe(16)}
        body = _b64(json.dumps(payload, separators=(",", ":")).encode()); signature = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest()); return body + "." + signature
    def read(self, token: str) -> dict:
        body, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())): raise PermissionError("Invalid session")
        data = json.loads(_unb64(body));
        if data["exp"] < int(utc_now().timestamp()): raise PermissionError("Session expired")
        return data


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
    user, _, _ = current(request, authorization); return envelope(platform(request).create_team(user, payload.name))
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
    try: return envelope(platform(request).join(user, payload.team_code))
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

@router.get("/teams/{team_id}/projects")
def projects(team_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    try: platform(request).require_member(user.id, team_id)
    except PermissionError: raise HTTPException(404, "Team not found")
    return envelope(platform(request).projects_for(team_id))

@router.post("/teams/{team_id}/projects", status_code=201)
def create_project(team_id: UUID, payload: ProjectCreateRequest, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    try: platform(request).require_member(user.id, team_id)
    except PermissionError: raise HTTPException(404, "Team not found")
    return envelope(platform(request).create_project(team_id, payload))
