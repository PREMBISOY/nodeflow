from __future__ import annotations

from dataclasses import dataclass

from app.engines.impact_analysis import ChangeImpactAnalyzer
from app.engines.relevance import RelevanceEngine
from app.services.agent_gateway import RecordingAgentGateway
from app.services.context_service import ContextService
from app.services.event_processor import EventProcessor
from app.services.git_intelligence import GitIntelligenceService
from app.services.collaboration import CollaborationService
from app.services.messaging import MessagingService
from app.services.onboarding import OnboardingService
from app.services.project_brain import ProjectBrain
from app.services.repository import InMemoryProjectRepository, ProjectKnowledgeRepository


@dataclass
class ServiceContainer:
    repository: ProjectKnowledgeRepository
    brain: ProjectBrain
    context: ContextService
    impact: ChangeImpactAnalyzer
    events: EventProcessor
    messaging: MessagingService
    onboarding: OnboardingService
    git: GitIntelligenceService
    collaboration: CollaborationService
    gateway: RecordingAgentGateway


def build_container(repository: ProjectKnowledgeRepository | None = None) -> ServiceContainer:
    repository = repository or InMemoryProjectRepository()
    brain = ProjectBrain(repository)
    impact = ChangeImpactAnalyzer(repository)
    relevance = RelevanceEngine()
    gateway = RecordingAgentGateway()
    events = EventProcessor(repository, impact, relevance, gateway)
    return ServiceContainer(
        repository=repository,
        brain=brain,
        context=ContextService(repository, brain),
        impact=impact,
        events=events,
        messaging=MessagingService(repository, gateway),
        onboarding=OnboardingService(repository, brain),
        git=GitIntelligenceService(repository, events),
        collaboration=CollaborationService(repository, brain),
        gateway=gateway,
    )
