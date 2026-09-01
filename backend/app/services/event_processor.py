from __future__ import annotations

import logging
from uuid import UUID

from app.engines.impact_analysis import ChangeImpactAnalyzer
from app.engines.relevance import RelevanceEngine
from app.models import Change, ContextUpdate, Event
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
        event = Event(
            project_id=request.project_id,
            event_type=request.event_type,
            actor_type=request.actor_type,
            actor_id=request.actor_id,
            entity_id=request.entity_id,
            component_ids=request.component_ids,
            summary=request.summary,
            payload=request.payload,
        )
        self.repository.add_event(event)
        if request.change is None:
            logger.info("Recorded non-change event %s", event.id)
            return EventProcessingResult(event=event, impact=None, propagated_to=[])

        change = Change(project_id=request.project_id, **request.change.model_dump())
        self.repository.add_change(change)
        if change.component_id not in event.component_ids:
            event.component_ids.append(change.component_id)
        impact = self.impact_analyzer.analyze(change)
        propagated_to: list[UUID] = []
        for agent in self.repository.list_agents(request.project_id):
            if not agent.active:
                continue
            score, reasons = self.relevance_engine.score(agent, event, impact)
            if score < self.PROPAGATION_THRESHOLD:
                continue
            update = ContextUpdate(
                project_id=request.project_id,
                recipient_agent_id=agent.id,
                source_event_id=event.id,
                subject=request.summary,
                content=self._assemble_update(impact, reasons),
                related_component_ids=[change.component_id, *(item.id for item in impact.affected_components)],
                relevance_score=score,
            )
            self.repository.add_update(update)
            self.gateway.publish_context_update(update)
            propagated_to.append(agent.id)
        logger.info("Processed event %s and propagated to %d agent(s)", event.id, len(propagated_to))
        return EventProcessingResult(event=event, impact=impact, propagated_to=propagated_to)

    @staticmethod
    def _assemble_update(impact, relevance_reasons: list[str]) -> str:
        component_names = ", ".join(item.name for item in impact.affected_components) or "none"
        return (
            f"{impact.change.summary} Impact level: {impact.impact_level}. "
            f"Affected connected components: {component_names}. "
            f"Relevant because: {', '.join(relevance_reasons)}."
        )
