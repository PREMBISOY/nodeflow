"""Product-facing collaboration state composed from Project Brain records."""

from __future__ import annotations

from uuid import UUID

from app.services.project_brain import ProjectBrain
from app.services.repository import ProjectKnowledgeRepository


class CollaborationService:
    def __init__(self, repository: ProjectKnowledgeRepository, brain: ProjectBrain):
        self.repository = repository
        self.brain = brain

    def get_state(self, project_id: UUID) -> dict:
        context = self.brain.get_project_context(project_id)
        agents = {agent.id: agent for agent in context.agents}
        updates = [update for agent in context.agents for update in self.repository.list_updates(agent.id)]
        waiting = [
            {"kind": "task", "id": str(task.id), "title": task.title, "status": task.status}
            for task in context.tasks if task.status in {"todo", "blocked", "waiting_approval"}
        ]
        waiting.extend(
            {"kind": "approval", "id": str(event.id), "title": event.summary,
             "status": "waiting_approval"}
            for event in context.recent_events if event.payload.get("requires_approval")
        )
        return {
            "project": context.project,
            "summary": self.brain.get_project_state(project_id),
            "timeline": [self._timeline_item(event, agents) for event in context.recent_events],
            "agents": [
                {"id": agent.id, "name": agent.name, "role": agent.role, "active": agent.active,
                 "current_task_ids": agent.current_task_ids}
                for agent in context.agents
            ],
            "notifications": {"total": len(updates), "unread": sum(not update.read for update in updates)},
            "waiting": waiting,
        }

    @staticmethod
    def _timeline_item(event, agents):
        actor = agents.get(event.actor_id)
        return {
            "id": event.id, "event_type": event.event_type, "summary": event.summary,
            "created_at": event.created_at, "actor_type": event.actor_type,
            "actor_name": actor.name if actor else event.payload.get("actor_name"),
            "component_ids": event.component_ids,
            "requires_approval": bool(event.payload.get("requires_approval")),
        }
