"""Thin GitHub ingestion adapter; Git remains the source of truth for code."""

from __future__ import annotations

from app.schemas.intelligence import EventCreate, GitHubEventCreate
from app.services.event_processor import EventProcessor
from app.services.repository import ProjectKnowledgeRepository


class GitIntelligenceService:
    def __init__(self, repository: ProjectKnowledgeRepository, events: EventProcessor):
        self.repository = repository
        self.events = events

    def ingest(self, request: GitHubEventCreate):
        component_ids = self._map_files(
            self.repository.list_components(request.project_id), request.changed_files
        )
        actor_id = self._resolve_actor(request.project_id, request.actor_name, component_ids)
        payload = {
            "provider": "github", "repository": request.repository, "ref": request.ref,
            "commit_sha": request.commit_sha, "pull_request_number": request.pull_request_number,
            "actor_name": request.actor_name, "changed_files": request.changed_files,
            "requires_approval": request.requires_approval,
        }
        if not component_ids:
            return self.events.process(EventCreate(
                project_id=request.project_id, event_type=f"github_{request.event_type}",
                actor_type="agent" if actor_id else "system", actor_id=actor_id,
                summary=request.summary, payload=payload,
            ))
        return self.events.process(EventCreate(
            project_id=request.project_id, event_type=f"github_{request.event_type}",
            actor_type="agent" if actor_id else "system", actor_id=actor_id,
            component_ids=component_ids, summary=request.summary, payload=payload,
            change={"component_id": component_ids[0], "summary": request.summary,
                    "change_type": request.event_type, "source_ref": request.commit_sha or request.ref},
        ))

    @staticmethod
    def _map_files(components, changed_files: list[str]):
        matched = []
        for component in components:
            prefixes = [tag.removeprefix("path:").strip("/") for tag in component.tags
                        if tag.startswith("path:")]
            if any(path == prefix or path.startswith(f"{prefix}/")
                   for prefix in prefixes for path in changed_files):
                matched.append(component.id)
        return matched

    def _resolve_actor(self, project_id, actor_name: str | None, component_ids):
        agents = self.repository.list_agents(project_id)
        if actor_name:
            normalized = actor_name.casefold()
            match = next((agent for agent in agents if normalized in agent.name.casefold()), None)
            if match:
                return match.id
        return next(
            (agent.id for agent in agents if set(agent.component_ids).intersection(component_ids)),
            None,
        )
