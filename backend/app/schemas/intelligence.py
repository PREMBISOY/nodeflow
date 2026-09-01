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
    affected_component_distances: dict[UUID, int] = Field(default_factory=dict)
    affected_agents: list[Agent]
    affected_tasks: list[Task]
    relevant_roles: list[str]
    impact_level: Literal["low", "medium", "high"]
    reasoning: list[str]


class EventCreate(BaseModel):
    project_id: UUID
    event_type: str = Field(min_length=1, max_length=100)
    actor_type: Literal["human", "agent", "system"] = "system"
    actor_id: UUID | None = None
    entity_id: UUID | None = None
    component_ids: list[UUID] = Field(default_factory=list, max_length=100)
    summary: str = Field(min_length=1, max_length=2_000)
    payload: dict[str, Any] = Field(default_factory=dict)
    change: "ChangeCreate | None" = None
    changes: list["ChangeCreate"] = Field(default_factory=list, max_length=50)


class ChangeCreate(BaseModel):
    component_id: UUID
    summary: str = Field(min_length=1, max_length=2_000)
    change_type: str = Field(default="modified", min_length=1, max_length=60)
    source_ref: str | None = Field(default=None, max_length=2_000)


class EventProcessingResult(BaseModel):
    event: Event
    impact: ImpactAnalysisResult | None
    impacts: list[ImpactAnalysisResult] = Field(default_factory=list)
    propagated_to: list[UUID]


class GitHubEventCreate(BaseModel):
    """A small, provider-neutral GitHub payload used to create Project Intelligence events."""

    project_id: UUID
    event_type: Literal["commit", "pull_request", "branch"]
    action: Literal["created", "updated", "opened", "synchronized", "merged", "closed"] | None = None
    repository: str = Field(min_length=3, max_length=300)
    summary: str = Field(min_length=1, max_length=2_000)
    changed_files: list[str] = Field(default_factory=list, max_length=5_000)
    ref: str | None = Field(default=None, max_length=1_000)
    commit_sha: str | None = Field(default=None, max_length=100)
    pull_request_number: int | None = None
    actor_name: str | None = Field(default=None, max_length=200)
    requires_approval: bool | None = None


class ApprovalDecisionCreate(BaseModel):
    project_id: UUID
    decision: Literal["approved", "rejected"]
    actor_name: str
    comment: str = ""


class MessageCreate(BaseModel):
    recipient_agent_id: UUID
    message_type: str = Field(default="context_update", min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20_000)
    related_components: list[UUID] = Field(default_factory=list, max_length=100)


class OnboardingRequest(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    agent_id: UUID | None = None
    scope: ContextScope = "related"
    question: str = Field(default="Explain this project to me.", min_length=1, max_length=2_000)


class OnboardingPackage(BaseModel):
    project: Project
    role: str
    architecture: list[str]
    major_components: list[Component]
    technology_stack: list[str]
    current_state: dict[str, Any]
    relevant_tasks: list[Task]
    important_decisions: list[Decision]
    relevant_memories: list[Memory]
    recent_changes: list[Change]
    role_specific_information: list[str]
    recommended_starting_points: list[str]
    briefing: str
