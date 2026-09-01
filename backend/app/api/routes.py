from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.schemas.common import success
from app.schemas.intelligence import EventCreate, MessageCreate, OnboardingRequest


router = APIRouter(prefix="/api/v1")


def services(request: Request):
    return request.app.state.container


@router.get("/projects/{project_id}")
def get_project(project_id: UUID, request: Request):
    return success(services(request).repository.get_project(project_id))


@router.get("/projects/{project_id}/context")
def get_project_context(project_id: UUID, request: Request):
    return success(services(request).brain.get_project_context(project_id))


@router.get("/projects/{project_id}/state")
def get_project_state(project_id: UUID, request: Request):
    return success(services(request).brain.get_project_state(project_id))


@router.get("/projects/{project_id}/architecture")
def get_architecture(project_id: UUID, request: Request):
    return success(services(request).brain.get_architecture(project_id))


@router.get("/projects/{project_id}/decisions")
def get_decisions(project_id: UUID, request: Request):
    container = services(request)
    container.repository.get_project(project_id)
    return success(container.repository.list_decisions(project_id))


@router.get("/projects/{project_id}/memory")
def get_memory(project_id: UUID, request: Request, query: str = Query(default="")):
    return success(services(request).brain.get_relevant_memory(project_id, query))


@router.get("/agents/{agent_id}/context")
def get_agent_context(
    agent_id: UUID,
    request: Request,
    scope: Literal["my_work", "team", "related", "project"] = Query(default="related"),
):
    return success(services(request).context.get_agent_context(agent_id, scope))


@router.get("/agents/{agent_id}/updates")
def get_agent_updates(agent_id: UUID, request: Request):
    return success(services(request).repository.list_updates(agent_id))


@router.post("/events", status_code=201)
def create_event(payload: EventCreate, request: Request):
    return success(services(request).events.process(payload))


@router.post("/agents/{agent_id}/messages", status_code=201)
def send_agent_message(agent_id: UUID, payload: MessageCreate, request: Request):
    return success(services(request).messaging.send(agent_id, payload))


@router.post("/onboarding")
def create_onboarding(payload: OnboardingRequest, request: Request):
    return success(services(request).onboarding.build(payload))
