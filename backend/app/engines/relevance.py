from __future__ import annotations

from app.models import Agent, Event
from app.schemas.intelligence import ImpactAnalysisResult


class RelevanceEngine:
    """Scores need-to-know separately from permission checks."""

    def score(self, agent: Agent, event: Event, impact: ImpactAnalysisResult) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        owned_component_ids = set(agent.component_ids)
        if impact.change.component_id in owned_component_ids:
            score += 0.70
            reasons.append("agent owns the changed component")
        else:
            dependent_distances = [
                impact.affected_component_distances[component_id]
                for component_id in owned_component_ids
                if component_id in impact.affected_component_distances
            ]
            if dependent_distances:
                distance = min(dependent_distances)
                score += 0.50 + (0.10 if distance == 1 else 0.05)
                reasons.append(f"agent owns a dependent component at distance {distance}")

        affected_task_ids = {task.id for task in impact.affected_tasks}
        assigned_task_ids = set(agent.current_task_ids) | {
            task.id for task in impact.affected_tasks if agent.id in task.assignee_agent_ids
        }
        if affected_task_ids.intersection(assigned_task_ids):
            score += 0.20
            reasons.append("agent has an affected assigned task")

        if agent.role in impact.relevant_roles:
            score += 0.10
            reasons.append("agent role is relevant to the impact")

        if event.event_type.startswith(("api_", "github_", "component_")) and reasons:
            score += 0.05
            reasons.append("event type represents a source-code or contract change")

        if event.actor_id == agent.id:
            score -= 0.85
            reasons.append("agent originated the event")

        return round(max(0.0, min(score, 1.0)), 2), reasons
