from __future__ import annotations

from app.engines.dependency_graph import DependencyGraph
from app.models import Change
from app.schemas.intelligence import ImpactAnalysisResult
from app.services.repository import ProjectKnowledgeRepository


class ChangeImpactAnalyzer:
    def __init__(self, repository: ProjectKnowledgeRepository):
        self.repository = repository

    def analyze(self, change: Change) -> ImpactAnalysisResult:
        project_id = change.project_id
        changed_component = self.repository.get_component(change.component_id)
        if changed_component.project_id != project_id:
            raise ValueError("Changed component does not belong to the event project")
        components = {item.id: item for item in self.repository.list_components(project_id)}
        relationships = self.repository.list_relationships(project_id)
        distances = DependencyGraph(relationships).related(change.component_id, max_depth=2)
        affected_ids = set(distances)
        affected_components = sorted(
            (components[item_id] for item_id in affected_ids if item_id in components),
            key=lambda item: (distances[item.id], item.name.casefold(), str(item.id)),
        )
        relevant_component_ids = affected_ids | {change.component_id}

        inactive_statuses = {"done", "completed", "cancelled", "canceled", "archived"}
        affected_tasks = sorted([
            task
            for task in self.repository.list_tasks(project_id)
            if relevant_component_ids.intersection(task.component_ids)
            and task.status.casefold() not in inactive_statuses
        ], key=lambda item: (item.title.casefold(), str(item.id)))
        task_ids = {task.id for task in affected_tasks}
        affected_agents = sorted([
            agent
            for agent in self.repository.list_agents(project_id)
            if agent.active
            and (
                relevant_component_ids.intersection(agent.component_ids)
                or task_ids.intersection(agent.current_task_ids)
                or any(agent.id in task.assignee_agent_ids for task in affected_tasks)
            )
        ], key=lambda item: (item.name.casefold(), str(item.id)))

        reasoning = [f"Change originated in component '{changed_component.name}'."]
        for component in sorted(affected_components, key=lambda item: (distances[item.id], item.name)):
            reasoning.append(
                f"'{component.name}' is connected at dependency distance {distances[component.id]}."
            )
        if affected_tasks:
            reasoning.append(f"{len(affected_tasks)} active task(s) touch the impacted component set.")
        if affected_agents:
            reasoning.append(f"{len(affected_agents)} active agent(s) own impacted work or components.")

        affected_count = len(affected_components)
        impact_level = "high" if affected_count >= 3 else "medium" if affected_count else "low"
        return ImpactAnalysisResult(
            change=change,
            affected_components=affected_components,
            affected_component_distances=distances,
            affected_agents=affected_agents,
            affected_tasks=affected_tasks,
            relevant_roles=sorted({agent.role for agent in affected_agents}),
            impact_level=impact_level,
            reasoning=reasoning,
        )
