from __future__ import annotations

from app.models import Agent, Event
from app.schemas.intelligence import ImpactAnalysisResult


class RelevanceEngine:
    """Scores need-to-know separately from permission checks."""

    def score(self, agent: Agent, event: Event, impact: ImpactAnalysisResult) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        impacted_ids = {impact.change.component_id, *(item.id for item in impact.affected_components)}
        direct = impacted_ids.intersection(agent.component_ids)
        if direct:
            score += 0.65
            reasons.append("agent owns or works on an impacted component")

        affected_task_ids = {task.id for task in impact.affected_tasks}
        if affected_task_ids.intersection(agent.current_task_ids):
            score += 0.25
            reasons.append("agent has an affected assigned task")

        if agent.role in impact.relevant_roles:
            score += 0.10
            reasons.append("agent role is relevant to the impact")

        if event.actor_id == agent.id:
            score -= 0.50
            reasons.append("agent originated the event")

        return max(0.0, min(score, 1.0)), reasons
