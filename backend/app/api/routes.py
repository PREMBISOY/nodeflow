from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.schemas.common import success
from app.schemas.intelligence import ApprovalDecisionCreate, EventCreate, GitHubEventCreate, MessageCreate, OnboardingRequest
from app.services.team_scope import require_active_team_project


router = APIRouter(prefix="/api/v1")


def services(request: Request):
    return request.app.state.container


def require_agent_project_scope(agent_id: UUID, request: Request):
    agent = services(request).repository.get_agent(agent_id)
    require_active_team_project(request, agent.project_id)
    return agent


def is_team_scoped_product_event(payload: EventCreate) -> bool:
    return (
        payload.event_type.startswith("github_")
        or payload.event_type == "collaboration_approval_decision"
        or payload.payload.get("provider") == "github"
    )


@router.get("/projects/{project_id}")
def get_project(project_id: UUID, request: Request):
    return success(services(request).repository.get_project(project_id))


@router.get("/projects/{project_id}/context")
def get_project_context(project_id: UUID, request: Request):
    return success(services(request).brain.get_project_context(project_id))


@router.get("/projects/{project_id}/collaboration")
def get_collaboration_state(project_id: UUID, request: Request):
    require_active_team_project(request, project_id)
    return success(services(request).collaboration.get_state(project_id))


@router.post("/projects/{project_id}/collaboration/approvals/{approval_event_id}")
def decide_approval(
    project_id: UUID, approval_event_id: UUID, payload: ApprovalDecisionCreate, request: Request
):
    if project_id != payload.project_id:
        raise ValueError("Project ID must match the approval request")
    require_active_team_project(request, project_id)
    return success(services(request).collaboration.decide_approval(approval_event_id, payload))


@router.get("/agents/{agent_id}/context")
def get_agent_context(
    agent_id: UUID,
    request: Request,
    scope: Literal["my_work", "team", "related", "project"] = Query(default="related"),
    task_id: UUID | None = Query(default=None),
):
    require_agent_project_scope(agent_id, request)
    return success(services(request).context.get_agent_context(agent_id, scope, task_id))


@router.get("/agents/{agent_id}/updates")
def get_agent_updates(agent_id: UUID, request: Request):
    require_agent_project_scope(agent_id, request)
    return success(services(request).repository.list_updates(agent_id))


@router.post("/events", status_code=201)
def create_event(payload: EventCreate, request: Request):
    if is_team_scoped_product_event(payload):
        require_active_team_project(request, payload.project_id)
    return success(services(request).events.process(payload))


@router.post("/integrations/github/events", status_code=201)
def ingest_github_event(payload: GitHubEventCreate, request: Request):
    require_active_team_project(request, payload.project_id)
    return success(services(request).git.ingest(payload))


@router.get("/projects/{project_id}/git/activity")
def get_git_activity(project_id: UUID, request: Request):
    require_active_team_project(request, project_id)
    return success(services(request).git.get_activity(project_id))


@router.post("/agents/{agent_id}/messages", status_code=201)
def send_agent_message(agent_id: UUID, payload: MessageCreate, request: Request):
    require_agent_project_scope(agent_id, request)
    return success(services(request).messaging.send(agent_id, payload))


@router.post("/onboarding")
def create_onboarding(payload: OnboardingRequest, request: Request):
    require_active_team_project(request, payload.project_id)
    return success(services(request).onboarding.build(payload))
