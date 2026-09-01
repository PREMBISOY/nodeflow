"""Product-facing collaboration state composed from Project Brain records."""

from __future__ import annotations

from uuid import UUID

from app.models import Event
from app.schemas.intelligence import ApprovalDecisionCreate
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
        approval_statuses = self._approval_statuses(context.recent_events)
        approvals = [
            {"id": event.id, "title": event.summary, "status": approval_statuses.get(event.id, "waiting_approval"),
             "component_ids": event.component_ids}
            for event in context.recent_events if event.payload.get("requires_approval")
        ]
        waiting.extend(
            {"kind": "approval", "id": str(item["id"]), "title": item["title"], "status": item["status"]}
            for item in approvals if item["status"] == "waiting_approval"
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
            "approvals": approvals,
            "waiting": waiting,
        }

    def decide_approval(self, approval_event_id: UUID, request: ApprovalDecisionCreate) -> Event:
        source = next((event for event in self.repository.list_events(request.project_id, limit=250)
                       if event.id == approval_event_id), None)
        if source is None or not source.payload.get("requires_approval"):
            raise LookupError("Approval request was not found")
        status = self._approval_statuses(self.repository.list_events(request.project_id, limit=250)).get(source.id)
        if status:
            raise ValueError(f"Approval request has already been {status}")
        decision = Event(
            project_id=request.project_id,
            event_type="collaboration_approval_decision",
            actor_type="human",
            entity_id=source.id,
            component_ids=source.component_ids,
            summary=f"{request.decision.title()}: {source.summary}",
            payload={"approval_event_id": str(source.id), "approval_status": request.decision,
                     "actor_name": request.actor_name, "comment": request.comment},
        )
        return self.repository.add_event(decision)

    @staticmethod
    def _approval_statuses(events):
        statuses = {}
        for event in sorted(events, key=lambda item: item.created_at):
            if event.event_type != "collaboration_approval_decision":
                continue
            reference = event.payload.get("approval_event_id")
            if reference:
                statuses[UUID(reference)] = event.payload.get("approval_status")
        return statuses

    @staticmethod
    def _timeline_item(event, agents):
        actor = agents.get(event.actor_id)
        return {
            "id": event.id, "event_type": event.event_type, "summary": event.summary,
            "created_at": event.created_at, "actor_type": event.actor_type,
            "actor_name": actor.name if actor else event.payload.get("actor_name"),
            "component_ids": event.component_ids,
            "requires_approval": bool(event.payload.get("requires_approval")),
            "approval_event_id": event.payload.get("approval_event_id"),
            "approval_status": event.payload.get("approval_status"),
        }
