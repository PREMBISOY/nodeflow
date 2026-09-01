from __future__ import annotations

from uuid import UUID

from app.engines.dependency_graph import DependencyGraph
from app.schemas.intelligence import ContextScope
from app.services.project_brain import ProjectBrain
from app.services.repository import EntityNotFoundError, ProjectKnowledgeRepository


class ContextService:
    def __init__(self, repository: ProjectKnowledgeRepository, brain: ProjectBrain):
        self.repository = repository
        self.brain = brain

    def get_agent_context(
        self,
        agent_id: UUID,
        scope: ContextScope = "related",
        task_id: UUID | None = None,
    ) -> dict:
        agent = self.repository.get_agent(agent_id)
        project_id = agent.project_id
        all_tasks = self.repository.list_tasks(project_id)
        all_agents = self.repository.list_agents(project_id)
        own_tasks = [
            task
            for task in all_tasks
            if task.id in set(agent.current_task_ids) or agent.id in task.assignee_agent_ids
        ]
        own_task_ids = {task.id for task in own_tasks}
        own_component_ids = set(agent.component_ids) | {
            component_id for task in own_tasks for component_id in task.component_ids
        }
        requested_task = None
        if task_id is not None:
            requested_task = next((task for task in all_tasks if task.id == task_id), None)
            if requested_task is None:
                raise EntityNotFoundError("Task", task_id)
            own_task_ids.add(requested_task.id)
            own_component_ids.update(requested_task.component_ids)

        if scope == "project":
            component_ids = {item.id for item in self.repository.list_components(project_id)}
            tasks = all_tasks
        elif scope == "team":
            peers = [item for item in all_agents if item.active]
            component_ids = {component_id for peer in peers for component_id in peer.component_ids}
            peer_ids = {peer.id for peer in peers}
            tasks = [
                task for task in all_tasks
                if set(task.assignee_agent_ids).intersection(peer_ids)
            ]
            component_ids.update(
                component_id for task in tasks for component_id in task.component_ids
            )
        elif scope == "my_work":
            component_ids = own_component_ids
            tasks = own_tasks
        else:
            graph = DependencyGraph(self.repository.list_relationships(project_id))
            component_ids = own_component_ids.copy()
            graph_origins = set(agent.component_ids) or own_component_ids
            for component_id in graph_origins:
                component_ids.update(graph.related(component_id, max_depth=1))
            tasks = [task for task in all_tasks if component_ids.intersection(task.component_ids)]

        if requested_task is not None and requested_task not in tasks:
            tasks = [requested_task, *tasks]

        components = [
            item for item in self.repository.list_components(project_id) if item.id in component_ids
        ]
        relationships = [
            relationship
            for relationship in self.repository.list_relationships(project_id)
            if relationship.source_component_id in component_ids
            and relationship.target_component_id in component_ids
        ]
        decisions = self.brain.get_relevant_decisions(project_id, list(component_ids))
        memories = [
            item
            for item in self.repository.list_memories(project_id)
            if not item.component_ids or component_ids.intersection(item.component_ids)
        ]
        events = [
            item
            for item in self.repository.list_events(project_id)
            if not item.component_ids or component_ids.intersection(item.component_ids)
        ]
        return {
            "agent": agent,
            "scope": scope,
            "project": self.repository.get_project(project_id),
            "components": components,
            "relationships": relationships,
            "tasks": tasks,
            "requested_task": requested_task,
            "decisions": decisions,
            "memories": memories,
            "recent_events": events,
        }
