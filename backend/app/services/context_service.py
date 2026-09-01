from __future__ import annotations

from uuid import UUID

from app.engines.dependency_graph import DependencyGraph
from app.schemas.intelligence import ContextScope
from app.services.project_brain import ProjectBrain
from app.services.repository import ProjectKnowledgeRepository


class ContextService:
    def __init__(self, repository: ProjectKnowledgeRepository, brain: ProjectBrain):
        self.repository = repository
        self.brain = brain

    def get_agent_context(self, agent_id: UUID, scope: ContextScope = "related") -> dict:
        agent = self.repository.get_agent(agent_id)
        project_id = agent.project_id
        all_tasks = self.repository.list_tasks(project_id)
        own_task_ids = set(agent.current_task_ids)
        own_component_ids = set(agent.component_ids)

        if scope == "project":
            component_ids = {item.id for item in self.repository.list_components(project_id)}
            tasks = all_tasks
        elif scope == "team":
            peer_roles = {agent.role}
            peers = [item for item in self.repository.list_agents(project_id) if item.role in peer_roles]
            component_ids = {component_id for peer in peers for component_id in peer.component_ids}
            tasks = [task for task in all_tasks if set(task.assignee_agent_ids).intersection({p.id for p in peers})]
        elif scope == "my_work":
            component_ids = own_component_ids
            tasks = [task for task in all_tasks if task.id in own_task_ids or agent.id in task.assignee_agent_ids]
        else:
            graph = DependencyGraph(self.repository.list_relationships(project_id))
            component_ids = own_component_ids.copy()
            for component_id in own_component_ids:
                component_ids.update(graph.related(component_id, max_depth=1))
            tasks = [task for task in all_tasks if component_ids.intersection(task.component_ids)]

        components = [
            item for item in self.repository.list_components(project_id) if item.id in component_ids
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
            "tasks": tasks,
            "decisions": decisions,
            "memories": memories,
            "recent_events": events,
        }
