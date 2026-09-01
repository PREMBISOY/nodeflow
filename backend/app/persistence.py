"""SQLAlchemy implementation of Prem's ``ProjectKnowledgeRepository`` protocol.

This module deliberately maps the existing Pydantic entities without changing
their fields or requiring the intelligence services to know about SQLAlchemy.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid, create_engine, delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from app.models import Agent, Change, Component, ContextUpdate, Decision, Event, Memory, Message, Project, Relationship, Task
from app.services.repository import EntityNotFoundError

JSONType = JSON().with_variant(JSONB, "postgresql")
# Generic UUID remains native on PostgreSQL while storing safely as CHAR(32) in
# SQLite, which is what keeps the adapter's contract tests portable.
SQLUUID = Uuid
ModelT = TypeVar("ModelT")


class Base(DeclarativeBase):
    pass


class IdRow:
    id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True)


class ProjectRow(IdRow, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(Text)
    technology_stack: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(40), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComponentRow(IdRow, Base):
    __tablename__ = "components"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(80), default="service")
    owner_role: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)


class RelationshipRow(IdRow, Base):
    __tablename__ = "relationships"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    source_component_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("components.id"), index=True)
    target_component_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("components.id"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(80), default="depends_on")
    description: Mapped[str] = mapped_column(Text, default="")


class TaskRow(IdRow, Base):
    __tablename__ = "tasks"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40), default="todo")
    component_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    assignee_agent_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    description: Mapped[str] = mapped_column(Text, default="")


class AgentRow(IdRow, Base):
    __tablename__ = "agents"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(100))
    model_provider: Mapped[str] = mapped_column(String(100), default="unknown")
    component_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    current_task_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    capabilities: Mapped[list[str]] = mapped_column(JSONType, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class EventRow(IdRow, Base):
    __tablename__ = "events"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    actor_type: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[UUID | None] = mapped_column(SQLUUID(as_uuid=True), index=True)
    entity_id: Mapped[UUID | None] = mapped_column(SQLUUID(as_uuid=True))
    component_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DecisionRow(IdRow, Base):
    __tablename__ = "decisions"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str] = mapped_column(Text)
    component_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(40), default="accepted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryRow(IdRow, Base):
    __tablename__ = "memories"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    component_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChangeRow(IdRow, Base):
    __tablename__ = "changes"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    component_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("components.id"))
    summary: Mapped[str] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(60), default="modified")
    source_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageRow(IdRow, Base):
    __tablename__ = "messages"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    sender_agent_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("agents.id"), index=True)
    recipient_agent_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("agents.id"), index=True)
    message_type: Mapped[str] = mapped_column(String(80))
    subject: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    related_component_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContextUpdateRow(IdRow, Base):
    __tablename__ = "context_updates"
    project_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    recipient_agent_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("agents.id"), index=True)
    source_event_id: Mapped[UUID] = mapped_column(SQLUUID(as_uuid=True), ForeignKey("events.id"))
    subject: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    related_component_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    relevance_score: Mapped[float]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read: Mapped[bool] = mapped_column(Boolean, default=False)


def build_session_factory(database_url: str):
    """Create a SQLAlchemy factory; production URL is PostgreSQL/Supabase."""
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    # Supabase's pooled endpoint uses PgBouncer transaction pooling. psycopg's
    # server-side prepared statements are connection-local and can collide when
    # PgBouncer reuses a server connection across client sessions.
    engine_options = {"pool_pre_ping": True}
    if database_url.startswith("postgresql+psycopg://"):
        engine_options["connect_args"] = {"prepare_threshold": None}
    return sessionmaker(create_engine(database_url, **engine_options), expire_on_commit=False)


class SqlAlchemyProjectRepository:
    """Persistent adapter implementing the existing ``ProjectKnowledgeRepository`` protocol."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _data(entity: Any) -> dict[str, Any]:
        data = entity.model_dump()
        json_data = entity.model_dump(mode="json")
        # Keep UUID primary/foreign keys native for SQLAlchemy, but encode UUIDs
        # held inside JSONB arrays and payloads.
        for name in (
            "technology_stack", "tags", "component_ids", "assignee_agent_ids",
            "current_task_ids", "capabilities", "related_component_ids", "payload",
        ):
            if name in data:
                data[name] = json_data[name]
        return data

    @staticmethod
    def _entity(row: Any, model: type[ModelT]) -> ModelT:
        return model.model_validate({column.name: getattr(row, column.name) for column in row.__table__.columns})

    def _add(self, entity: ModelT, row_type: type[Any], model: type[ModelT]) -> ModelT:
        row = row_type(**self._data(entity))
        self.session.add(row)
        # flush() detects constraint violations without committing; the
        # request-scoped unit-of-work middleware owns the final commit.
        self.session.flush()
        self.session.refresh(row)
        return self._entity(row, model)

    def _get(self, row_type: type[Any], model: type[ModelT], entity_id: UUID) -> ModelT:
        row = self.session.get(row_type, entity_id)
        if row is None:
            raise EntityNotFoundError(model.__name__, entity_id)
        return self._entity(row, model)

    def _list(self, row_type: type[Any], model: type[ModelT], project_id: UUID, order: Any | None = None, limit: int | None = None) -> list[ModelT]:
        query = select(row_type).where(row_type.project_id == project_id)
        if order is not None:
            query = query.order_by(order.desc())
        if limit is not None:
            query = query.limit(limit)
        return [self._entity(row, model) for row in self.session.scalars(query)]

    def get_project(self, project_id: UUID) -> Project: return self._get(ProjectRow, Project, project_id)
    def list_projects(self) -> list[Project]: return [self._entity(row, Project) for row in self.session.scalars(select(ProjectRow))]
    def get_component(self, component_id: UUID) -> Component: return self._get(ComponentRow, Component, component_id)
    def get_agent(self, agent_id: UUID) -> Agent: return self._get(AgentRow, Agent, agent_id)
    def list_components(self, project_id: UUID) -> list[Component]:
        return [item for item in self._list(ComponentRow, Component, project_id) if "state:stale" not in item.tags]
    def list_relationships(self, project_id: UUID) -> list[Relationship]: return self._list(RelationshipRow, Relationship, project_id)
    def list_tasks(self, project_id: UUID) -> list[Task]: return self._list(TaskRow, Task, project_id)
    def list_agents(self, project_id: UUID) -> list[Agent]: return self._list(AgentRow, Agent, project_id)
    def list_events(self, project_id: UUID, limit: int = 25) -> list[Event]: return self._list(EventRow, Event, project_id, EventRow.created_at, limit)
    def list_decisions(self, project_id: UUID) -> list[Decision]: return self._list(DecisionRow, Decision, project_id)
    def list_memories(self, project_id: UUID) -> list[Memory]: return self._list(MemoryRow, Memory, project_id)
    def list_changes(self, project_id: UUID, limit: int = 25) -> list[Change]: return self._list(ChangeRow, Change, project_id, ChangeRow.created_at, limit)
    def sync_github_architecture(self, project_id: UUID, components: list[Component], relationships: list[Relationship]) -> None:
        generated = [row for row in self.session.scalars(select(ComponentRow).where(ComponentRow.project_id == project_id)) if "source:github" in (row.tags or [])]
        current_ids = {item.id for item in components}
        for row in generated:
            if row.id not in current_ids:
                row.tags = [tag for tag in (row.tags or []) if tag != "state:stale"] + ["state:stale"]
        self.session.execute(delete(RelationshipRow).where(RelationshipRow.project_id == project_id, RelationshipRow.description.startswith("GitHub-derived:")))
        for component in components:
            self.session.merge(ComponentRow(**self._data(component)))
        self.session.flush()
        for relationship in relationships:
            self.session.merge(RelationshipRow(**self._data(relationship)))
        self.session.flush()
    def has_github_commit(self, project_id: UUID, repository: str, commit_sha: str) -> bool:
        events = self.session.scalars(select(EventRow).where(EventRow.project_id == project_id, EventRow.event_type == "github_commit"))
        return any(event.payload.get("repository", "").casefold() == repository.casefold() and event.payload.get("commit_sha") == commit_sha for event in events)
    def add_event(self, event: Event) -> Event: return self._add(event, EventRow, Event)
    def add_change(self, change: Change) -> Change: return self._add(change, ChangeRow, Change)
    def add_message(self, message: Message) -> Message: return self._add(message, MessageRow, Message)
    def add_update(self, update: ContextUpdate) -> ContextUpdate: return self._add(update, ContextUpdateRow, ContextUpdate)

    def list_updates(self, agent_id: UUID) -> list[ContextUpdate]:
        self.get_agent(agent_id)
        query = select(ContextUpdateRow).where(ContextUpdateRow.recipient_agent_id == agent_id).order_by(ContextUpdateRow.created_at.desc())
        return [self._entity(row, ContextUpdate) for row in self.session.scalars(query)]

    def seed(self, *entities: object) -> None:
        """Compatibility helper mirroring the in-memory demo adapter for setup/tests."""
        rows: list[tuple[type[Any], type[Any]]] = [
            (Project, ProjectRow), (Component, ComponentRow), (Relationship, RelationshipRow),
            (Task, TaskRow), (Agent, AgentRow), (Event, EventRow), (Decision, DecisionRow),
            (Memory, MemoryRow), (Change, ChangeRow), (Message, MessageRow), (ContextUpdate, ContextUpdateRow),
        ]
        for entity in entities:
            for model, row_type in rows:
                if isinstance(entity, model):
                    # ``seed`` is intentionally idempotent, matching the demo
                    # adapter's dictionary semantics when fixtures are replayed.
                    self.session.merge(row_type(**self._data(entity)))
                    break
            else:
                raise TypeError(f"Unsupported seed entity: {type(entity)!r}")
        self.session.flush()
