from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request

from app.schemas.common import success
from app.schemas.intelligence import ApprovalDecisionCreate, EventCreate, GitHubEventCreate, MessageCreate, OnboardingRequest
from app.platform import require_project_access


router = APIRouter(prefix="/api/v1")


def services(request: Request):
    return request.app.state.container


@router.get("/projects/{project_id}")
def get_project(project_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, project_id, authorization)
    return success(services(request).repository.get_project(project_id))


@router.get("/projects/{project_id}/context")
def get_project_context(project_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, project_id, authorization)
    return success(services(request).brain.get_project_context(project_id))


@router.get("/projects/{project_id}/state")
def get_project_state(project_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, project_id, authorization)
    return success(services(request).brain.get_project_state(project_id))


@router.get("/projects/{project_id}/architecture")
def get_project_architecture(project_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, project_id, authorization)
    return success(services(request).brain.get_architecture(project_id))


@router.get("/projects/{project_id}/components/{component_id}/context")
def get_component_context(
    project_id: UUID,
    component_id: UUID,
    request: Request,
    authorization: str | None = Header(default=None),
):
    require_project_access(request, project_id, authorization)
    return success(services(request).brain.get_component_context(project_id, component_id))


@router.get("/projects/{project_id}/decisions")
def get_project_decisions(project_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, project_id, authorization)
    services(request).repository.get_project(project_id)
    return success(services(request).repository.list_decisions(project_id))


@router.get("/projects/{project_id}/memory")
def get_project_memory(
    project_id: UUID,
    request: Request,
    query: str = Query(default="", max_length=2_000),
    authorization: str | None = Header(default=None),
):
    require_project_access(request, project_id, authorization)
    return success(services(request).brain.get_relevant_memory(project_id, query))


@router.get("/projects/{project_id}/collaboration")
def get_collaboration_state(project_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, project_id, authorization)
    return success(services(request).collaboration.get_state(project_id))


@router.post("/projects/{project_id}/collaboration/approvals/{approval_event_id}")
def decide_approval(
    project_id: UUID, approval_event_id: UUID, payload: ApprovalDecisionCreate, request: Request, authorization: str | None = Header(default=None)
):
    require_project_access(request, project_id, authorization)
    if project_id != payload.project_id:
        raise ValueError("Project ID must match the approval request")
    return success(services(request).collaboration.decide_approval(approval_event_id, payload))


@router.get("/agents/{agent_id}/context")
def get_agent_context(
    agent_id: UUID,
    request: Request,
    scope: Literal["my_work", "team", "related", "project"] = Query(default="related"),
    task_id: UUID | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    require_project_access(request, services(request).repository.get_agent(agent_id).project_id, authorization)
    return success(services(request).context.get_agent_context(agent_id, scope, task_id))


@router.get("/agents/{agent_id}/updates")
def get_agent_updates(agent_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, services(request).repository.get_agent(agent_id).project_id, authorization)
    return success(services(request).repository.list_updates(agent_id))


@router.post("/events", status_code=201)
def create_event(payload: EventCreate, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, payload.project_id, authorization)
    return success(services(request).events.process(payload))


@router.post("/integrations/github/events", status_code=201)
def ingest_github_event(payload: GitHubEventCreate, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, payload.project_id, authorization)
    return success(services(request).git.ingest(payload))


@router.get("/projects/{project_id}/git/activity")
def get_git_activity(project_id: UUID, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, project_id, authorization)
    return success(services(request).git.get_activity(project_id))


@router.post("/agents/{agent_id}/messages", status_code=201)
def send_agent_message(agent_id: UUID, payload: MessageCreate, request: Request, authorization: str | None = Header(default=None)):
    sender = services(request).repository.get_agent(agent_id)
    require_project_access(request, sender.project_id, authorization)
    recipient = services(request).repository.get_agent(payload.recipient_agent_id)
    if sender.project_id != recipient.project_id:
        raise ValueError("Sender and recipient agents must belong to the same project")
    return success(services(request).messaging.send(agent_id, payload))


@router.post("/onboarding")
def create_onboarding(payload: OnboardingRequest, request: Request, authorization: str | None = Header(default=None)):
    require_project_access(request, payload.project_id, authorization)
    return success(services(request).onboarding.build(payload))
