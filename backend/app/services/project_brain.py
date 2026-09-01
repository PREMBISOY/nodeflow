from __future__ import annotations

from uuid import UUID

from app.engines.dependency_graph import DependencyGraph
from app.schemas.intelligence import ComponentContext, ProjectContext
from app.services.repository import ProjectKnowledgeRepository


class ProjectBrain:
    """Structured retrieval facade over project knowledge."""

    def __init__(self, repository: ProjectKnowledgeRepository):
        self.repository = repository

    def get_project_context(self, project_id: UUID) -> ProjectContext:
        return ProjectContext(
            project=self.repository.get_project(project_id),
            components=self.repository.list_components(project_id),
            relationships=self.repository.list_relationships(project_id),
            tasks=self.repository.list_tasks(project_id),
            agents=self.repository.list_agents(project_id),
            recent_events=self.repository.list_events(project_id),
            decisions=self.repository.list_decisions(project_id),
            memories=self.repository.list_memories(project_id),
            recent_changes=self.repository.list_changes(project_id),
        )

    def get_component_context(self, project_id: UUID, component_id: UUID) -> ComponentContext:
        component = self.repository.get_component(component_id)
        if component.project_id != project_id:
            raise LookupError("Component does not belong to the requested project")
        relationships = self.repository.list_relationships(project_id)
        related_ids = set(DependencyGraph(relationships).related(component_id, max_depth=1))
        related_relationships = [
            item
            for item in relationships
            if component_id in (item.source_component_id, item.target_component_id)
        ]
        return ComponentContext(
            component=component,
            relationships=related_relationships,
            related_components=[
                item for item in self.repository.list_components(project_id) if item.id in related_ids
            ],
            tasks=[
                item for item in self.repository.list_tasks(project_id) if component_id in item.component_ids
            ],
            agents=[
                item for item in self.repository.list_agents(project_id) if component_id in item.component_ids
            ],
            decisions=self.get_relevant_decisions(project_id, [component_id, *related_ids]),
            memories=[
                item
                for item in self.repository.list_memories(project_id)
                if set(item.component_ids).intersection({component_id, *related_ids})
            ],
            recent_events=[
                item
                for item in self.repository.list_events(project_id)
                if set(item.component_ids).intersection({component_id, *related_ids})
            ],
        )

    def get_related_context(self, project_id: UUID, entity_id: UUID) -> ComponentContext:
        return self.get_component_context(project_id, entity_id)

    def get_recent_changes(self, project_id: UUID):
        self.repository.get_project(project_id)
        return self.repository.list_changes(project_id)

    def get_relevant_decisions(self, project_id: UUID, component_ids: list[UUID]):
        target_ids = set(component_ids)
        return [
            item
            for item in self.repository.list_decisions(project_id)
            if not item.component_ids or target_ids.intersection(item.component_ids)
        ]

    def get_relevant_memory(self, project_id: UUID, query: str):
        tokens = {token.lower() for token in query.split() if len(token) > 2}
        memories = self.repository.list_memories(project_id)
        if not tokens:
            return memories
        return [
            item
            for item in memories
            if tokens.intersection({token.strip(".,:;!?()").lower() for token in item.content.split()})
            or tokens.intersection({tag.lower() for tag in item.tags})
        ]

    def get_project_state(self, project_id: UUID) -> dict:
        context = self.get_project_context(project_id)
        return {
            "project_id": project_id,
            "status": context.project.status,
            "component_count": len(context.components),
            "active_agent_count": sum(agent.active for agent in context.agents),
            "tasks_by_status": {
                status: sum(task.status == status for task in context.tasks)
                for status in sorted({task.status for task in context.tasks})
            },
            "recent_event_count": len(context.recent_events),
            "recent_change_count": len(context.recent_changes),
        }
