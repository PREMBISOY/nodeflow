from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import Agent, Change, Component, Decision, Event, Memory, Project, Relationship, Task


ContextScope = Literal["my_work", "team", "related", "project"]


class ProjectContext(BaseModel):
    project: Project
    components: list[Component]
    relationships: list[Relationship]
    tasks: list[Task]
    agents: list[Agent]
    recent_events: list[Event]
    decisions: list[Decision]
    memories: list[Memory]
    recent_changes: list[Change]


class ComponentContext(BaseModel):
    component: Component
    relationships: list[Relationship]
    related_components: list[Component]
    tasks: list[Task]
    agents: list[Agent]
    decisions: list[Decision]
    memories: list[Memory]
    recent_events: list[Event]


class ImpactAnalysisResult(BaseModel):
    change: Change
    affected_components: list[Component]
    affected_agents: list[Agent]
    affected_tasks: list[Task]
    relevant_roles: list[str]
    impact_level: Literal["low", "medium", "high"]
    reasoning: list[str]


class EventCreate(BaseModel):
    project_id: UUID
    event_type: str
    actor_type: Literal["human", "agent", "system"] = "system"
    actor_id: UUID | None = None
    entity_id: UUID | None = None
    component_ids: list[UUID] = Field(default_factory=list)
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    change: "ChangeCreate | None" = None


class ChangeCreate(BaseModel):
    component_id: UUID
    summary: str
    change_type: str = "modified"
    source_ref: str | None = None


class EventProcessingResult(BaseModel):
    event: Event
    impact: ImpactAnalysisResult | None
    propagated_to: list[UUID]


class MessageCreate(BaseModel):
    recipient_agent_id: UUID
    message_type: str = "context_update"
    subject: str
    content: str
    related_components: list[UUID] = Field(default_factory=list)


class OnboardingRequest(BaseModel):
    project_id: UUID
    name: str
    role: str
    agent_id: UUID | None = None
    scope: ContextScope = "related"
    question: str = "Explain this project to me."


class OnboardingPackage(BaseModel):
    project: Project
    role: str
    architecture: list[str]
    major_components: list[Component]
    technology_stack: list[str]
    current_state: dict[str, Any]
    relevant_tasks: list[Task]
    important_decisions: list[Decision]
    recent_changes: list[Change]
    role_specific_information: list[str]
    recommended_starting_points: list[str]
    briefing: str
