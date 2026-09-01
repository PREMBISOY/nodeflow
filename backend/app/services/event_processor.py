from __future__ import annotations

import logging
from uuid import UUID

from app.engines.impact_analysis import ChangeImpactAnalyzer
from app.engines.relevance import RelevanceEngine
from app.models import Change, ContextUpdate, Event
from app.models.entities import utc_now
from app.schemas.intelligence import EventCreate, EventProcessingResult
from app.services.agent_gateway import AgentGateway
from app.services.repository import ProjectKnowledgeRepository


logger = logging.getLogger(__name__)


class EventProcessor:
    PROPAGATION_THRESHOLD = 0.50

    def __init__(
        self,
        repository: ProjectKnowledgeRepository,
        impact_analyzer: ChangeImpactAnalyzer,
        relevance_engine: RelevanceEngine,
        gateway: AgentGateway,
    ):
        self.repository = repository
        self.impact_analyzer = impact_analyzer
        self.relevance_engine = relevance_engine
        self.gateway = gateway

    def process(self, request: EventCreate) -> EventProcessingResult:
        self.repository.get_project(request.project_id)
        project_components = {
            component.id: component for component in self.repository.list_components(request.project_id)
        }
        component_ids = list(dict.fromkeys(request.component_ids))
        change_requests = ([request.change] if request.change is not None else []) + request.changes
        changes: list[Change] = []
        impacts = []

        if request.actor_type == "agent":
            if request.actor_id is None:
                raise ValueError("An agent event requires actor_id")
            actor = self.repository.get_agent(request.actor_id)
            if actor.project_id != request.project_id:
                raise ValueError("Event actor does not belong to the event project")

        for component_id in component_ids:
            if component_id not in project_components:
                raise ValueError(f"Component '{component_id}' does not belong to the event project")

        seen_change_components: set[UUID] = set()
        for item in change_requests:
            if item.component_id in seen_change_components:
                continue
            seen_change_components.add(item.component_id)
            if item.component_id not in project_components:
                raise ValueError(
                    f"Changed component '{item.component_id}' does not belong to the event project"
                )
            change = Change(project_id=request.project_id, **item.model_dump())
            changes.append(change)
            if change.component_id not in component_ids:
                component_ids.append(change.component_id)

        # Analyze every change before writing anything. This avoids persisting an
        # event when one of its component references is invalid and lets a single
        # Git delivery describe changes across independent components.
        impacts = [self.impact_analyzer.analyze(change) for change in changes]
        event = Event(
            project_id=request.project_id,
            event_type=request.event_type,
            actor_type=request.actor_type,
            actor_id=request.actor_id,
            entity_id=request.entity_id,
            component_ids=component_ids,
            summary=request.summary,
            payload=request.payload,
            created_at=request.occurred_at or utc_now(),
        )
        self.repository.add_event(event)
        if not changes:
            logger.info("Recorded non-change event %s", event.id)
            return EventProcessingResult(event=event, impact=None, impacts=[], propagated_to=[])

        for change in changes:
            self.repository.add_change(change)
        propagated_to: list[UUID] = []
        for agent in self.repository.list_agents(request.project_id):
            if not agent.active:
                continue
            scored_impacts = [
                (*self.relevance_engine.score(agent, event, impact), impact) for impact in impacts
            ]
            score, reasons, _best_impact = max(scored_impacts, key=lambda item: item[0])
            if score < self.PROPAGATION_THRESHOLD:
                continue
            relevant_impacts = [impact for item_score, _item_reasons, impact in scored_impacts if item_score > 0]
            relevant_reasons = list(dict.fromkeys(
                reason
                for item_score, item_reasons, _impact in scored_impacts
                if item_score > 0
                for reason in item_reasons
            ))
            relevant_change_ids = {impact.change.id for impact in relevant_impacts}
            related_component_ids = list(dict.fromkeys([
                *(
                    change.component_id
                    for change in changes
                    if change.id in relevant_change_ids
                ),
                *(
                    component.id
                    for impact in relevant_impacts
                    for component in impact.affected_components
                ),
            ]))
            update = ContextUpdate(
                project_id=request.project_id,
                recipient_agent_id=agent.id,
                source_event_id=event.id,
                subject=request.summary,
                content=self._assemble_update(relevant_impacts, relevant_reasons or reasons),
                related_component_ids=related_component_ids,
                relevance_score=score,
            )
            self.repository.add_update(update)
            self.gateway.publish_context_update(update)
            propagated_to.append(agent.id)
        logger.info("Processed event %s and propagated to %d agent(s)", event.id, len(propagated_to))
        return EventProcessingResult(
            event=event,
            impact=impacts[0],
            impacts=impacts,
            propagated_to=propagated_to,
        )

    @staticmethod
    def _assemble_update(impacts, relevance_reasons: list[str]) -> str:
        summaries = "; ".join(dict.fromkeys(impact.change.summary for impact in impacts))
        component_names = ", ".join(dict.fromkeys(
            component.name for impact in impacts for component in impact.affected_components
        )) or "none"
        levels = {"low": 1, "medium": 2, "high": 3}
        impact_level = max((impact.impact_level for impact in impacts), key=levels.get)
        return (
            f"{summaries} Impact level: {impact_level}. "
            f"Affected connected components: {component_names}. "
            f"Relevant because: {', '.join(relevance_reasons)}."
        )
