"""Minimal shared entities used by the intelligence layer.

These models deliberately contain only the fields required by the core services.
The persistence owner can map database models to these contracts without changing
the reasoning layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Project(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    purpose: str
    technology_stack: list[str] = Field(default_factory=list)
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)


class Component(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    name: str
    description: str = ""
    kind: str = "service"
    owner_role: str | None = None
    tags: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    source_component_id: UUID
    target_component_id: UUID
    relationship_type: str = "depends_on"
    description: str = ""


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    title: str
    status: str = "todo"
    component_ids: list[UUID] = Field(default_factory=list)
    assignee_agent_ids: list[UUID] = Field(default_factory=list)
    description: str = ""


class Agent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    name: str
    role: str
    model_provider: str = "unknown"
    component_ids: list[UUID] = Field(default_factory=list)
    current_task_ids: list[UUID] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    active: bool = True


class Event(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    event_type: str
    actor_type: Literal["human", "agent", "system"] = "system"
    actor_id: UUID | None = None
    entity_id: UUID | None = None
    component_ids: list[UUID] = Field(default_factory=list)
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class Decision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    title: str
    rationale: str
    component_ids: list[UUID] = Field(default_factory=list)
    status: str = "accepted"
    created_at: datetime = Field(default_factory=utc_now)


class Memory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    content: str
    component_ids: list[UUID] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class Change(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    component_id: UUID
    summary: str
    change_type: str = "modified"
    source_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ContextUpdate(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    recipient_agent_id: UUID
    source_event_id: UUID
    subject: str
    content: str
    related_component_ids: list[UUID] = Field(default_factory=list)
    relevance_score: float
    created_at: datetime = Field(default_factory=utc_now)
    read: bool = False


class Message(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    sender_agent_id: UUID
    recipient_agent_id: UUID
    message_type: str
    subject: str
    content: str
    related_component_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
