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
            "action": request.action,
            "requires_approval": self._requires_approval(request),
            "flow_stage": self._flow_stage(request),
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
            changes=[
                {
                    "component_id": component_id,
                    "summary": request.summary,
                    "change_type": request.event_type,
                    "source_ref": request.commit_sha or request.ref,
                }
                for component_id in component_ids
            ],
        ))

    @staticmethod
    def _map_files(components, changed_files: list[str]):
        matched = []
        for path in changed_files:
            normalized_path = path.strip("/")
            for component in components:
                prefixes = [
                    tag.removeprefix("path:").strip("/")
                    for tag in component.tags
                    if tag.startswith("path:")
                ]
                if component.id not in matched and any(
                    normalized_path == prefix or normalized_path.startswith(f"{prefix}/")
                    for prefix in prefixes
                ):
                    matched.append(component.id)
        return matched

    def _resolve_actor(self, project_id, actor_name: str | None, component_ids):
        agents = self.repository.list_agents(project_id)
        if actor_name:
            normalized = actor_name.strip().casefold()
            match = next(
                (
                    agent
                    for agent in agents
                    if normalized in self._agent_name_aliases(agent.name)
                ),
                None,
            )
            if match:
                return match.id
        return next(
            (agent.id for agent in agents if set(agent.component_ids).intersection(component_ids)),
            None,
        )

    @staticmethod
    def _agent_name_aliases(name: str) -> set[str]:
        normalized = name.strip().casefold()
        aliases = {normalized}
        for suffix in ("'s agent", "’s agent", " agent"):
            if normalized.endswith(suffix):
                aliases.add(normalized.removesuffix(suffix).strip())
        return aliases

    def get_activity(self, project_id):
        self.repository.get_project(project_id)
        return [
            {"id": event.id, "event_type": event.event_type, "summary": event.summary,
             "created_at": event.created_at, "component_ids": event.component_ids,
             "repository": event.payload.get("repository"), "ref": event.payload.get("ref"),
             "commit_sha": event.payload.get("commit_sha"), "pull_request_number": event.payload.get("pull_request_number"),
             "action": event.payload.get("action"), "flow_stage": event.payload.get("flow_stage"),
             "requires_approval": bool(event.payload.get("requires_approval"))}
            for event in self.repository.list_events(project_id, limit=100)
            if event.payload.get("provider") == "github"
        ]

    @staticmethod
    def _requires_approval(request: GitHubEventCreate) -> bool:
        if request.requires_approval is not None:
            return request.requires_approval
        return request.event_type == "pull_request" and request.action in {"opened", "synchronized"}

    @staticmethod
    def _flow_stage(request: GitHubEventCreate) -> str:
        if request.event_type == "pull_request" and request.action == "merged":
            return "merged"
        if request.event_type == "pull_request" and request.action in {"opened", "synchronized"}:
            return "review_required"
        if request.event_type == "commit":
            return "change_detected"
        return "branch_updated"
