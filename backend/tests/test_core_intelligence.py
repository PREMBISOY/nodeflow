from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.demo_data import DEMO_IDS
from app.main import create_app


def build_client() -> TestClient:
    return TestClient(create_app())


def test_project_brain_contracts_return_structured_context():
    client = build_client()
    project_id = DEMO_IDS["project"]

    project = client.get(f"/api/v1/projects/{project_id}")
    context = client.get(f"/api/v1/projects/{project_id}/context")

    assert project.status_code == 200
    assert project.json()["data"]["name"] == "NodeFlow"
    assert len(context.json()["data"]["components"]) == 4
    assert len(context.json()["data"]["relationships"]) == 2
    assert len(context.json()["data"]["agents"]) == 4
    assert all(response.json()["success"] for response in [project, context])


def test_non_owned_feature_routes_are_not_implemented():
    client = build_client()
    project_id = DEMO_IDS["project"]

    for suffix in ["state", "architecture", "decisions", "memory"]:
        assert client.get(f"/api/v1/projects/{project_id}/{suffix}").status_code == 404


def test_golden_demo_change_impacts_frontend_and_ml_but_not_marketing():
    client = build_client()
    response = client.post(
        "/api/v1/events",
        json={
            "project_id": str(DEMO_IDS["project"]),
            "event_type": "api_changed",
            "actor_type": "agent",
            "actor_id": str(DEMO_IDS["backend_agent"]),
            "component_ids": [str(DEMO_IDS["recommendations_api"])],
            "summary": "Backend created GET /recommendations",
            "change": {
                "component_id": str(DEMO_IDS["recommendations_api"]),
                "summary": "Added GET /recommendations",
                "change_type": "created",
                "source_ref": "main:backend/app/api/recommendations.py",
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    impact = body["data"]["impact"]
    assert {item["name"] for item in impact["affected_components"]} == {"Frontend", "ML Service"}
    assert impact["impact_level"] == "medium"
    assert set(body["data"]["propagated_to"]) == {
        str(DEMO_IDS["frontend_agent"]),
        str(DEMO_IDS["ml_agent"]),
    }

    frontend_updates = client.get(f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/updates").json()["data"]
    ml_updates = client.get(f"/api/v1/agents/{DEMO_IDS['ml_agent']}/updates").json()["data"]
    marketing_updates = client.get(f"/api/v1/agents/{DEMO_IDS['marketing_agent']}/updates").json()["data"]
    assert len(frontend_updates) == 1
    assert len(ml_updates) == 1
    assert marketing_updates == []
    assert "Added GET /recommendations" in frontend_updates[0]["content"]


def test_related_context_includes_dependency_but_excludes_marketing():
    client = build_client()
    response = client.get(
        f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/context",
        params={"scope": "related"},
    )
    names = {item["name"] for item in response.json()["data"]["components"]}
    assert names == {"Frontend", "Recommendations API"}


def test_agent_message_is_delivered_and_recorded_as_project_history():
    client = build_client()
    before_events = client.get(
        f"/api/v1/projects/{DEMO_IDS['project']}/context"
    ).json()["data"]["recent_events"]
    response = client.post(
        f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/messages",
        json={
            "recipient_agent_id": str(DEMO_IDS["backend_agent"]),
            "message_type": "acknowledgement",
            "subject": "Recommendations API integration",
            "content": "I'll integrate the new API.",
            "related_components": [str(DEMO_IDS["frontend"]), str(DEMO_IDS["recommendations_api"])],
        },
    )
    after_events = client.get(
        f"/api/v1/projects/{DEMO_IDS['project']}/context"
    ).json()["data"]["recent_events"]

    assert response.status_code == 201
    assert response.json()["data"]["content"] == "I'll integrate the new API."
    assert len(after_events) == len(before_events) + 1
    assert after_events[0]["event_type"] == "agent_message"


def test_rahul_receives_role_specific_onboarding_from_project_brain():
    client = build_client()
    client.post(
        "/api/v1/events",
        json={
            "project_id": str(DEMO_IDS["project"]),
            "event_type": "api_changed",
            "summary": "Recommendations API added",
            "change": {
                "component_id": str(DEMO_IDS["recommendations_api"]),
                "summary": "Added GET /recommendations",
                "change_type": "created",
            },
        },
    )
    response = client.post(
        "/api/v1/onboarding",
        json={
            "project_id": str(DEMO_IDS["project"]),
            "name": "Rahul",
            "role": "Frontend Engineer",
            "scope": "related",
            "question": "Explain this project to me.",
        },
    )

    assert response.status_code == 200
    package = response.json()["data"]
    assert package["project"]["name"] == "NodeFlow"
    assert {item["name"] for item in package["major_components"]} == {
        "Frontend", "Recommendations API"
    }
    assert package["recent_changes"][0]["summary"] == "Added GET /recommendations"
    assert "Welcome Rahul" in package["briefing"]
    assert package["recommended_starting_points"]


def test_failures_use_standard_response_shape():
    client = build_client()
    response = client.get("/api/v1/projects/99999999-9999-9999-9999-999999999999")
    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "data": None,
        "error": {
            "code": "NOT_FOUND",
            "message": "Project '99999999-9999-9999-9999-999999999999' was not found",
        },
    }
