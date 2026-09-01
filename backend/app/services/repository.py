"""Persistence boundary and hackathon in-memory adapter."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Protocol, TypeVar
from uuid import UUID

from app.models import (
    Agent,
    Change,
    Component,
    ContextUpdate,
    Decision,
    Event,
    Memory,
    Message,
    Project,
    Relationship,
    Task,
)


class EntityNotFoundError(LookupError):
    def __init__(self, entity: str, entity_id: UUID):
        super().__init__(f"{entity} '{entity_id}' was not found")
        self.entity = entity
        self.entity_id = entity_id


class ProjectKnowledgeRepository(Protocol):
    def get_project(self, project_id: UUID) -> Project: ...
    def get_component(self, component_id: UUID) -> Component: ...
    def get_agent(self, agent_id: UUID) -> Agent: ...
    def get_event(self, event_id: UUID) -> Event: ...
    def list_components(self, project_id: UUID) -> list[Component]: ...
    def list_relationships(self, project_id: UUID) -> list[Relationship]: ...
    def list_tasks(self, project_id: UUID) -> list[Task]: ...
    def list_agents(self, project_id: UUID) -> list[Agent]: ...
    def list_events(self, project_id: UUID, limit: int | None = 25) -> list[Event]: ...
    def list_decisions(self, project_id: UUID) -> list[Decision]: ...
    def list_memories(self, project_id: UUID) -> list[Memory]: ...
    def list_changes(self, project_id: UUID, limit: int = 25) -> list[Change]: ...
    def add_event(self, event: Event) -> Event: ...
    def record_approval_decision(self, event: Event) -> Event | None: ...
    def add_change(self, change: Change) -> Change: ...
    def add_message(self, message: Message) -> Message: ...
    def add_update(self, update: ContextUpdate) -> ContextUpdate: ...
    def list_updates(self, agent_id: UUID) -> list[ContextUpdate]: ...


T = TypeVar("T")


class InMemoryProjectRepository:
    """Deterministic demo adapter; replace with the team's persistent adapter."""

    def __init__(self) -> None:
        self.projects: dict[UUID, Project] = {}
        self.components: dict[UUID, Component] = {}
        self.relationships: dict[UUID, Relationship] = {}
        self.tasks: dict[UUID, Task] = {}
        self.agents: dict[UUID, Agent] = {}
        self.events: dict[UUID, Event] = {}
        self.decisions: dict[UUID, Decision] = {}
        self.memories: dict[UUID, Memory] = {}
        self.changes: dict[UUID, Change] = {}
        self.messages: dict[UUID, Message] = {}
        self.updates: dict[UUID, ContextUpdate] = {}
        self.agent_update_ids: dict[UUID, list[UUID]] = defaultdict(list)
        self._approval_lock = Lock()

    @staticmethod
    def _require(store: dict[UUID, T], entity_id: UUID, entity: str) -> T:
        try:
            return store[entity_id]
        except KeyError as exc:
            raise EntityNotFoundError(entity, entity_id) from exc

    @staticmethod
    def _for_project(store: dict[UUID, T], project_id: UUID) -> list[T]:
        return [item for item in store.values() if getattr(item, "project_id") == project_id]

    def get_project(self, project_id: UUID) -> Project:
        return self._require(self.projects, project_id, "Project")

    def get_component(self, component_id: UUID) -> Component:
        return self._require(self.components, component_id, "Component")

    def get_agent(self, agent_id: UUID) -> Agent:
        return self._require(self.agents, agent_id, "Agent")

    def get_event(self, event_id: UUID) -> Event:
        return self._require(self.events, event_id, "Event")

    def list_components(self, project_id: UUID) -> list[Component]:
        return self._for_project(self.components, project_id)

    def list_relationships(self, project_id: UUID) -> list[Relationship]:
        return self._for_project(self.relationships, project_id)

    def list_tasks(self, project_id: UUID) -> list[Task]:
        return self._for_project(self.tasks, project_id)

    def list_agents(self, project_id: UUID) -> list[Agent]:
        return self._for_project(self.agents, project_id)

    def list_events(self, project_id: UUID, limit: int | None = 25) -> list[Event]:
        items = self._for_project(self.events, project_id)
        return sorted(items, key=lambda item: item.created_at, reverse=True)[:limit]

    def list_decisions(self, project_id: UUID) -> list[Decision]:
        return self._for_project(self.decisions, project_id)

    def list_memories(self, project_id: UUID) -> list[Memory]:
        return self._for_project(self.memories, project_id)

    def list_changes(self, project_id: UUID, limit: int = 25) -> list[Change]:
        items = self._for_project(self.changes, project_id)
        return sorted(items, key=lambda item: item.created_at, reverse=True)[:limit]

    def add_event(self, event: Event) -> Event:
        self.events[event.id] = event
        return event

    def record_approval_decision(self, event: Event) -> Event | None:
        approval_event_id = event.payload.get("approval_event_id")
        with self._approval_lock:
            duplicate = any(
                item.project_id == event.project_id
                and item.event_type == "collaboration_approval_decision"
                and item.payload.get("approval_event_id") == approval_event_id
                for item in self.events.values()
            )
            if duplicate:
                return None
            self.events[event.id] = event
            return event

    def add_change(self, change: Change) -> Change:
        self.changes[change.id] = change
        return change

    def add_message(self, message: Message) -> Message:
        self.messages[message.id] = message
        return message

    def add_update(self, update: ContextUpdate) -> ContextUpdate:
        self.updates[update.id] = update
        self.agent_update_ids[update.recipient_agent_id].append(update.id)
        return update

    def list_updates(self, agent_id: UUID) -> list[ContextUpdate]:
        self.get_agent(agent_id)
        items = [self.updates[item_id] for item_id in self.agent_update_ids[agent_id]]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def seed(self, *entities: object) -> None:
        stores = {
            Project: self.projects,
            Component: self.components,
            Relationship: self.relationships,
            Task: self.tasks,
            Agent: self.agents,
            Event: self.events,
            Decision: self.decisions,
            Memory: self.memories,
            Change: self.changes,
        }
        for entity in entities:
            for model, store in stores.items():
                if isinstance(entity, model):
                    store[entity.id] = entity
                    break
            else:
                raise TypeError(f"Unsupported seed entity: {type(entity)!r}")
