from __future__ import annotations

from app.engines.dependency_graph import DependencyGraph
from app.schemas.intelligence import OnboardingPackage, OnboardingRequest
from app.services.project_brain import ProjectBrain
from app.services.repository import ProjectKnowledgeRepository


class OnboardingService:
    def __init__(self, repository: ProjectKnowledgeRepository, brain: ProjectBrain):
        self.repository = repository
        self.brain = brain

    def build(self, request: OnboardingRequest) -> OnboardingPackage:
        context = self.brain.get_project_context(request.project_id)
        generic_role_terms = {"engineer", "developer", "agent", "member", "lead"}
        role_terms = {
            token.lower() for token in request.role.split() if token.lower() not in generic_role_terms
        }
        if not role_terms:
            role_terms = {token.lower() for token in request.role.split()}
        agent = self.repository.get_agent(request.agent_id) if request.agent_id else None
        if agent and agent.project_id != request.project_id:
            raise ValueError("Onboarding agent does not belong to the requested project")
        relevant_component_ids = set(agent.component_ids) if agent else {
            component.id
            for component in context.components
            if role_terms.intersection({token.lower() for token in component.tags})
            or (component.owner_role and any(term in component.owner_role.lower() for term in role_terms))
        }
        if not relevant_component_ids:
            relevant_component_ids = {component.id for component in context.components}
        elif request.scope == "related":
            graph = DependencyGraph(context.relationships)
            for component_id in list(relevant_component_ids):
                relevant_component_ids.update(graph.related(component_id, max_depth=1))
        elif request.scope == "project":
            relevant_component_ids = {component.id for component in context.components}

        relevant_tasks = [
            task
            for task in context.tasks
            if set(task.component_ids).intersection(relevant_component_ids)
            or (agent and agent.id in task.assignee_agent_ids)
        ]
        decisions = self.brain.get_relevant_decisions(request.project_id, list(relevant_component_ids))
        changes = [
            change for change in context.recent_changes if change.component_id in relevant_component_ids
        ][:10]
        components = [item for item in context.components if item.id in relevant_component_ids]
        relationship_lines = []
        component_names = {item.id: item.name for item in context.components}
        for relation in context.relationships:
            relationship_lines.append(
                f"{component_names.get(relation.source_component_id, 'Unknown')} "
                f"{relation.relationship_type} {component_names.get(relation.target_component_id, 'Unknown')}"
            )

        role_info = [
            f"Your {request.role} context emphasizes: {', '.join(item.name for item in components)}."
        ]
        starting_points = [f"Review component: {item.name} — {item.description}" for item in components[:3]]
        starting_points.extend(f"Pick up task: {task.title}" for task in relevant_tasks[:2])
        if not starting_points:
            starting_points.append("Review the project architecture and current project state.")

        state = self.brain.get_project_state(request.project_id)
        briefing = self._render_briefing(
            request.name,
            request.role,
            context.project.name,
            context.project.purpose,
            components,
            relevant_tasks,
            decisions,
            changes,
            starting_points,
        )
        return OnboardingPackage(
            project=context.project,
            role=request.role,
            architecture=relationship_lines,
            major_components=components,
            technology_stack=context.project.technology_stack,
            current_state=state,
            relevant_tasks=relevant_tasks,
            important_decisions=decisions,
            recent_changes=changes,
            role_specific_information=role_info,
            recommended_starting_points=starting_points,
            briefing=briefing,
        )

    @staticmethod
    def _render_briefing(name, role, project_name, purpose, components, tasks, decisions, changes, starts):
        return "\n".join(
            [
                f"Welcome {name}. You are joining {project_name} as {role}.",
                f"Purpose: {purpose}",
                "Your relevant components: " + (", ".join(item.name for item in components) or "all project components"),
                "Current work: " + (", ".join(item.title for item in tasks) or "No role-specific task is assigned yet."),
                f"Important decisions available: {len(decisions)}; recent relevant changes: {len(changes)}.",
                "Start here: " + starts[0],
            ]
        )
