"""Product-layer bridge to the authentication and tenant-authorization owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class ActiveTeamProjectAccess:
    """Authorization result supplied by upstream auth/team middleware."""

    user_id: str
    active_team_id: UUID
    authorized_project_ids: frozenset[UUID]


class ActiveTeamProjectResolver(Protocol):
    def __call__(self, request: Request) -> ActiveTeamProjectAccess: ...


def require_active_team_project(request: Request, project_id: UUID) -> ActiveTeamProjectAccess | None:
    """Ensure a product workflow stays inside the caller's selected team/project.

    Aayush's auth/team layer attaches ``team_project_resolver`` to app state.
    Demo mode may explicitly opt out; deployed environments must set
    ``require_team_scope`` so missing integration fails closed.
    """

    resolver = getattr(request.app.state, "team_project_resolver", None)
    if resolver is None:
        if getattr(request.app.state, "require_team_scope", False):
            raise HTTPException(
                status_code=503,
                detail="Active team/project authorization is not configured",
            )
        return None

    access = resolver(request)
    if not access.active_team_id or project_id not in access.authorized_project_ids:
        raise HTTPException(status_code=403, detail="Project is outside the active team scope")
    return access
