"""SQLAlchemy schema. PostgreSQL is the production target; SQLite supports local tests."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import JSON

JSONType = JSON().with_variant(JSONB, "postgresql")
def now(): return datetime.now(timezone.utc)
class Base(DeclarativeBase): pass
class IdMixin:
    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)

class ProjectRow(IdMixin, Base):
    __tablename__ = "projects"; name: Mapped[str] = mapped_column(String(200)); description: Mapped[str] = mapped_column(Text, default=""); repository_url: Mapped[str | None] = mapped_column(Text); status: Mapped[str] = mapped_column(String(40), default="active"); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
class UserRow(IdMixin, Base):
    __tablename__ = "users"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); name: Mapped[str] = mapped_column(String(200)); role: Mapped[str] = mapped_column(String(100)); permissions: Mapped[list] = mapped_column(JSONType, default=list); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class RoleRow(IdMixin, Base):
    __tablename__ = "roles"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); name: Mapped[str] = mapped_column(String(100)); permissions: Mapped[list] = mapped_column(JSONType, default=list); description: Mapped[str] = mapped_column(Text, default="")
class AgentRow(IdMixin, Base):
    __tablename__ = "agents"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); owner_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id")); name: Mapped[str] = mapped_column(String(200)); provider: Mapped[str] = mapped_column(String(100)); model: Mapped[str | None] = mapped_column(String(200)); role: Mapped[str] = mapped_column(String(100)); capabilities: Mapped[list] = mapped_column(JSONType, default=list); status: Mapped[str] = mapped_column(String(40), default="ACTIVE"); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class ComponentRow(IdMixin, Base):
    __tablename__ = "components"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); name: Mapped[str] = mapped_column(String(200)); type: Mapped[str] = mapped_column(String(80)); description: Mapped[str] = mapped_column(Text, default=""); metadata_: Mapped[dict] = mapped_column("metadata", JSONType, default=dict)
class RelationshipRow(IdMixin, Base):
    __tablename__ = "relationships"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); source_entity_id: Mapped[object] = mapped_column(UUID(as_uuid=True), index=True); target_entity_id: Mapped[object] = mapped_column(UUID(as_uuid=True), index=True); relationship_type: Mapped[str] = mapped_column(String(80)); metadata_: Mapped[dict] = mapped_column("metadata", JSONType, default=dict)
class TaskRow(IdMixin, Base):
    __tablename__ = "tasks"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); title: Mapped[str] = mapped_column(String(300)); description: Mapped[str] = mapped_column(Text, default=""); owner_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id")); agent_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), index=True); status: Mapped[str] = mapped_column(String(40)); priority: Mapped[str] = mapped_column(String(40)); affected_components: Mapped[list] = mapped_column(JSONType, default=list); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
class EventRow(IdMixin, Base):
    __tablename__ = "events"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); actor_type: Mapped[str] = mapped_column(String(40)); actor_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), index=True); event_type: Mapped[str] = mapped_column(String(100), index=True); description: Mapped[str] = mapped_column(Text); affected_components: Mapped[list] = mapped_column(JSONType, default=list); metadata_: Mapped[dict] = mapped_column("metadata", JSONType, default=dict); timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
class MemoryRow(IdMixin, Base):
    __tablename__ = "memories"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); type: Mapped[str] = mapped_column(String(80)); content: Mapped[str] = mapped_column(Text); source: Mapped[str | None] = mapped_column(Text); related_components: Mapped[list] = mapped_column(JSONType, default=list); related_agents: Mapped[list] = mapped_column(JSONType, default=list); metadata_: Mapped[dict] = mapped_column("metadata", JSONType, default=dict); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class DecisionRow(IdMixin, Base):
    __tablename__ = "decisions"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); title: Mapped[str] = mapped_column(String(300)); decision: Mapped[str] = mapped_column(Text); rationale: Mapped[str] = mapped_column(Text); created_by: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id")); affected_components: Mapped[list] = mapped_column(JSONType, default=list); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class ChangeRow(IdMixin, Base):
    __tablename__ = "changes"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); component_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), ForeignKey("components.id")); summary: Mapped[str] = mapped_column(Text); change_type: Mapped[str] = mapped_column(String(60)); source_ref: Mapped[str | None] = mapped_column(Text); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class MessageRow(IdMixin, Base):
    __tablename__ = "messages"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); sender_agent_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), index=True); recipient_agent_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), index=True); message_type: Mapped[str] = mapped_column(String(80)); subject: Mapped[str] = mapped_column(String(300)); content: Mapped[str] = mapped_column(Text); related_components: Mapped[list] = mapped_column(JSONType, default=list); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class ContextUpdateRow(IdMixin, Base):
    __tablename__ = "context_updates"; project_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True); recipient_agent_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), index=True); source_event_id: Mapped[object] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id")); subject: Mapped[str] = mapped_column(String(300)); content: Mapped[str] = mapped_column(Text); related_components: Mapped[list] = mapped_column(JSONType, default=list); relevance_score: Mapped[float]; created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); read: Mapped[bool] = mapped_column(default=False)

def session_factory(database_url: str | None = None):
    url = database_url or os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/nodeflow")
    engine = create_engine(url, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)
