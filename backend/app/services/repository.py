"""Persistence boundary; engines use this service rather than raw SQLAlchemy sessions."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import AgentRow, ChangeRow, ComponentRow, ContextUpdateRow, DecisionRow, EventRow, MemoryRow, MessageRow, ProjectRow, RelationshipRow, RoleRow, TaskRow, UserRow
from app.models import Agent, Change, Component, ContextUpdate, Decision, Event, Memory, Message, Project, Relationship, Role, Task, User

T = TypeVar("T")
class EntityNotFoundError(LookupError):
    def __init__(self, entity: str, entity_id: UUID): super().__init__(f"{entity} '{entity_id}' was not found")

class PermissionDeniedError(PermissionError): pass

class InMemoryProjectRepository:
    """Deterministic adapter for demos/tests; same public shape as the SQL adapter."""
    def __init__(self): self._stores = defaultdict(dict)
    def add(self, entity: T) -> T: self._stores[type(entity)][entity.id] = entity; return entity
    def get(self, kind: type[T], entity_id: UUID) -> T:
        try: return self._stores[kind][entity_id]
        except KeyError: raise EntityNotFoundError(kind.__name__, entity_id)
    def list(self, kind: type[T], project_id: UUID) -> list[T]: return [x for x in self._stores[kind].values() if x.project_id == project_id]
    def get_project(self, id): return self.get(Project, id)
    def get_agent(self, id): return self.get(Agent, id)
    def list_projects(self): return list(self._stores[Project].values())
    def list_agents(self, p): return self.list(Agent, p)
    def list_tasks(self, p): return self.list(Task, p)
    def list_events(self, p, limit=100, before: datetime | None=None): return sorted([e for e in self.list(Event,p) if not before or e.timestamp <= before], key=lambda x:x.timestamp, reverse=True)[:limit]
    def list_decisions(self,p): return self.list(Decision,p)
    def list_memories(self,p): return self.list(Memory,p)
    def list_components(self,p): return self.list(Component,p)
    def list_relationships(self,p): return self.list(Relationship,p)
    def list_changes(self,p): return self.list(Change,p)
    def list_messages(self, p, agent_id=None):
        values=self.list(Message,p); return [m for m in values if agent_id is None or agent_id in (m.sender_agent_id,m.recipient_agent_id)]
    def list_updates(self, agent_id):
        return sorted([x for x in self._stores[ContextUpdate].values() if x.recipient_agent_id==agent_id], key=lambda x:x.created_at, reverse=True)
    def update_task(self, task_id, **changes):
        task=self.get(Task,task_id).model_copy(update=changes); self._stores[Task][task_id]=task; return task
    create_project=add; create_user=add; create_role=add; create_agent=add; create_task=add; create_event=add; create_decision=add; create_memory=add; create_component=add; create_relationship=add; create_message=add; create_context_update=add; create_change=add

class SqlAlchemyProjectRepository:
    def __init__(self, session: Session): self.session = session
    @staticmethod
    def _model(row, schema):
        data = {col.name: getattr(row, col.name) for col in row.__table__.columns if col.name != "metadata"}
        if hasattr(row, "metadata_"): data["metadata"] = row.metadata_
        return schema.model_validate(data)
    def _create(self, entity, row_type, schema, metadata=False):
        data = entity.model_dump()
        # UUIDs are valid domain values, but Python's default JSON encoder cannot
        # serialize them when they appear in JSONB list fields. Keep native UUIDs
        # for FK/primary-key columns and use Pydantic's JSON mode only for JSONB.
        json_data = entity.model_dump(mode="json")
        for key in ("permissions", "capabilities", "affected_components", "related_components", "related_agents"):
            if key in data:
                data[key] = json_data[key]
        if metadata: data["metadata_"] = data.pop("metadata")
        row = row_type(**data); self.session.add(row); self.session.commit(); self.session.refresh(row); return self._model(row, schema)
    def _get(self, row_type, schema, id):
        row = self.session.get(row_type, id)
        if not row: raise EntityNotFoundError(schema.__name__, id)
        return self._model(row, schema)
    def _list(self, row_type, schema, project_id, order=None, limit=None):
        q = select(row_type).where(row_type.project_id == project_id)
        if order is not None: q = q.order_by(order.desc())
        if limit: q = q.limit(limit)
        return [self._model(x, schema) for x in self.session.scalars(q)]
    def create_project(self,x): return self._create(x,ProjectRow,Project)
    def create_user(self,x): return self._create(x,UserRow,User)
    def create_role(self,x): return self._create(x,RoleRow,Role)
    def create_agent(self,x): return self._create(x,AgentRow,Agent)
    def create_component(self,x): return self._create(x,ComponentRow,Component,True)
    def create_relationship(self,x): return self._create(x,RelationshipRow,Relationship,True)
    def create_task(self,x): return self._create(x,TaskRow,Task)
    def create_event(self,x): return self._create(x,EventRow,Event,True)
    def create_memory(self,x): return self._create(x,MemoryRow,Memory,True)
    def create_decision(self,x): return self._create(x,DecisionRow,Decision)
    def create_change(self,x): return self._create(x,ChangeRow,Change)
    def create_message(self,x): return self._create(x,MessageRow,Message)
    def create_context_update(self,x): return self._create(x,ContextUpdateRow,ContextUpdate)
    def get_project(self,id): return self._get(ProjectRow,Project,id)
    def get_agent(self,id): return self._get(AgentRow,Agent,id)
    def list_projects(self): return [self._model(x,Project) for x in self.session.scalars(select(ProjectRow))]
    def list_agents(self,p): return self._list(AgentRow,Agent,p)
    def list_tasks(self,p): return self._list(TaskRow,Task,p,TaskRow.updated_at)
    def list_events(self,p,limit=100,before=None):
        q=select(EventRow).where(EventRow.project_id==p)
        if before: q=q.where(EventRow.timestamp<=before)
        return [self._model(x,Event) for x in self.session.scalars(q.order_by(EventRow.timestamp.desc()).limit(limit))]
    def list_decisions(self,p): return self._list(DecisionRow,Decision,p)
    def list_memories(self,p): return self._list(MemoryRow,Memory,p)
    def list_components(self,p): return self._list(ComponentRow,Component,p)
    def list_relationships(self,p): return self._list(RelationshipRow,Relationship,p)
    def list_changes(self,p): return self._list(ChangeRow,Change,p)
    def list_messages(self,p,agent_id=None):
        q=select(MessageRow).where(MessageRow.project_id==p)
        if agent_id: q=q.where((MessageRow.sender_agent_id==agent_id) | (MessageRow.recipient_agent_id==agent_id))
        return [self._model(x,Message) for x in self.session.scalars(q.order_by(MessageRow.created_at.desc()))]
    def list_updates(self,agent_id):
        q=select(ContextUpdateRow).where(ContextUpdateRow.recipient_agent_id==agent_id).order_by(ContextUpdateRow.created_at.desc())
        return [self._model(x,ContextUpdate) for x in self.session.scalars(q)]
    def update_task(self,task_id,**changes):
        row=self.session.get(TaskRow,task_id)
        if not row: raise EntityNotFoundError("Task",task_id)
        for key,value in changes.items():
            if key=="affected_components": value=[str(x) for x in value]
            setattr(row,key,value)
        self.session.commit(); self.session.refresh(row); return self._model(row,Task)

class AccessControlService:
    """Small permission gate deliberately separate from context relevance."""
    def can_read(self, user: User | None, resource: str) -> bool:
        if user is None: return False
        return "admin" in user.permissions or resource in user.permissions or "project:read" in user.permissions

class ContextQueryService:
    def __init__(self, repository): self.repository = repository
    def for_agent(self, agent: Agent, scope: str):
        project_id=agent.project_id; tasks=self.repository.list_tasks(project_id); components=set()
        if scope == "my_work": tasks=[x for x in tasks if x.agent_id==agent.id]; components={c for x in tasks for c in x.affected_components}
        elif scope == "team":
            peer_ids={x.id for x in self.repository.list_agents(project_id) if x.role==agent.role}; tasks=[x for x in tasks if x.agent_id in peer_ids]; components={c for x in tasks for c in x.affected_components}
        elif scope == "related":
            own={c for x in tasks if x.agent_id==agent.id for c in x.affected_components}; rel=self.repository.list_relationships(project_id); components=own | {r.target_entity_id for r in rel if r.source_entity_id in own} | {r.source_entity_id for r in rel if r.target_entity_id in own}; tasks=[x for x in tasks if components.intersection(x.affected_components)]
        else: components={x.id for x in self.repository.list_components(project_id)}
        memories=[x for x in self.repository.list_memories(project_id) if not x.related_components or components.intersection(x.related_components)]
        decisions=[x for x in self.repository.list_decisions(project_id) if not x.affected_components or components.intersection(x.affected_components)]
        events=[x for x in self.repository.list_events(project_id) if not x.affected_components or components.intersection(x.affected_components)]
        return {"agent":agent,"scope":scope,"tasks":tasks,"memories":memories,"decisions":decisions,"events":events}

class CollaborationService:
    """Persists messages and material event notifications for delivery by Sunal's gateway."""
    def __init__(self, repository): self.repository=repository
    def record_event(self, event: Event) -> Event:
        saved=self.repository.create_event(event)
        affected=set(saved.affected_components)
        if affected:
            for agent in self.repository.list_agents(saved.project_id):
                agent_tasks=[t for t in self.repository.list_tasks(saved.project_id) if t.agent_id==agent.id]
                owns={c for task in agent_tasks for c in task.affected_components}
                if owns.intersection(affected) and agent.id != saved.actor_id:
                    self.repository.create_context_update(ContextUpdate(project_id=saved.project_id,recipient_agent_id=agent.id,source_event_id=saved.id,subject=saved.event_type,content=saved.description,related_components=list(affected),relevance_score=0.8))
        return saved
    def send_message(self, message: Message) -> Message:
        sender=self.repository.get_agent(message.sender_agent_id); recipient=self.repository.get_agent(message.recipient_agent_id)
        if sender.project_id != recipient.project_id or sender.project_id != message.project_id: raise ValueError("Agents and message must belong to one project")
        saved=self.repository.create_message(message)
        self.record_event(Event(project_id=message.project_id,actor_type="agent",actor_id=message.sender_agent_id,event_type="AGENT_MESSAGE",description=message.subject,affected_components=message.related_components,metadata={"message_id":str(saved.id),"recipient_agent_id":str(message.recipient_agent_id)}))
        return saved

class StateReplayService:
    """Small, explicit event replay for time travel; not a full event-sourcing framework."""
    def __init__(self, repository): self.repository=repository
    def at(self, project_id, timestamp: datetime):
        events=list(reversed(self.repository.list_events(project_id,limit=10_000,before=timestamp)))
        task_counts=defaultdict(int); agents=set(); components=set()
        for event in events:
            components.update(event.affected_components)
            if event.actor_id: agents.add(event.actor_id)
            status=event.metadata.get("task_status")
            if status: task_counts[status] += 1
        return {"project_id":project_id,"as_of":timestamp,"events_replayed":len(events),"observed_components":len(components),"active_actors":len(agents),"task_status_transitions":dict(task_counts)}
