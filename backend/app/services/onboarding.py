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
        if agent and not agent.active:
            raise ValueError("Inactive agents cannot receive onboarding context")
        agent_tasks = [
            task
            for task in context.tasks
            if agent
            and (task.id in agent.current_task_ids or agent.id in task.assignee_agent_ids)
        ]
        relevant_component_ids = (
            set(agent.component_ids) | {
                component_id for task in agent_tasks for component_id in task.component_ids
            }
        ) if agent else {
            component.id
            for component in context.components
            if role_terms.intersection({token.lower() for token in component.tags})
            or (component.owner_role and any(term in component.owner_role.lower() for term in role_terms))
        }
        if request.scope == "team":
            active_agent_ids = {item.id for item in context.agents if item.active}
            team_tasks = [
                task
                for task in context.tasks
                if set(task.assignee_agent_ids).intersection(active_agent_ids)
            ]
            relevant_component_ids = {
                component_id
                for item in context.agents
                if item.active
                for component_id in item.component_ids
            } | {
                component_id for task in team_tasks for component_id in task.component_ids
            }
        elif request.scope == "project":
            relevant_component_ids = {component.id for component in context.components}
        elif not relevant_component_ids:
            relevant_component_ids = {component.id for component in context.components}

        if request.scope == "related":
            graph = DependencyGraph(context.relationships)
            for component_id in list(relevant_component_ids):
                relevant_component_ids.update(graph.related(component_id, max_depth=1))

        relevant_tasks = [
            task
            for task in context.tasks
            if set(task.component_ids).intersection(relevant_component_ids)
            or (agent and agent.id in task.assignee_agent_ids)
        ]
        decisions = self.brain.get_relevant_decisions(request.project_id, list(relevant_component_ids))
        question_memories = self.brain.get_relevant_memory(request.project_id, request.question)
        relevant_memories = [
            memory
            for memory in context.memories
            if not memory.component_ids
            or set(memory.component_ids).intersection(relevant_component_ids)
        ]
        if question_memories:
            question_memory_ids = {memory.id for memory in question_memories}
            relevant_memories.sort(
                key=lambda memory: (
                    memory.id in question_memory_ids,
                    memory.created_at,
                ),
                reverse=True,
            )
        changes = [
            change for change in context.recent_changes if change.component_id in relevant_component_ids
        ][:10]
        components = [item for item in context.components if item.id in relevant_component_ids]
        relationship_lines = []
        component_names = {item.id: item.name for item in context.components}
        for relation in context.relationships:
            if not {
                relation.source_component_id,
                relation.target_component_id,
            }.issubset(relevant_component_ids):
                continue
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
            relevant_memories,
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
            relevant_memories=relevant_memories,
            recent_changes=changes,
            role_specific_information=role_info,
            recommended_starting_points=starting_points,
            briefing=briefing,
        )

    @staticmethod
    def _render_briefing(
        name,
        role,
        project_name,
        purpose,
        components,
        tasks,
        decisions,
        memories,
        changes,
        starts,
    ):
        return "\n".join(
            [
                f"Welcome {name}. You are joining {project_name} as {role}.",
                f"Purpose: {purpose}",
                "Your relevant components: " + (", ".join(item.name for item in components) or "all project components"),
                "Current work: " + (", ".join(item.title for item in tasks) or "No role-specific task is assigned yet."),
                (
                    f"Important decisions available: {len(decisions)}; "
                    f"project memories: {len(memories)}; recent relevant changes: {len(changes)}."
                ),
                "Start here: " + starts[0],
            ]
        )
