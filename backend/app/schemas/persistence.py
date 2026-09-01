from __future__ import annotations
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field
from app.models import Agent, Decision, Event, Memory, Project, Task

ContextScope = Literal["my_work", "team", "related", "project"]
class TaskCreate(BaseModel):
    project_id: UUID; title: str; description: str = ""; owner_id: UUID | None = None; agent_id: UUID | None = None; priority: str = "MEDIUM"; affected_components: list[UUID] = Field(default_factory=list)
class TaskUpdate(BaseModel):
    status: Literal["TODO", "IN_PROGRESS", "BLOCKED", "COMPLETED"] | None = None
    owner_id: UUID | None = None
    agent_id: UUID | None = None
    priority: str | None = None
    affected_components: list[UUID] | None = None
class EventCreate(BaseModel):
    project_id: UUID; event_type: str; description: str; actor_type: str = "system"; actor_id: UUID | None = None; affected_components: list[UUID] = Field(default_factory=list); metadata: dict = Field(default_factory=dict)
class DecisionCreate(BaseModel):
    project_id: UUID; title: str; decision: str; rationale: str; created_by: UUID | None = None; affected_components: list[UUID] = Field(default_factory=list)
class MemoryCreate(BaseModel):
    project_id: UUID; type: str = "PROJECT_FACT"; content: str; source: str | None = None; related_components: list[UUID] = Field(default_factory=list); related_agents: list[UUID] = Field(default_factory=list); metadata: dict = Field(default_factory=dict)
class MessageCreate(BaseModel):
    project_id: UUID; recipient_agent_id: UUID; subject: str; content: str; message_type: str = "AGENT_MESSAGE"; related_components: list[UUID] = Field(default_factory=list)
class ProjectState(BaseModel):
    project: Project; task_counts: dict[str, int]; agent_counts: dict[str, int]; recent_events: list[Event]; components: int
class AgentContext(BaseModel):
    agent: Agent; scope: ContextScope; tasks: list[Task]; memories: list[Memory]; decisions: list[Decision]; events: list[Event]
