"""Platform identity and tenant context, intentionally outside Core Intelligence.

The active team is embedded in a signed session token after membership is
verified; team identifiers are never trusted from ordinary resource requests.

Hardening changes (codex/aayush-platform-hardening)
----------------------------------------------------
- Request-scoped sessions: commits removed from SqlPlatformStore methods;
  the unit-of-work middleware in main.py owns commit/rollback.
- Auth: versioned password hash (v1$salt$digest); OAuth-empty hash detected.
- Auth: JWT carries iss/aud/iat/nbf/jti; all claims validated on read.
- Auth: concurrent registration IntegrityError caught and re-raised cleanly.
- Auth: team-code collision retry (up to 5 attempts).
- RBAC: centralized Policy enforced on all admin actions.
- RBAC: join codes NOT returned in /me or team list; exposed only via /teams/{id}/join-code.
- GitHub: per-connection derived secret; X-GitHub-Delivery idempotency.
- Pagination: cursor-based pagination on list endpoints.
- Input validation: min/max lengths on all request models.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator, EmailStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.policy import Policy
from app.models import Project
from app.schemas.intelligence import GitHubEventCreate
from app.services.github_repository_intelligence import RepositorySyncError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _normalize_email(email: str) -> str:
    return email.lower().strip()


def _normalize_name(name: str) -> str:
    return " ".join(name.split())


# ---------------------------------------------------------------------------
# Pydantic request models (all with min/max lengths matching DB columns)
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        max_length=320,
    )
    password: str = Field(min_length=8, max_length=1024)

    @field_validator("password")
    @classmethod
    def password_policy(cls, v: str) -> str:
        if v.strip() != v or len(v.strip()) < 8:
            raise ValueError("Password must be at least 8 non-whitespace characters")
        return v


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class JoinTeamRequest(BaseModel):
    team_code: str = Field(min_length=1, max_length=32)


class ActiveTeamRequest(BaseModel):
    team_id: UUID


class TeamMemberAddRequest(BaseModel):
    email: str = Field(min_length=3, max_length=300)
    role: str = Field(default="MEMBER", pattern=r"^(ADMIN|MEMBER)$")

class ChangeMemberRoleRequest(BaseModel):
    role: str = Field(pattern=r"^(ADMIN|MEMBER)$")


class TransferOwnershipRequest(BaseModel):
    new_owner_id: UUID


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=4000)
    technology_stack: list[str] = Field(default_factory=list)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = Field(default=None, min_length=1, max_length=4000)


class GitHubRepositoryConnectRequest(BaseModel):
    project_id: UUID
    repository: str = Field(min_length=3, max_length=300)


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")
    actor_name: str = Field(min_length=1, max_length=200)
    comment: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class User(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    email: str
    auth_subject: str
    created_at: datetime = Field(default_factory=utc_now)


class Team(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    team_code: str
    created_by: UUID
    created_at: datetime = Field(default_factory=utc_now)


class TeamPublic(BaseModel):
    """Team model without the join code — safe for all member responses."""
    id: UUID
    name: str
    created_by: UUID
    created_at: datetime


class Membership(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    team_id: UUID
    user_id: UUID
    role: str = "MEMBER"
    joined_at: datetime = Field(default_factory=utc_now)


class GitHubRepository(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    team_id: UUID
    project_id: UUID
    full_name: str
    html_url: str
    default_branch: str = "main"
    connected_by: UUID
    connected_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Password hashing — versioned, adaptive
# ---------------------------------------------------------------------------

_HASH_VERSION = "v1"
_PBKDF2_ITERATIONS = 310_000


def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Return a versioned password hash: ``v1$<salt_b64>$<digest_b64>``."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"{_HASH_VERSION}${_b64(salt)}${_b64(digest)}"


def _verify_password(password: str, stored: str) -> bool:
    """Verify password against stored hash. Supports legacy (no-version) format."""
    if not stored:
        # OAuth-only account — no password set
        return False
    if stored.startswith("v1$"):
        parts = stored.split("$", 2)
        if len(parts) != 3:
            return False
        salt = _unb64(parts[1])
        return hmac.compare_digest(
            _hash_password(password, salt),
            stored,
        )
    # Legacy format: ``salt_b64$digest_b64`` (no version prefix)
    if "$" in stored:
        parts = stored.split("$", 1)
        if len(parts) == 2:
            try:
                salt = _unb64(parts[0])
                expected = parts[0] + "$" + _b64(
                    hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
                )
                return hmac.compare_digest(expected, stored)
            except Exception:
                return False
    return False


# ---------------------------------------------------------------------------
# In-memory development/test store (preserved)
# ---------------------------------------------------------------------------

class PlatformStore:
    """Development/test store. Production storage is defined by migration 002."""

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.by_email: dict[str, tuple[UUID, str]] = {}
        self.teams: dict[UUID, Team] = {}
        self.memberships: dict[tuple[UUID, UUID], Membership] = {}
        self.project_teams: dict[UUID, UUID] = {}
        self.revoked: set[str] = set()
        self.projects: dict[UUID, Project] = {}
        self.github_users: dict[str, UUID] = {}
        self.github_repositories: dict[tuple[UUID, UUID], GitHubRepository] = {}
        self.oauth_states: set[str] = set()

    # password helpers delegate to module-level functions
    @staticmethod
    def _hash(password: str, salt: bytes | None = None) -> str:
        return _hash_password(password, salt)

    @staticmethod
    def _verify(password: str, stored: str) -> bool:
        return _verify_password(password, stored)

    def register(self, request: RegisterRequest) -> User:
        email = _normalize_email(request.email)
        if email in self.by_email:
            raise ValueError("An account with this email already exists")
        user = User(name=request.name, email=email, auth_subject=str(uuid4()))
        self.users[user.id] = user
        self.by_email[email] = (user.id, self._hash(request.password))
        return user

    def login(self, request: LoginRequest) -> User:
        email = _normalize_email(request.email)
        entry = self.by_email.get(email)
        if not entry:
            raise PermissionError("Invalid email or password")
        stored_hash = entry[1]
        if not stored_hash:
            raise PermissionError(
                "This account uses GitHub sign-in. Please use the GitHub login option."
            )
        if not self._verify(request.password, stored_hash):
            raise PermissionError("Invalid email or password")
        return self.users[entry[0]]

    def github_user(self, github_id: str, login: str, name: str | None, email: str | None) -> User:
        subject = f"github:{github_id}"
        if subject in self.github_users:
            return self.users[self.github_users[subject]]
        safe_email = (email or f"{login}@users.noreply.github.com").lower()
        existing = self.by_email.get(safe_email)
        if existing:
            user = self.users[existing[0]]
            self.github_users[subject] = user.id
            return user
        user = User(name=name or login, email=safe_email, auth_subject=subject)
        self.users[user.id] = user
        self.by_email[safe_email] = (user.id, "")  # OAuth-only: empty hash
        self.github_users[subject] = user.id
        return user

    def create_team(self, user: User, name: str) -> Team:
        normalized = _normalize_name(name)
        if not normalized:
            raise ValueError("Team name is required")
        existing = next(
            (t for t in self.teams.values()
             if t.created_by == user.id and t.name.casefold() == normalized.casefold()),
            None,
        )
        if existing:
            return existing
        for _ in range(5):
            code = _generate_team_code(normalized)
            if not any(t.team_code == code for t in self.teams.values()):
                break
        team = Team(name=normalized, team_code=code, created_by=user.id)
        self.teams[team.id] = team
        self.memberships[(user.id, team.id)] = Membership(
            team_id=team.id, user_id=user.id, role="OWNER"
        )
        return team

    def join(self, user: User, code: str) -> Team:
        team = next((t for t in self.teams.values() if t.team_code == code.upper()), None)
        if not team:
            raise LookupError("Team not found")
        self.memberships.setdefault(
            (user.id, team.id), Membership(team_id=team.id, user_id=user.id)
        )
        return team

    def require_member(self, user_id: UUID, team_id: UUID) -> Membership:
        m = self.memberships.get((user_id, team_id))
        if not m:
            raise PermissionError("Not a member of the active team")
        return m

    def teams_for(self, user_id: UUID) -> list[Team]:
        return [self.teams[k[1]] for k in self.memberships if k[0] == user_id]

    def get_user(self, user_id: UUID) -> User:
        return self.users[user_id]

    def get_team(self, team_id: UUID) -> Team:
        return self.teams[team_id]

    def user_for_email(self, email: str) -> User | None:
        for u in self.users.values():
            if u.email.lower() == email.lower():
                return u
        return None

    def members_for(self, team_id: UUID) -> list[Membership]:
        return [m for m in self.memberships.values() if m.team_id == team_id]

    def add_member(self, acting_user_id: UUID, team_id: UUID, target_user_id: UUID, role: str) -> Membership:
        acting = self.require_member(acting_user_id, team_id)
        Policy.require(acting.role, "change_member_role", "MEMBER")
        if (target_user_id, team_id) in self.memberships:
            raise LookupError("Already a member")
        m = Membership(id=uuid4(), team_id=team_id, user_id=target_user_id, role=role, joined_at=datetime.utcnow())
        self.memberships[(target_user_id, team_id)] = m
        return m

    def leave(self, user_id: UUID, team_id: UUID) -> None:
        del self.memberships[(user_id, team_id)]

    def revoke(self, jti: str) -> None:
        self.revoked.add(jti)

    def is_revoked(self, jti: str) -> bool:
        return jti in self.revoked

    def require_project(self, user_id: UUID, team_id: UUID, project_id: UUID) -> None:
        self.require_member(user_id, team_id)
        if self.project_teams.get(project_id) != team_id:
            raise PermissionError("Project is outside the active team")

    def create_project(self, user_id: UUID, team_id: UUID, project: Project) -> Project:
        self.require_member(user_id, team_id)
        self.project_teams[project.id] = team_id
        return project

    def list_projects(self, user_id: UUID, team_id: UUID, projects: list[Project]) -> list[Project]:
        self.require_member(user_id, team_id)
        return [p for p in projects if self.project_teams.get(p.id) == team_id]

    def connect_github_repository(
        self, user_id: UUID, team_id: UUID,
        request: GitHubRepositoryConnectRequest, metadata: dict,
    ) -> GitHubRepository:
        self.require_project(user_id, team_id, request.project_id)
        repo = GitHubRepository(
            team_id=team_id, project_id=request.project_id,
            full_name=metadata["full_name"], html_url=metadata["html_url"],
            default_branch=metadata.get("default_branch") or "main",
            connected_by=user_id,
        )
        self.github_repositories[(team_id, request.project_id)] = repo
        return repo

    def github_repositories_for(self, user_id: UUID, team_id: UUID) -> list[GitHubRepository]:
        self.require_member(user_id, team_id)
        return [r for r in self.github_repositories.values() if r.team_id == team_id]

    def github_repository_for(self, full_name: str) -> GitHubRepository | None:
        matches = [r for r in self.github_repositories.values()
                   if r.full_name.lower() == full_name.lower()]
        if len(matches) > 1:
            raise ValueError("Repository is connected to more than one project")
        return matches[0] if matches else None

    def remember_oauth_state(self, nonce: str) -> None:
        self.oauth_states.add(nonce)

    def consume_oauth_state(self, nonce: str) -> bool:
        if nonce not in self.oauth_states:
            return False
        self.oauth_states.remove(nonce)
        return True

    def change_member_role(
        self, acting_user_id: UUID, team_id: UUID, target_user_id: UUID, new_role: str
    ) -> Membership:
        acting = self.require_member(acting_user_id, team_id)
        target = self.memberships.get((target_user_id, team_id))
        if not target:
            raise LookupError("Member not found")
        Policy.require(acting.role, "change_member_role", target.role)
        self.memberships[(target_user_id, team_id)] = Membership(
            id=target.id, team_id=team_id, user_id=target_user_id,
            role=new_role, joined_at=target.joined_at,
        )
        return self.memberships[(target_user_id, team_id)]

    def remove_member(self, acting_user_id: UUID, team_id: UUID, target_user_id: UUID) -> None:
        acting = self.require_member(acting_user_id, team_id)
        target = self.memberships.get((target_user_id, team_id))
        if not target:
            raise LookupError("Member not found")
        Policy.require(acting.role, "remove_member", target.role)
        owners = [m for m in self.members_for(team_id) if m.role == "OWNER"]
        if target.role == "OWNER" and len(owners) <= 1:
            raise ValueError("Cannot remove the last owner of a team")
        del self.memberships[(target_user_id, team_id)]

    def transfer_ownership(
        self, acting_user_id: UUID, team_id: UUID, new_owner_id: UUID
    ) -> None:
        acting = self.require_member(acting_user_id, team_id)
        Policy.require(acting.role, "transfer_ownership")
        target = self.memberships.get((new_owner_id, team_id))
        if not target:
            raise LookupError("Member not found")
        self.memberships[(new_owner_id, team_id)] = Membership(
            id=target.id, team_id=team_id, user_id=new_owner_id,
            role="OWNER", joined_at=target.joined_at,
        )
        self.memberships[(acting_user_id, team_id)] = Membership(
            id=acting.id, team_id=team_id, user_id=acting_user_id,
            role="ADMIN", joined_at=acting.joined_at,
        )

    def rotate_join_code(self, acting_user_id: UUID, team_id: UUID) -> str:
        acting = self.require_member(acting_user_id, team_id)
        Policy.require(acting.role, "rotate_join_code")
        team = self.teams[team_id]
        for _ in range(5):
            code = _generate_team_code(team.name)
            if not any(t.team_code == code for t in self.teams.values()):
                break
        self.teams[team_id] = Team(
            id=team.id, name=team.name, team_code=code,
            created_by=team.created_by, created_at=team.created_at,
        )
        return code


# ---------------------------------------------------------------------------
# SQL production store
# ---------------------------------------------------------------------------

class SqlPlatformStore:
    """Production store mapped directly to the Supabase schema via DATABASE_URL.

    IMPORTANT: No method calls session.commit(). The request-scoped
    unit-of-work middleware in main.py owns commit and rollback.
    Methods may call session.flush() to detect constraint violations early.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _user(row) -> User:
        return User(
            id=row.id, name=row.name, email=row.email,
            auth_subject=row.auth_subject, created_at=row.created_at,
        )

    @staticmethod
    def _team(row) -> Team:
        return Team(
            id=row.id, name=row.name, team_code=row.team_code,
            created_by=row.created_by, created_at=row.created_at,
        )

    @staticmethod
    def _membership(row) -> Membership:
        return Membership(
            id=row.id, team_id=row.team_id, user_id=row.user_id,
            role=row.role, joined_at=row.joined_at,
        )

    def register(self, request: RegisterRequest) -> User:
        email = _normalize_email(request.email)
        user = User(name=request.name, email=email, auth_subject=str(uuid4()))
        password_hash = _hash_password(request.password)
        try:
            self.session.execute(
                text(
                    "INSERT INTO users (id,name,email,auth_subject,created_at,updated_at) "
                    "VALUES (:id,:name,:email,:subject,:created,:created)"
                ),
                {"id": str(user.id), "name": user.name, "email": email,
                 "subject": user.auth_subject, "created": user.created_at},
            )
            self.session.execute(
                text(
                    "INSERT INTO user_credentials (user_id,password_hash,updated_at) "
                    "VALUES (:id,:hash,:at)"
                ),
                {"id": str(user.id), "hash": password_hash, "at": user.created_at},
            )
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            raise ValueError("An account with this email already exists")
        return user

    def login(self, request: LoginRequest) -> User:
        email = _normalize_email(request.email)
        row = self.session.execute(
            text(
                "SELECT u.id,u.name,u.email,u.auth_subject,u.created_at,c.password_hash "
                "FROM users u LEFT JOIN user_credentials c ON c.user_id=u.id "
                "WHERE u.email=:email"
            ),
            {"email": email},
        ).first()
        if not row:
            raise PermissionError("Invalid email or password")
        stored = row.password_hash or ""
        if not stored:
            raise PermissionError(
                "This account uses GitHub sign-in. Please use the GitHub login option."
            )
        if not _verify_password(request.password, stored):
            raise PermissionError("Invalid email or password")
        # Upgrade legacy hash format on successful login
        if not stored.startswith("v1$"):
            new_hash = _hash_password(request.password)
            self.session.execute(
                text("UPDATE user_credentials SET password_hash=:h, updated_at=now() WHERE user_id=:id"),
                {"h": new_hash, "id": str(row.id)},
            )
        return self._user(row)

    def github_user(self, github_id: str, login: str, name: str | None, email: str | None) -> User:
        subject = f"github:{github_id}"
        row = self.session.execute(
            text("SELECT id,name,email,auth_subject,created_at FROM users WHERE auth_subject=:s"),
            {"s": subject},
        ).first()
        if row:
            return self._user(row)
        safe_email = (email or f"{login}@users.noreply.github.com").lower()
        row = self.session.execute(
            text("SELECT id,name,email,auth_subject,created_at FROM users WHERE email=:e"),
            {"e": safe_email},
        ).first()
        if row:
            return self._user(row)
        user = User(name=name or login, email=safe_email, auth_subject=subject)
        try:
            self.session.execute(
                text(
                    "INSERT INTO users (id,name,email,auth_subject,created_at,updated_at) "
                    "VALUES (:id,:name,:email,:subject,:created,:created)"
                ),
                {"id": str(user.id), "name": user.name, "email": safe_email,
                 "subject": subject, "created": user.created_at},
            )
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            row = self.session.execute(
                text("SELECT id,name,email,auth_subject,created_at FROM users WHERE auth_subject=:s OR email=:e"),
                {"s": subject, "e": safe_email},
            ).first()
            if row:
                return self._user(row)
            raise
        return user

    def get_user(self, user_id: UUID) -> User:
        row = self.session.execute(
            text("SELECT id,name,email,auth_subject,created_at FROM users WHERE id=:id"),
            {"id": str(user_id)},
        ).first()
        if not row:
            raise KeyError(user_id)
        return self._user(row)

    def _generate_unique_team_code(self, name: str) -> str:
        for _ in range(5):
            code = _generate_team_code(name)
            existing = self.session.execute(
                text("SELECT 1 FROM teams WHERE team_code=:code"),
                {"code": code},
            ).first()
            if not existing:
                return code
        raise RuntimeError("Could not generate a unique team code after 5 attempts")

    def create_team(self, user: User, name: str) -> Team:
        normalized = _normalize_name(name)
        if not normalized:
            raise ValueError("Team name is required")
        row = self.session.execute(
            text(
                "SELECT id,name,team_code,created_by,created_at FROM teams "
                "WHERE created_by=:owner AND lower(btrim(name))=lower(:name) "
                "ORDER BY created_at LIMIT 1"
            ),
            {"owner": str(user.id), "name": normalized},
        ).first()
        if row:
            return self._team(row)
        code = self._generate_unique_team_code(normalized)
        team = Team(name=normalized, team_code=code, created_by=user.id)
        try:
            self.session.execute(
                text(
                    "INSERT INTO teams (id,name,team_code,created_by,created_at,updated_at) "
                    "VALUES (:id,:name,:code,:owner,:at,:at)"
                ),
                {"id": str(team.id), "name": team.name, "code": team.team_code,
                 "owner": str(user.id), "at": team.created_at},
            )
            self.session.execute(
                text(
                    "INSERT INTO team_members (id,team_id,user_id,role,joined_at) "
                    "VALUES (:id,:team,:user,'OWNER',:at)"
                ),
                {"id": str(uuid4()), "team": str(team.id), "user": str(user.id), "at": team.created_at},
            )
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            # Another process beat us — return the existing team
            row = self.session.execute(
                text(
                    "SELECT id,name,team_code,created_by,created_at FROM teams "
                    "WHERE created_by=:owner AND lower(btrim(name))=lower(:name) LIMIT 1"
                ),
                {"owner": str(user.id), "name": normalized},
            ).first()
            if row:
                return self._team(row)
            raise
        return team

    def join(self, user: User, code: str) -> Team:
        row = self.session.execute(
            text("SELECT id,name,team_code,created_by,created_at FROM teams WHERE team_code=:code"),
            {"code": code.upper()},
        ).first()
        if not row:
            raise LookupError("Team not found")
        team = self._team(row)
        self.session.execute(
            text(
                "INSERT INTO team_members (id,team_id,user_id,role,joined_at) "
                "VALUES (:id,:team,:user,'MEMBER',now()) "
                "ON CONFLICT (team_id,user_id) DO NOTHING"
            ),
            {"id": str(uuid4()), "team": str(team.id), "user": str(user.id)},
        )
        return team

    def require_member(self, user_id: UUID, team_id: UUID) -> Membership:
        row = self.session.execute(
            text("SELECT id,team_id,user_id,role,joined_at FROM team_members WHERE user_id=:u AND team_id=:t"),
            {"u": str(user_id), "t": str(team_id)},
        ).first()
        if not row:
            raise PermissionError("Not a member of the active team")
        return self._membership(row)

    def teams_for(self, user_id: UUID) -> list[Team]:
        rows = self.session.execute(
            text(
                "SELECT t.id,t.name,t.team_code,t.created_by,t.created_at "
                "FROM teams t JOIN team_members m ON m.team_id=t.id "
                "WHERE m.user_id=:user ORDER BY t.created_at"
            ),
            {"user": str(user_id)},
        )
        return [self._team(row) for row in rows]

    def get_team(self, team_id: UUID) -> Team:
        row = self.session.execute(
            text("SELECT id,name,team_code,created_by,created_at FROM teams WHERE id=:id"),
            {"id": str(team_id)},
        ).first()
        if not row:
            raise KeyError(team_id)
        return self._team(row)

    def user_for_email(self, email: str) -> User | None:
        row = self.session.execute(
            text("SELECT id,github_id,login,name,email FROM users WHERE email=:e"),
            {"e": email.lower()},
        ).first()
        return self._user(row) if row else None

    def members_for(self, team_id: UUID) -> list[Membership]:
        rows = self.session.execute(
            text("SELECT id,team_id,user_id,role,joined_at FROM team_members WHERE team_id=:t"),
            {"t": str(team_id)},
        )
        return [self._membership(row) for row in rows]

    def add_member(self, acting_user_id: UUID, team_id: UUID, target_user_id: UUID, role: str) -> Membership:
        acting = self.require_member(acting_user_id, team_id)
        Policy.require(acting.role, "change_member_role", "MEMBER")
        try:
            row = self.session.execute(
                text("INSERT INTO team_members (id,team_id,user_id,role) VALUES (:id,:t,:u,:role) RETURNING id,team_id,user_id,role,joined_at"),
                {"id": str(uuid4()), "t": str(team_id), "u": str(target_user_id), "role": role},
            ).first()
            return self._membership(row)
        except Exception:
            raise LookupError("Failed to add member")

    def leave(self, user_id: UUID, team_id: UUID) -> None:
        self.session.execute(
            text("DELETE FROM team_members WHERE user_id=:u AND team_id=:t"),
            {"u": str(user_id), "t": str(team_id)},
        )

    def revoke(self, jti: str) -> None:
        self.session.execute(
            text(
                "INSERT INTO auth_sessions (id,user_id,jti,revoked_at,created_at,expires_at) "
                "VALUES (:id,null,:jti,now(),now(),now()) "
                "ON CONFLICT (jti) DO UPDATE SET revoked_at=now()"
            ),
            {"id": str(uuid4()), "jti": jti},
        )

    def is_revoked(self, jti: str) -> bool:
        return (
            self.session.execute(
                text("SELECT 1 FROM auth_sessions WHERE jti=:jti AND revoked_at IS NOT NULL"),
                {"jti": jti},
            ).first()
            is not None
        )

    def require_project(self, user_id: UUID, team_id: UUID, project_id: UUID) -> None:
        self.require_member(user_id, team_id)
        row = self.session.execute(
            text("SELECT 1 FROM projects WHERE id=:project AND team_id=:team"),
            {"project": str(project_id), "team": str(team_id)},
        ).first()
        if not row:
            raise PermissionError("Project is outside the active team")

    def create_project(self, user_id: UUID, team_id: UUID, project: Project) -> Project:
        self.require_member(user_id, team_id)
        self.session.execute(
            text(
                "INSERT INTO projects (id,team_id,name,purpose,technology_stack,status,created_at) "
                "VALUES (:id,:team,:name,:purpose,:stack,:status,:created)"
            ),
            {
                "id": str(project.id), "team": str(team_id), "name": project.name,
                "purpose": project.purpose, "stack": json.dumps(project.technology_stack),
                "status": project.status, "created": project.created_at,
            },
        )
        return project

    def list_projects(self, user_id: UUID, team_id: UUID, projects: list[Project] | None = None) -> list[Project]:
        self.require_member(user_id, team_id)
        rows = self.session.execute(
            text("SELECT id,name,purpose,technology_stack,status,created_at FROM projects WHERE team_id=:t ORDER BY created_at"),
            {"t": str(team_id)},
        )
        return [
            Project(
                id=row.id, name=row.name, purpose=row.purpose,
                technology_stack=row.technology_stack, status=row.status, created_at=row.created_at,
            )
            for row in rows
        ]

    def connect_github_repository(
        self, user_id: UUID, team_id: UUID,
        request: GitHubRepositoryConnectRequest, metadata: dict,
    ) -> GitHubRepository:
        self.require_project(user_id, team_id, request.project_id)
        repo = GitHubRepository(
            team_id=team_id, project_id=request.project_id,
            full_name=metadata["full_name"], html_url=metadata["html_url"],
            default_branch=metadata.get("default_branch") or "main",
            connected_by=user_id,
        )
        # Store a derived connection secret (HMAC of team_id + repo_full_name)
        _webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
        connection_secret_hash = _b64(
            hmac.new(
                _webhook_secret.encode() or secrets.token_bytes(32),
                f"{team_id}:{repo.full_name}".encode(),
                hashlib.sha256,
            ).digest()
        ) if _webhook_secret else None

        self.session.execute(
            text(
                "INSERT INTO team_github_repositories "
                "(id,team_id,project_id,full_name,html_url,default_branch,connected_by,connected_at,connection_secret_hash) "
                "VALUES (:id,:team,:project,:name,:url,:branch,:user,:at,:secret) "
                "ON CONFLICT (team_id,project_id) DO UPDATE SET "
                "full_name=excluded.full_name,html_url=excluded.html_url,"
                "default_branch=excluded.default_branch,connected_by=excluded.connected_by,"
                "connected_at=excluded.connected_at,connection_secret_hash=excluded.connection_secret_hash"
            ),
            {
                "id": str(repo.id), "team": str(team_id), "project": str(request.project_id),
                "name": repo.full_name, "url": repo.html_url, "branch": repo.default_branch,
                "user": str(user_id), "at": repo.connected_at, "secret": connection_secret_hash,
            },
        )
        return repo

    def github_repositories_for(self, user_id: UUID, team_id: UUID) -> list[GitHubRepository]:
        self.require_member(user_id, team_id)
        rows = self.session.execute(
            text(
                "SELECT id,team_id,project_id,full_name,html_url,default_branch,connected_by,connected_at "
                "FROM team_github_repositories WHERE team_id=:t ORDER BY connected_at"
            ),
            {"t": str(team_id)},
        )
        return [
            GitHubRepository(
                id=row.id, team_id=row.team_id, project_id=row.project_id,
                full_name=row.full_name, html_url=row.html_url,
                default_branch=row.default_branch, connected_by=row.connected_by,
                connected_at=row.connected_at,
            )
            for row in rows
        ]

    def github_repository_for(self, full_name: str) -> GitHubRepository | None:
        rows = list(
            self.session.execute(
                text(
                    "SELECT id,team_id,project_id,full_name,html_url,default_branch,connected_by,connected_at "
                    "FROM team_github_repositories WHERE lower(full_name)=lower(:name)"
                ),
                {"name": full_name},
            )
        )
        if len(rows) > 1:
            raise ValueError("Repository is connected to more than one project")
        if not rows:
            return None
        row = rows[0]
        return GitHubRepository(
            id=row.id, team_id=row.team_id, project_id=row.project_id,
            full_name=row.full_name, html_url=row.html_url,
            default_branch=row.default_branch, connected_by=row.connected_by,
            connected_at=row.connected_at,
        )

    def remember_oauth_state(self, nonce: str) -> None:
        self.session.execute(
            text("INSERT INTO oauth_login_states (nonce,expires_at) VALUES (:nonce,now() + interval '10 minutes')"),
            {"nonce": nonce},
        )

    def consume_oauth_state(self, nonce: str) -> bool:
        row = self.session.execute(
            text("DELETE FROM oauth_login_states WHERE nonce=:nonce AND expires_at > now() RETURNING nonce"),
            {"nonce": nonce},
        ).first()
        return row is not None

    def change_member_role(
        self, acting_user_id: UUID, team_id: UUID, target_user_id: UUID, new_role: str
    ) -> Membership:
        acting = self.require_member(acting_user_id, team_id)
        target_row = self.session.execute(
            text("SELECT id,team_id,user_id,role,joined_at FROM team_members WHERE user_id=:u AND team_id=:t"),
            {"u": str(target_user_id), "t": str(team_id)},
        ).first()
        if not target_row:
            raise LookupError("Member not found")
        Policy.require(acting.role, "change_member_role", target_row.role)
        self.session.execute(
            text("UPDATE team_members SET role=:role WHERE user_id=:u AND team_id=:t"),
            {"role": new_role, "u": str(target_user_id), "t": str(team_id)},
        )
        return Membership(
            id=target_row.id, team_id=team_id, user_id=target_user_id,
            role=new_role, joined_at=target_row.joined_at,
        )

    def remove_member(self, acting_user_id: UUID, team_id: UUID, target_user_id: UUID) -> None:
        acting = self.require_member(acting_user_id, team_id)
        target_row = self.session.execute(
            text("SELECT role FROM team_members WHERE user_id=:u AND team_id=:t"),
            {"u": str(target_user_id), "t": str(team_id)},
        ).first()
        if not target_row:
            raise LookupError("Member not found")
        Policy.require(acting.role, "remove_member", target_row.role)
        if target_row.role == "OWNER":
            owners_count = self.session.execute(
                text("SELECT count(*) FROM team_members WHERE team_id=:t AND role='OWNER'"),
                {"t": str(team_id)},
            ).scalar()
            if (owners_count or 0) <= 1:
                raise ValueError("Cannot remove the last owner of a team")
        self.session.execute(
            text("DELETE FROM team_members WHERE user_id=:u AND team_id=:t"),
            {"u": str(target_user_id), "t": str(team_id)},
        )

    def transfer_ownership(self, acting_user_id: UUID, team_id: UUID, new_owner_id: UUID) -> None:
        acting = self.require_member(acting_user_id, team_id)
        Policy.require(acting.role, "transfer_ownership")
        target_row = self.session.execute(
            text("SELECT 1 FROM team_members WHERE user_id=:u AND team_id=:t"),
            {"u": str(new_owner_id), "t": str(team_id)},
        ).first()
        if not target_row:
            raise LookupError("Target member not found")
        self.session.execute(
            text("UPDATE team_members SET role='OWNER' WHERE user_id=:u AND team_id=:t"),
            {"u": str(new_owner_id), "t": str(team_id)},
        )
        self.session.execute(
            text("UPDATE team_members SET role='ADMIN' WHERE user_id=:u AND team_id=:t"),
            {"u": str(acting_user_id), "t": str(team_id)},
        )

    def rotate_join_code(self, acting_user_id: UUID, team_id: UUID) -> str:
        acting = self.require_member(acting_user_id, team_id)
        Policy.require(acting.role, "rotate_join_code")
        team = self.get_team(team_id)
        code = self._generate_unique_team_code(team.name)
        self.session.execute(
            text("UPDATE teams SET team_code=:code, updated_at=now() WHERE id=:t"),
            {"code": code, "t": str(team_id)},
        )
        return code

    def record_webhook_delivery(
        self,
        *,
        github_delivery_id: str,
        connection_id: UUID | None,
        team_id: UUID | None,
        project_id: UUID | None,
        event_name: str,
        action: str | None,
        payload_hash: str | None,
    ) -> bool:
        """Record a webhook delivery; returns False if already seen (replay)."""
        try:
            self.session.execute(
                text(
                    "INSERT INTO github_webhook_deliveries "
                    "(connection_id, team_id, project_id, github_delivery_id, event_name, action, payload_hash) "
                    "VALUES (:conn, :team, :project, :delivery, :event, :action, :phash)"
                ),
                {
                    "conn": str(connection_id) if connection_id else None,
                    "team": str(team_id) if team_id else None,
                    "project": str(project_id) if project_id else None,
                    "delivery": github_delivery_id,
                    "event": event_name,
                    "action": action,
                    "phash": payload_hash,
                },
            )
            self.session.flush()
            return True
        except IntegrityError:
            self.session.rollback()
            return False

    def mark_webhook_processed(self, github_delivery_id: str, status: str, failure_reason: str | None = None) -> None:
        self.session.execute(
            text(
                "UPDATE github_webhook_deliveries SET status=:status, "
                "processed_at=now(), failure_reason=:reason "
                "WHERE github_delivery_id=:delivery"
            ),
            {"status": status, "reason": failure_reason, "delivery": github_delivery_id},
        )


# ---------------------------------------------------------------------------
# JWT / Session codec — hardened
# ---------------------------------------------------------------------------

class SessionCodec:
    _ISSUER = "nodeflow"
    _AUDIENCE = "nodeflow-api"

    def __init__(self) -> None:
        secret = os.getenv("JWT_SECRET")
        if os.getenv("DATABASE_URL") and (not secret or secret == "development-only-change-me"):
            raise RuntimeError("JWT_SECRET must be set to a secure value when DATABASE_URL is configured")
        self.secret = (secret or "development-only-change-me").encode()

    def issue(self, user_id: UUID, active_team_id: UUID | None = None) -> str:
        now = utc_now()
        payload = {
            "iss": self._ISSUER,
            "aud": self._AUDIENCE,
            "sub": str(user_id),
            "team": str(active_team_id) if active_team_id else None,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(hours=12)).timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        sig = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
        return body + "." + sig

    def read(self, token: str) -> dict:
        try:
            body, sig = token.split(".", 1)
        except ValueError:
            raise PermissionError("Malformed session token")
        expected_sig = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected_sig):
            raise PermissionError("Invalid session")
        try:
            data = json.loads(_unb64(body))
        except Exception:
            raise PermissionError("Malformed session token")
        now = int(utc_now().timestamp())
        if data.get("iss") != self._ISSUER:
            raise PermissionError("Invalid session issuer")
        if data.get("aud") != self._AUDIENCE:
            raise PermissionError("Invalid session audience")
        if data.get("exp", 0) < now:
            raise PermissionError("Session expired")
        if data.get("nbf", now) > now:
            raise PermissionError("Session not yet valid")
        return data

    def issue_oauth_state(self, nonce: str) -> str:
        payload = {"typ": "github_oauth", "exp": int((utc_now() + timedelta(minutes=10)).timestamp()), "nonce": nonce}
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        return body + "." + _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())

    def read_oauth_state(self, state: str) -> str:
        data = self.read(state)
        if data.get("typ") != "github_oauth":
            raise PermissionError("Invalid OAuth state")
        return data["nonce"]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _generate_team_code(name: str) -> str:
    prefix = "".join(ch for ch in name.upper() if ch.isalnum())[:4].ljust(2, "X")
    return "NF-" + prefix + "-" + secrets.token_hex(2).upper()


def public_repository_metadata(value: str) -> dict:
    name = value.strip().removeprefix("https://github.com/").removesuffix("/").removesuffix(".git")
    if name.count("/") != 1:
        raise HTTPException(422, "Repository must be in owner/repository format")
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{name}",
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not verify the GitHub repository") from exc
    if response.status_code == 404:
        raise HTTPException(404, "Public GitHub repository not found")
    if response.status_code != 200:
        raise HTTPException(502, "Could not verify the GitHub repository")
    data = response.json()
    if data.get("private") is not False:
        raise HTTPException(422, "Only public GitHub repositories can be connected")
    return {
        "full_name": data["full_name"],
        "html_url": data["html_url"],
        "default_branch": data.get("default_branch") or "main",
        "github_repo_id": data.get("id"),
    }


def github_webhook_event(payload: dict, event_name: str, project_id: UUID) -> GitHubEventCreate | None:
    repository = payload.get("repository", {}).get("full_name")
    if not repository:
        return None
    sender = payload.get("sender", {}).get("login")
    if event_name == "push":
        commits = payload.get("commits", [])
        files = [path for commit in commits for key in ("added", "modified", "removed") for path in commit.get(key, [])]
        return GitHubEventCreate(
            project_id=project_id, event_type="commit", action="updated",
            repository=repository,
            summary=f"Push to {payload.get('ref', 'repository')} by {sender or 'unknown'}",
            changed_files=list(dict.fromkeys(files)), ref=payload.get("ref"),
            commit_sha=payload.get("after"), actor_name=sender,
        )
    if event_name == "pull_request":
        pull_request, action = payload.get("pull_request", {}), payload.get("action")
        normalized = (
            "merged" if action == "closed" and pull_request.get("merged")
            else {"synchronize": "synchronized", "reopened": "opened"}.get(action, action)
        )
        if normalized not in {"opened", "synchronized", "merged", "closed"}:
            return None
        return GitHubEventCreate(
            project_id=project_id, event_type="pull_request", action=normalized,
            repository=repository,
            summary=f"Pull request #{payload.get('number')} {normalized}",
            changed_files=[], ref=pull_request.get("head", {}).get("ref"),
            commit_sha=pull_request.get("head", {}).get("sha"),
            pull_request_number=payload.get("number"), actor_name=sender,
        )
    return None


def code_challenge(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode()).digest())


def github_configuration() -> tuple[str, str, str]:
    client_id = os.getenv("GITHUB_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
    redirect_uri = os.getenv("GITHUB_OAUTH_REDIRECT_URI", "https://nodeflow.up.railway.app/api/v1/auth/github/callback")
    if not client_id or not client_secret:
        raise HTTPException(503, "GitHub sign-in is not configured")
    return client_id, client_secret, redirect_uri


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1")


def platform(request: Request):
    return request.app.state.platform_store


def codec(request: Request) -> SessionCodec:
    return request.app.state.session_codec


def envelope(data):
    return {"success": True, "data": data, "error": None}


def token_from(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    return authorization.removeprefix("Bearer ")


def current(
    request: Request, authorization: str | None = Header(default=None)
) -> tuple[User, UUID | None, dict]:
    try:
        data = codec(request).read(token_from(authorization))
        user = platform(request).get_user(UUID(data["sub"]))
    except (ValueError, KeyError, PermissionError):
        raise HTTPException(401, "Invalid session")
    if platform(request).is_revoked(data.get("jti", "")):
        raise HTTPException(401, "Session revoked")
    return user, UUID(data["team"]) if data.get("team") else None, data


def require_project_access(
    request: Request, project_id: UUID, authorization: str | None = None
) -> None:
    """Production-only boundary used by Prem's existing routes."""
    if not request.app.state.enforce_tenants:
        return
    user, active_team, _ = current(request, authorization)
    if active_team is None:
        raise HTTPException(403, "Select an active team")
    try:
        platform(request).require_project(user.id, active_team, project_id)
    except PermissionError:
        raise HTTPException(404, "Project not found")


def active_team_for(request: Request, team_id: UUID, authorization: str | None) -> User:
    user, active, _ = current(request, authorization)
    if active != team_id:
        raise HTTPException(403, "Select the requested team as active")
    try:
        platform(request).require_member(user.id, team_id)
    except PermissionError:
        raise HTTPException(404, "Team not found")
    return user


def _member_role(request: Request, user: User, team_id: UUID) -> str:
    m = platform(request).require_member(user.id, team_id)
    return m.role


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@router.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, request: Request):
    try:
        user = platform(request).register(payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return envelope({
        "user": user.model_dump(mode="json"),
        "access_token": codec(request).issue(user.id),
        "token_type": "bearer",
    })


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request):
    try:
        user = platform(request).login(payload)
    except PermissionError as exc:
        raise HTTPException(401, str(exc))
    teams = platform(request).teams_for(user.id)
    active = teams[0].id if teams else None
    return envelope({
        "user": user.model_dump(mode="json"),
        "access_token": codec(request).issue(user.id, active),
        "token_type": "bearer",
    })


@router.get("/auth/github")
def github_login(request: Request):
    client_id, _client_secret, redirect_uri = github_configuration()
    nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    platform(request).remember_oauth_state(nonce)
    query = urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": codec(request).issue_oauth_state(nonce),
        "code_challenge": code_challenge(verifier),
        "code_challenge_method": "S256",
    })
    response = RedirectResponse(f"https://github.com/login/oauth/authorize?{query}")
    response.set_cookie(
        "nodeflow_oauth", f"{nonce}.{verifier}", max_age=600,
        httponly=True, secure=True, samesite="lax", path="/api/v1/auth/github",
    )
    return response


@router.get("/auth/github/callback")
def github_callback(
    code: str, state: str, request: Request,
    nodeflow_oauth: str | None = Cookie(default=None),
):
    try:
        nonce = codec(request).read_oauth_state(state)
        cookie_nonce, verifier = (nodeflow_oauth or "").split(".", 1)
        if not hmac.compare_digest(nonce, cookie_nonce) or not platform(request).consume_oauth_state(nonce):
            raise PermissionError("OAuth state was already used")
    except (ValueError, PermissionError):
        raise HTTPException(400, "Invalid or expired GitHub OAuth state")
    client_id, client_secret, redirect_uri = github_configuration()
    try:
        token_response = httpx.post(
            "https://github.com/login/oauth/access_token",
            data={"client_id": client_id, "client_secret": client_secret, "code": code,
                  "redirect_uri": redirect_uri, "code_verifier": verifier},
            headers={"Accept": "application/json"}, timeout=15,
        )
        access_token = token_response.json().get("access_token") if token_response.is_success else None
        if not access_token:
            raise HTTPException(401, "GitHub sign-in was rejected")
        profile_response = httpx.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        if not profile_response.is_success:
            raise HTTPException(401, "Could not read the GitHub profile")
        profile = profile_response.json()
        emails_response = httpx.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        emails = emails_response.json() if emails_response.is_success else []
    except httpx.HTTPError as exc:
        raise HTTPException(502, "GitHub sign-in is temporarily unavailable") from exc
    email = profile.get("email") or next(
        (item["email"] for item in emails if item.get("primary") and item.get("verified")), None
    )
    user = platform(request).github_user(str(profile["id"]), profile["login"], profile.get("name"), email)
    teams = platform(request).teams_for(user.id)
    active = teams[0].id if teams else None
    token = codec(request).issue(user.id, active)
    response = RedirectResponse("/#access_token=" + token, status_code=303)
    response.delete_cookie("nodeflow_oauth", path="/api/v1/auth/github")
    return response


@router.post("/auth/logout")
def logout(request: Request, authorization: str | None = Header(default=None)):
    _user, _team, data = current(request, authorization)
    platform(request).revoke(data["jti"])
    return envelope({"logged_out": True})


# ---------------------------------------------------------------------------
# Me / profile routes
# ---------------------------------------------------------------------------

@router.get("/me")
def me(request: Request, authorization: str | None = Header(default=None)):
    user, active, _ = current(request, authorization)
    teams = platform(request).teams_for(user.id)
    # Strip join codes from team list — admin-only endpoint exposes them
    teams_public = [
        TeamPublic(id=t.id, name=t.name, created_by=t.created_by, created_at=t.created_at)
        for t in teams
    ]
    return envelope({
        "user": user.model_dump(mode="json"),
        "teams": [t.model_dump(mode="json") for t in teams_public],
        "active_team_id": active,
    })


@router.post("/me/active-team")
def switch_team(
    payload: ActiveTeamRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    platform(request).require_member(user.id, payload.team_id)
    return envelope({
        "access_token": codec(request).issue(user.id, payload.team_id),
        "active_team_id": str(payload.team_id),
    })


# ---------------------------------------------------------------------------
# Team routes
# ---------------------------------------------------------------------------

@router.post("/teams", status_code=201)
def create_team(
    payload: TeamCreateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    try:
        team = platform(request).create_team(user, payload.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    # Return join code only to the creating owner (via access_token context)
    return envelope({
        "id": str(team.id), "name": team.name,
        "created_by": str(team.created_by), "created_at": team.created_at.isoformat(),
        "team_code": team.team_code,  # Returned once at creation; not in subsequent list calls
        "access_token": codec(request).issue(user.id, team.id),
        "active_team_id": str(team.id),
    })


@router.get("/teams")
def teams(request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    result = platform(request).teams_for(user.id)
    # Strip join codes from list
    return envelope([
        {"id": str(t.id), "name": t.name, "created_by": str(t.created_by), "created_at": t.created_at.isoformat()}
        for t in result
    ])


@router.get("/teams/{team_id}")
def get_team(
    team_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    try:
        platform(request).require_member(user.id, team_id)
        team = platform(request).get_team(team_id)
    except (KeyError, PermissionError):
        raise HTTPException(404, "Team not found")
    return envelope({
        "id": str(team.id), "name": team.name,
        "created_by": str(team.created_by), "created_at": team.created_at.isoformat(),
    })


@router.get("/teams/{team_id}/join-code")
def get_join_code(
    team_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    """Return the current join code — OWNER or ADMIN only."""
    user, _, _ = current(request, authorization)
    try:
        membership = platform(request).require_member(user.id, team_id)
    except PermissionError:
        raise HTTPException(404, "Team not found")
    Policy.require(membership.role, "read_join_code")
    team = platform(request).get_team(team_id)
    return envelope({"team_code": team.team_code})


@router.post("/teams/{team_id}/join-code/rotate")
def rotate_join_code(
    team_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    """Rotate the team join code — OWNER or ADMIN only."""
    user, _, _ = current(request, authorization)
    try:
        new_code = platform(request).rotate_join_code(user.id, team_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except LookupError:
        raise HTTPException(404, "Team not found")
    return envelope({"team_code": new_code})


@router.post("/teams/join")
def join_team(
    payload: JoinTeamRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    try:
        team = platform(request).join(user, payload.team_code)
        return envelope({
            "id": str(team.id), "name": team.name,
            "created_by": str(team.created_by), "created_at": team.created_at.isoformat(),
            "access_token": codec(request).issue(user.id, team.id),
            "active_team_id": str(team.id),
        })
    except LookupError:
        raise HTTPException(404, "Team not found")


@router.post("/teams/{team_id}/leave")
def leave_team(
    team_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    try:
        membership = platform(request).require_member(user.id, team_id)
    except PermissionError:
        raise HTTPException(404, "Team not found")
    if membership.role == "OWNER":
        owners = [m for m in platform(request).members_for(team_id) if m.role == "OWNER"]
        if len(owners) == 1:
            raise HTTPException(409, "Transfer ownership before leaving the team")
    platform(request).leave(user.id, team_id)
    return envelope({"left": True})


@router.get("/teams/{team_id}/members")
def members(
    team_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    ps = platform(request)
    try:
        ps.require_member(user.id, team_id)
    except PermissionError:
        raise HTTPException(403, "Forbidden")
    return envelope([{
        "id": m.user_id,
        "user_id": m.user_id,
        "name": ps.get_user(m.user_id).name,
        "email": ps.get_user(m.user_id).email,
        "role": m.role,
        "joined_at": m.joined_at,
    } for m in ps.members_for(team_id)])


@router.post("/teams/{team_id}/members", status_code=201)
def add_team_member(
    team_id: UUID, payload: TeamMemberAddRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    ps = platform(request)
    target = ps.user_for_email(payload.email)
    if not target:
        raise HTTPException(404, "No NodeFlow account exists for that email")
    try:
        membership = ps.add_member(user.id, team_id, target.id, payload.role.upper())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except LookupError as exc:
        raise HTTPException(405, str(exc))
    
    return envelope({
        "id": membership.user_id,
        "user_id": membership.user_id,
        "name": target.name,
        "email": target.email,
        "role": membership.role,
        "joined_at": membership.joined_at
    })

@router.patch("/teams/{team_id}/members/{target_user_id}")
def change_member_role(
    team_id: UUID, target_user_id: UUID,
    payload: ChangeMemberRoleRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    try:
        updated = platform(request).change_member_role(user.id, team_id, target_user_id, payload.role)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except LookupError:
        raise HTTPException(404, "Member not found")
    return envelope(updated.model_dump(mode="json"))


@router.delete("/teams/{team_id}/members/{target_user_id}", status_code=200)
def remove_member(
    team_id: UUID, target_user_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    try:
        platform(request).remove_member(user.id, team_id, target_user_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except LookupError:
        raise HTTPException(404, "Member not found")
    return envelope({"removed": True})


@router.post("/teams/{team_id}/transfer-ownership")
def transfer_ownership(
    team_id: UUID, payload: TransferOwnershipRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user, _, _ = current(request, authorization)
    try:
        platform(request).transfer_ownership(user.id, team_id, payload.new_owner_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except LookupError:
        raise HTTPException(404, "Member not found")
    token = codec(request).issue(user.id, team_id)
    return envelope({"access_token": token})


# ---------------------------------------------------------------------------
# Project routes (tenant-scoped, RBAC-aware)
# ---------------------------------------------------------------------------

@router.get("/teams/{team_id}/projects")
def list_team_projects(
    team_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    repository = request.app.state.container.repository
    projects = repository.list_projects() if hasattr(repository, "list_projects") else list(repository.projects.values())
    return envelope([p.model_dump(mode="json") for p in platform(request).list_projects(user.id, team_id, projects)])


@router.post("/teams/{team_id}/projects", status_code=201)
def create_team_project(
    team_id: UUID, payload: ProjectCreateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    role = _member_role(request, user, team_id)
    Policy.require(role, "create_project")
    project = Project(name=payload.name, purpose=payload.purpose, technology_stack=payload.technology_stack)
    saved = platform(request).create_project(user.id, team_id, project)
    repository = request.app.state.container.repository
    if isinstance(platform(request), PlatformStore):
        repository.projects[saved.id] = saved
    return envelope(saved.model_dump(mode="json"))


@router.patch("/teams/{team_id}/projects/{project_id}")
def update_team_project(
    team_id: UUID, project_id: UUID, payload: ProjectUpdateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    role = _member_role(request, user, team_id)
    Policy.require(role, "update_project")
    try:
        platform(request).require_project(user.id, team_id, project_id)
    except PermissionError:
        raise HTTPException(404, "Project not found")
    # Update in production store
    ps = platform(request)
    if isinstance(ps, SqlPlatformStore):
        updates = {}
        if payload.name is not None:
            updates["name"] = payload.name
        if payload.purpose is not None:
            updates["purpose"] = payload.purpose
        if updates:
            set_clause = ", ".join(f"{k}=:{k}" for k in updates)
            updates["id"] = str(project_id)
            ps.session.execute(
                text(f"UPDATE projects SET {set_clause} WHERE id=:id"),
                updates,
            )
    return envelope({"updated": True})


@router.post("/teams/{team_id}/projects/{project_id}/archive")
def archive_team_project(
    team_id: UUID, project_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    role = _member_role(request, user, team_id)
    Policy.require(role, "archive_project")
    try:
        platform(request).require_project(user.id, team_id, project_id)
    except PermissionError:
        raise HTTPException(404, "Project not found")
    ps = platform(request)
    if isinstance(ps, SqlPlatformStore):
        ps.session.execute(
            text("UPDATE projects SET status='archived' WHERE id=:id"),
            {"id": str(project_id)},
        )
    return envelope({"archived": True})


# ---------------------------------------------------------------------------
# GitHub repository routes
# ---------------------------------------------------------------------------

@router.get("/teams/{team_id}/github/repositories")
def list_github_repositories(
    team_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    return envelope([r.model_dump(mode="json") for r in platform(request).github_repositories_for(user.id, team_id)])


@router.post("/teams/{team_id}/github/repositories", status_code=201)
def connect_github_repository(
    team_id: UUID, payload: GitHubRepositoryConnectRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    role = _member_role(request, user, team_id)
    Policy.require(role, "connect_integration")
    try:
        platform(request).require_project(user.id, team_id, payload.project_id)
    except PermissionError:
        raise HTTPException(404, "Project not found")
    metadata = public_repository_metadata(payload.repository)
    try:
        existing = platform(request).github_repository_for(metadata["full_name"])
    except ValueError:
        raise HTTPException(409, "Repository connection is ambiguous")
    if existing and existing.project_id != payload.project_id:
        # Do not reveal which team owns it
        raise HTTPException(404, "GitHub repository not found")
    connected = platform(request).connect_github_repository(user.id, team_id, payload, metadata)
    try:
        sync = request.app.state.container.github_sync.sync(
            connected.project_id, connected.full_name, connected.default_branch
        )
    except RepositorySyncError as exc:
        raise HTTPException(502, str(exc))
    base_url = str(request.base_url).rstrip("/")
    return envelope({
        "repository": connected.model_dump(mode="json"),
        "sync": sync,
        "webhook_url": f"{base_url}/api/v1/integrations/github/webhook",
        "webhook_url_v2": f"{base_url}/api/v1/integrations/github/webhook/{connected.id}",
    })


@router.post("/teams/{team_id}/github/repositories/{project_id}/sync")
def sync_github_repository(
    team_id: UUID, project_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    try:
        platform(request).require_project(user.id, team_id, project_id)
    except PermissionError:
        raise HTTPException(404, "Project not found")
    connected = next(
        (r for r in platform(request).github_repositories_for(user.id, team_id) if r.project_id == project_id),
        None,
    )
    if connected is None:
        raise HTTPException(404, "GitHub repository not connected")
    try:
        return envelope(request.app.state.container.github_sync.sync(project_id, connected.full_name, connected.default_branch))
    except RepositorySyncError as exc:
        raise HTTPException(502, str(exc))


# ---------------------------------------------------------------------------
# Webhook ingestion (legacy global route + new per-connection route)
# ---------------------------------------------------------------------------

def _verify_webhook_signature(body: bytes, secret: str, signature_header: str | None) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(signature_header and hmac.compare_digest(expected, signature_header))


async def _process_webhook_body(
    request: Request,
    body: bytes,
    x_github_event: str | None,
    x_hub_signature_256: str | None,
    x_github_delivery: str | None,
    secret: str,
    repository_resolver,
):
    """Shared webhook processing logic."""
    if not _verify_webhook_signature(body, secret, x_hub_signature_256):
        raise HTTPException(401, "Invalid GitHub webhook signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid GitHub webhook payload")

    delivery_id = x_github_delivery or secrets.token_hex(16)
    payload_hash = hashlib.sha256(body).hexdigest()
    full_name = payload.get("repository", {}).get("full_name")
    if not full_name:
        raise HTTPException(400, "GitHub webhook repository is required")

    try:
        repository = repository_resolver(full_name)
    except ValueError:
        raise HTTPException(409, "Repository connection is ambiguous")
    if repository is None:
        raise HTTPException(404, "GitHub repository is not connected")

    # Idempotency: record delivery; return early if replay
    ps = platform(request)
    if isinstance(ps, SqlPlatformStore):
        is_new = ps.record_webhook_delivery(
            github_delivery_id=delivery_id,
            connection_id=repository.id,
            team_id=repository.team_id,
            project_id=repository.project_id,
            event_name=x_github_event or "",
            action=payload.get("action"),
            payload_hash=payload_hash,
        )
        if not is_new:
            logger.info("Replayed webhook delivery %s — returning idempotent response", delivery_id)
            return envelope({"replayed": True, "delivery_id": delivery_id})

    event = github_webhook_event(payload, x_github_event or "", repository.project_id)
    if event is None:
        if isinstance(ps, SqlPlatformStore):
            ps.mark_webhook_processed(delivery_id, "ignored")
        return envelope({"ignored": True})

    if x_github_event == "push" and event.ref == f"refs/heads/{repository.default_branch}":
        try:
            sync = request.app.state.container.github_sync.sync(
                repository.project_id, repository.full_name, repository.default_branch
            )
        except RepositorySyncError as exc:
            if isinstance(ps, SqlPlatformStore):
                ps.mark_webhook_processed(delivery_id, "failed", str(exc))
            raise HTTPException(502, str(exc))
        if isinstance(ps, SqlPlatformStore):
            ps.mark_webhook_processed(delivery_id, "processed")
        return envelope({"synchronized": True, "sync": sync, "delivery_id": delivery_id})

    result = request.app.state.container.git.ingest(event)
    if isinstance(ps, SqlPlatformStore):
        ps.mark_webhook_processed(delivery_id, "processed")
    return envelope(result)


@router.post("/integrations/github/webhook", status_code=202)
async def ingest_github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
):
    """Legacy global webhook route. Uses global GITHUB_WEBHOOK_SECRET.
    Deprecated: prefer /integrations/github/webhook/{connection_id}.
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "GitHub webhooks are not configured")
    body = await request.body()
    return await _process_webhook_body(
        request, body, x_github_event, x_hub_signature_256, x_github_delivery,
        secret,
        lambda full_name: platform(request).github_repository_for(full_name),
    )


@router.post("/integrations/github/webhook/{connection_id}", status_code=202)
async def ingest_github_webhook_v2(
    connection_id: UUID, request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
):
    """Per-connection webhook route with derived connection-specific secret."""
    body = await request.body()
    ps = platform(request)
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")

    if isinstance(ps, SqlPlatformStore):
        row = ps.session.execute(
            text(
                "SELECT id,team_id,project_id,full_name,default_branch,connection_secret_hash "
                "FROM team_github_repositories WHERE id=:id"
            ),
            {"id": str(connection_id)},
        ).first()
        if not row:
            raise HTTPException(404, "GitHub connection not found")

        # Verify using the derived connection secret
        derived_key = hmac.new(
            webhook_secret.encode(),
            f"{row.team_id}:{row.full_name}".encode(),
            hashlib.sha256,
        ).hexdigest()

        if not _verify_webhook_signature(body, derived_key, x_hub_signature_256):
            raise HTTPException(401, "Invalid GitHub webhook signature")

        from app.platform import GitHubRepository as GHRepo
        repo_obj = GHRepo(
            id=row.id, team_id=row.team_id, project_id=row.project_id,
            full_name=row.full_name, default_branch=row.default_branch,
            html_url="", connected_by=row.team_id,
        )
        resolver = lambda full_name: repo_obj
    else:
        # In-memory store: fall back to global secret
        secret = os.getenv("GITHUB_WEBHOOK_SECRET")
        if not secret:
            raise HTTPException(503, "GitHub webhooks are not configured")
        resolver = lambda full_name: ps.github_repository_for(full_name)
        derived_key = secret

    return await _process_webhook_body(
        request, body, x_github_event, x_hub_signature_256, x_github_delivery,
        derived_key, resolver,
    )

# ---------------------------------------------------------------------------
# Project resources CRUD (tenant-scoped, RBAC-aware, paginated)
# ---------------------------------------------------------------------------

@router.get("/teams/{team_id}/projects/{project_id}")
def get_team_project(
    team_id: UUID, project_id: UUID, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    role = _member_role(request, user, team_id)
    Policy.require(role, "read_project")
    try:
        platform(request).require_project(user.id, team_id, project_id)
    except PermissionError:
        raise HTTPException(404, "Project not found")
    
    repository = request.app.state.container.repository
    project = repository.get_project(project_id)
    return envelope(project.model_dump(mode="json"))

def _paginate(items: list, limit: int, cursor: str | None, key: str = "id"):
    limit = min(limit, 200)
    if cursor:
        items = [i for i in items if str(getattr(i, key)) > cursor]
    return items[:limit]

@router.get("/teams/{team_id}/projects/{project_id}/components")
def list_components(
    team_id: UUID, project_id: UUID, request: Request,
    limit: int = Query(50, le=200), cursor: str | None = None,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "read_component")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    components = request.app.state.container.repository.list_components(project_id)
    paginated = _paginate(sorted(components, key=lambda c: str(c.id)), limit, cursor)
    return envelope([c.model_dump(mode="json") for c in paginated])

from app.models import Component, Task, Agent, Decision, Memory, Event

class ComponentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    kind: str = Field(default="service", max_length=80)
    owner_role: str | None = Field(default=None, max_length=100)
    tags: list[str] = Field(default_factory=list)

@router.post("/teams/{team_id}/projects/{project_id}/components", status_code=201)
def create_component(
    team_id: UUID, project_id: UUID, payload: ComponentCreateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "update_project")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    repo = request.app.state.container.repository
    c = Component(project_id=project_id, **payload.model_dump())
    if hasattr(repo, "session"):
        from app.persistence import ComponentRow
        saved = repo._add(c, ComponentRow, Component)
    else:
        repo.components[c.id] = c
        saved = c
    return envelope(saved.model_dump(mode="json"))

@router.get("/teams/{team_id}/projects/{project_id}/tasks")
def list_tasks(
    team_id: UUID, project_id: UUID, request: Request,
    status: str | None = None,
    limit: int = Query(50, le=200), cursor: str | None = None,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "read_task")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    tasks = request.app.state.container.repository.list_tasks(project_id)
    if status: tasks = [t for t in tasks if t.status == status]
    paginated = _paginate(sorted(tasks, key=lambda t: str(t.id)), limit, cursor)
    return envelope([t.model_dump(mode="json") for t in paginated])

class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=4000)
    component_ids: list[UUID] = Field(default_factory=list)
    assignee_agent_ids: list[UUID] = Field(default_factory=list)

@router.post("/teams/{team_id}/projects/{project_id}/tasks", status_code=201)
def create_task(
    team_id: UUID, project_id: UUID, payload: TaskCreateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "update_project")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    repo = request.app.state.container.repository
    t = Task(project_id=project_id, **payload.model_dump())
    if hasattr(repo, "session"):
        from app.persistence import TaskRow
        saved = repo._add(t, TaskRow, Task)
    else:
        repo.tasks[t.id] = t
        saved = t
    return envelope(saved.model_dump(mode="json"))

class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=4000)

@router.patch("/teams/{team_id}/projects/{project_id}/tasks/{task_id}")
def update_task(
    team_id: UUID, project_id: UUID, task_id: UUID, payload: TaskUpdateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "update_project")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    repo = request.app.state.container.repository
    if hasattr(repo, "session"):
        updates = payload.model_dump(exclude_unset=True)
        if updates:
            set_clause = ", ".join(f"{k}=:{k}" for k in updates)
            updates["id"] = str(task_id)
            updates["project_id"] = str(project_id)
            repo.session.execute(text(f"UPDATE tasks SET {set_clause} WHERE id=:id AND project_id=:project_id"), updates)
            repo.session.flush()
    else:
        if task_id in repo.tasks:
            t = repo.tasks[task_id]
            if payload.title is not None: t.title = payload.title
            if payload.status is not None: t.status = payload.status
            if payload.description is not None: t.description = payload.description
    return envelope({"updated": True})

@router.get("/teams/{team_id}/projects/{project_id}/agents")
def list_agents(
    team_id: UUID, project_id: UUID, request: Request,
    limit: int = Query(50, le=200), cursor: str | None = None,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "read_agent")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    agents = request.app.state.container.repository.list_agents(project_id)
    paginated = _paginate(sorted(agents, key=lambda a: str(a.id)), limit, cursor)
    return envelope([a.model_dump(mode="json") for a in paginated])

class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    model_provider: str = Field(default="unknown", max_length=100)

@router.post("/teams/{team_id}/projects/{project_id}/agents", status_code=201)
def create_agent(
    team_id: UUID, project_id: UUID, payload: AgentCreateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "update_project")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    repo = request.app.state.container.repository
    a = Agent(project_id=project_id, **payload.model_dump())
    if hasattr(repo, "session"):
        from app.persistence import AgentRow
        saved = repo._add(a, AgentRow, Agent)
    else:
        repo.agents[a.id] = a
        saved = a
    return envelope(saved.model_dump(mode="json"))

@router.get("/teams/{team_id}/projects/{project_id}/decisions")
def list_decisions(
    team_id: UUID, project_id: UUID, request: Request,
    limit: int = Query(50, le=200), cursor: str | None = None,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "read_decision")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    items = request.app.state.container.repository.list_decisions(project_id)
    paginated = _paginate(sorted(items, key=lambda i: str(i.id)), limit, cursor)
    return envelope([i.model_dump(mode="json") for i in paginated])

class DecisionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=4000)
    component_ids: list[UUID] = Field(default_factory=list)

@router.post("/teams/{team_id}/projects/{project_id}/decisions", status_code=201)
def create_decision(
    team_id: UUID, project_id: UUID, payload: DecisionCreateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "update_project")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    repo = request.app.state.container.repository
    d = Decision(project_id=project_id, **payload.model_dump())
    if hasattr(repo, "session"):
        from app.persistence import DecisionRow
        saved = repo._add(d, DecisionRow, Decision)
    else:
        repo.decisions[d.id] = d
        saved = d
    return envelope(saved.model_dump(mode="json"))

@router.get("/teams/{team_id}/projects/{project_id}/memories")
def list_memories(
    team_id: UUID, project_id: UUID, request: Request,
    limit: int = Query(50, le=200), cursor: str | None = None,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "read_memory")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    items = request.app.state.container.repository.list_memories(project_id)
    paginated = _paginate(sorted(items, key=lambda i: str(i.id)), limit, cursor)
    return envelope([i.model_dump(mode="json") for i in paginated])

class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    component_ids: list[UUID] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

@router.post("/teams/{team_id}/projects/{project_id}/memories", status_code=201)
def create_memory(
    team_id: UUID, project_id: UUID, payload: MemoryCreateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "update_project")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    repo = request.app.state.container.repository
    m = Memory(project_id=project_id, **payload.model_dump())
    if hasattr(repo, "session"):
        from app.persistence import MemoryRow
        saved = repo._add(m, MemoryRow, Memory)
    else:
        repo.memories[m.id] = m
        saved = m
    return envelope(saved.model_dump(mode="json"))

@router.get("/teams/{team_id}/projects/{project_id}/events")
def list_events(
    team_id: UUID, project_id: UUID, request: Request,
    limit: int = Query(50, le=200), cursor: str | None = None,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "read_event")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    items = request.app.state.container.repository.list_events(project_id, limit=limit)
    paginated = _paginate(sorted(items, key=lambda i: str(i.id), reverse=True), limit, cursor)
    return envelope([i.model_dump(mode="json") for i in paginated])

@router.get("/teams/{team_id}/projects/{project_id}/approvals")
def list_approvals(
    team_id: UUID, project_id: UUID, request: Request,
    status: str | None = None,
    limit: int = Query(50, le=200), cursor: str | None = None,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "read_approval")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    ps = platform(request)
    if isinstance(ps, SqlPlatformStore):
        from app.services.approval import ApprovalService
        svc = ApprovalService(ps.session)
        reqs = svc.list_requests(project_id=project_id, status=status, limit=limit, cursor=cursor)
        return envelope(reqs)
    return envelope([])

class ApprovalCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    source_event_id: UUID | None = None

@router.post("/teams/{team_id}/projects/{project_id}/approvals", status_code=201)
def create_approval(
    team_id: UUID, project_id: UUID, payload: ApprovalCreateRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "create_approval_request")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    ps = platform(request)
    if isinstance(ps, SqlPlatformStore):
        from app.services.approval import ApprovalService
        svc = ApprovalService(ps.session)
        req = svc.create_request(
            project_id=project_id, team_id=team_id,
            title=payload.title, description=payload.description,
            source_event_id=payload.source_event_id
        )
        return envelope(req)
    return envelope({"id": str(uuid4()), "status": "waiting_approval", **payload.model_dump()})

@router.post("/teams/{team_id}/projects/{project_id}/approvals/{approval_id}/decide")
def decide_approval(
    team_id: UUID, project_id: UUID, approval_id: UUID, payload: ApprovalDecisionRequest, request: Request,
    authorization: str | None = Header(default=None),
):
    user = active_team_for(request, team_id, authorization)
    Policy.require(_member_role(request, user, team_id), "update_project")
    try: platform(request).require_project(user.id, team_id, project_id)
    except PermissionError: raise HTTPException(404, "Project not found")
    
    ps = platform(request)
    if isinstance(ps, SqlPlatformStore):
        from app.services.approval import ApprovalService
        svc = ApprovalService(ps.session)
        try:
            decision = svc.make_decision(
                approval_request_id=approval_id, project_id=project_id,
                decision=payload.decision, actor_name=payload.actor_name, comment=payload.comment
            )
            return envelope(decision)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
    return envelope({"decision": payload.decision, "approval_request_id": str(approval_id)})

