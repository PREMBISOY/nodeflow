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
def platform(request: Request) -> PlatformStore: return request.app.state.platform_store
def codec(request: Request) -> SessionCodec: return request.app.state.session_codec
def envelope(data): return {"success": True, "data": data, "error": None}
def token_from(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Authentication required")
    return authorization.removeprefix("Bearer ")
def current(request: Request, authorization: str | None = Header(default=None)) -> tuple[User, UUID | None, dict]:
    try: data = codec(request).read(token_from(authorization)); user = platform(request).users[UUID(data["sub"])]
    except (ValueError, KeyError, PermissionError): raise HTTPException(401, "Invalid session")
    if data["jti"] in platform(request).revoked: raise HTTPException(401, "Session revoked")
    return user, UUID(data["team"]) if data.get("team") else None, data

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
    _user, _team, data = current(request, authorization); platform(request).revoked.add(data["jti"]); return envelope({"logged_out": True})
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
    try: platform(request).require_member(user.id, team_id); return envelope(platform(request).teams[team_id])
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
        owners = [m for m in platform(request).memberships.values() if m.team_id == team_id and m.role == "OWNER"]
        if len(owners) == 1: raise HTTPException(409, "Transfer ownership before leaving the team")
    del platform(request).memberships[(user.id, team_id)]
    return envelope({"left": True})
@router.get("/teams/{team_id}/members")
def members(team_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    user, _, _ = current(request, authorization)
    try: platform(request).require_member(user.id, team_id)
    except PermissionError: raise HTTPException(403, "Forbidden")
    return envelope([membership for membership in platform(request).memberships.values() if membership.team_id == team_id])
