from __future__ import annotations

from uuid import UUID

from app.models import Agent, Component, Decision, Event, Memory, Project, Relationship, Task
from app.services.repository import InMemoryProjectRepository


DEMO_IDS = {
    "project": UUID("10000000-0000-0000-0000-000000000001"),
    "frontend": UUID("20000000-0000-0000-0000-000000000001"),
    "recommendations_api": UUID("20000000-0000-0000-0000-000000000002"),
    "ml": UUID("20000000-0000-0000-0000-000000000003"),
    "marketing": UUID("20000000-0000-0000-0000-000000000004"),
    "backend_agent": UUID("30000000-0000-0000-0000-000000000001"),
    "frontend_agent": UUID("30000000-0000-0000-0000-000000000002"),
    "ml_agent": UUID("30000000-0000-0000-0000-000000000003"),
    "marketing_agent": UUID("30000000-0000-0000-0000-000000000004"),
    "frontend_task": UUID("40000000-0000-0000-0000-000000000001"),
    "ml_task": UUID("40000000-0000-0000-0000-000000000002"),
}


def seed_demo(repository: InMemoryProjectRepository) -> None:
    project_id = DEMO_IDS["project"]
    frontend = Component(
        id=DEMO_IDS["frontend"], project_id=project_id, name="Frontend",
        description="User-facing collaborative workspace", kind="application",
        owner_role="Frontend Engineer", tags=["frontend", "ui", "path:frontend"],
    )
    api = Component(
        id=DEMO_IDS["recommendations_api"], project_id=project_id, name="Recommendations API",
        description="GET /recommendations backend contract", kind="api",
        owner_role="Backend Engineer", tags=["backend", "api", "path:backend"],
    )
    ml = Component(
        id=DEMO_IDS["ml"], project_id=project_id, name="ML Service",
        description="Produces recommendation candidates", kind="service",
        owner_role="ML Engineer", tags=["ml", "ai", "path:ml"],
    )
    marketing = Component(
        id=DEMO_IDS["marketing"], project_id=project_id, name="Marketing Site",
        description="Public product information", kind="application",
        owner_role="Marketing", tags=["marketing", "path:marketing"],
    )
    frontend_agent = Agent(
        id=DEMO_IDS["frontend_agent"], project_id=project_id, name="Aarya's Agent",
        role="Frontend Engineer", model_provider="Claude", component_ids=[frontend.id],
        current_task_ids=[DEMO_IDS["frontend_task"]],
    )
    ml_agent = Agent(
        id=DEMO_IDS["ml_agent"], project_id=project_id, name="ML Agent",
        role="ML Engineer", model_provider="ChatGPT", component_ids=[ml.id],
        current_task_ids=[DEMO_IDS["ml_task"]],
    )
    repository.seed(
        Project(
            id=project_id,
            name="NodeFlow",
            purpose="A shared project-intelligence layer for humans and heterogeneous AI agents.",
            technology_stack=["Python", "FastAPI", "Pydantic", "PostgreSQL"],
        ),
        frontend,
        api,
        ml,
        marketing,
        Relationship(
            project_id=project_id, source_component_id=frontend.id, target_component_id=api.id,
            description="Frontend consumes GET /recommendations",
        ),
        Relationship(
            project_id=project_id, source_component_id=api.id, target_component_id=ml.id,
            description="Recommendations API consumes ML candidates",
        ),
        Task(
            id=DEMO_IDS["frontend_task"], project_id=project_id,
            title="Integrate recommendations UI", status="in_progress",
            component_ids=[frontend.id, api.id], assignee_agent_ids=[frontend_agent.id],
        ),
        Task(
            id=DEMO_IDS["ml_task"], project_id=project_id,
            title="Expose recommendation candidates", status="in_progress",
            component_ids=[ml.id, api.id], assignee_agent_ids=[ml_agent.id],
        ),
        Agent(
            id=DEMO_IDS["backend_agent"], project_id=project_id, name="Prem's Agent",
            role="Backend Engineer", model_provider="Codex", component_ids=[api.id],
        ),
        frontend_agent,
        ml_agent,
        Agent(
            id=DEMO_IDS["marketing_agent"], project_id=project_id, name="Marketing Agent",
            role="Marketing", model_provider="ChatGPT", component_ids=[marketing.id],
        ),
        Decision(
            project_id=project_id, title="Project is the source of intelligence truth",
            rationale="Shared context must survive individual AI conversations.",
        ),
        Decision(
            project_id=project_id, title="Use a stable recommendations contract",
            rationale="Frontend and ML integrations need a shared deterministic API.",
            component_ids=[frontend.id, api.id, ml.id],
        ),
        Memory(
            project_id=project_id,
            content="The recommendations flow connects Frontend to Recommendations API to ML Service.",
            component_ids=[frontend.id, api.id, ml.id], tags=["recommendations", "architecture"],
        ),
        Event(
            project_id=project_id, event_type="project_initialized", summary="Golden demo data loaded",
            component_ids=[frontend.id, api.id, ml.id],
        ),
    )
