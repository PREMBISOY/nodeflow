"""Stable domain contracts shared by API, persistence, and intelligence services."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

def utc_now() -> datetime: return datetime.now(timezone.utc)

class Entity(BaseModel):
    id: UUID = Field(default_factory=uuid4)

class Project(Entity):
    name: str
    description: str = ""
    repository_url: str | None = None
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class User(Entity):
    project_id: UUID
    name: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

class Role(Entity):
    project_id: UUID
    name: str
    permissions: list[str] = Field(default_factory=list)
    description: str = ""

class Component(Entity):
    project_id: UUID
    name: str
    type: str = "service"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

class Relationship(Entity):
    project_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: str = "DEPENDS_ON"
    metadata: dict[str, Any] = Field(default_factory=dict)

class Agent(Entity):
    project_id: UUID
    owner_id: UUID | None = None
    name: str
    provider: str = "unknown"
    model: str | None = None
    role: str
    capabilities: list[str] = Field(default_factory=list)
    status: str = "ACTIVE"
    created_at: datetime = Field(default_factory=utc_now)

class Task(Entity):
    project_id: UUID
    title: str
    description: str = ""
    owner_id: UUID | None = None
    agent_id: UUID | None = None
    status: str = "TODO"
    priority: str = "MEDIUM"
    affected_components: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class Event(Entity):
    project_id: UUID
    actor_type: str = "system"
    actor_id: UUID | None = None
    event_type: str
    description: str
    affected_components: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)

class Memory(Entity):
    project_id: UUID
    type: str = "PROJECT_FACT"
    content: str
    source: str | None = None
    related_components: list[UUID] = Field(default_factory=list)
    related_agents: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

class Decision(Entity):
    project_id: UUID
    title: str
    decision: str
    rationale: str
    created_by: UUID | None = None
    affected_components: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

class Change(Entity):
    project_id: UUID
    component_id: UUID | None = None
    summary: str
    change_type: str = "MODIFIED"
    source_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

class Message(Entity):
    project_id: UUID
    sender_agent_id: UUID
    recipient_agent_id: UUID
    message_type: str = "AGENT_MESSAGE"
    subject: str
    content: str
    related_components: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

class ContextUpdate(Entity):
    project_id: UUID
    recipient_agent_id: UUID
    source_event_id: UUID
    subject: str
    content: str
    related_components: list[UUID] = Field(default_factory=list)
    relevance_score: float = 1.0
    created_at: datetime = Field(default_factory=utc_now)
    read: bool = False
