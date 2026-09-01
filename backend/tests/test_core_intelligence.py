from __future__ import annotations

from fastapi.testclient import TestClient

from tests.fixtures.demo_data import DEMO_IDS
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


def test_project_brain_read_routes_are_implemented():
    client = build_client()
    project_id = DEMO_IDS["project"]

    for suffix in ["state", "architecture", "decisions", "memory"]:
        response = client.get(f"/api/v1/projects/{project_id}/{suffix}")
        assert response.status_code == 200
        assert response.json()["success"] is True

    memory = client.get(
        f"/api/v1/projects/{project_id}/memory", params={"query": "recommendation"}
    ).json()["data"]
    assert [item["content"] for item in memory] == [
        "The recommendations flow connects Frontend to Recommendations API to ML Service."
    ]

    architecture = client.get(
        f"/api/v1/projects/{project_id}/architecture"
    ).json()["data"]
    assert len(architecture["components"]) == 4
    assert len(architecture["relationships"]) == 2


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
    assert impact["affected_component_distances"] == {
        str(DEMO_IDS["frontend"]): 1,
        str(DEMO_IDS["ml"]): 1,
    }
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
    assert frontend_updates[0]["relevance_score"] == 0.95


def test_project_brain_memory_search_ranks_normalized_partial_matches():
    client = build_client()
    brain = client.app.state.container.brain

    results = brain.get_relevant_memory(DEMO_IDS["project"], "recommendation")

    assert [memory.content for memory in results] == [
        "The recommendations flow connects Frontend to Recommendations API to ML Service."
    ]


def test_related_context_includes_dependency_but_excludes_marketing():
    client = build_client()
    response = client.get(
        f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/context",
        params={"scope": "related"},
    )
    names = {item["name"] for item in response.json()["data"]["components"]}
    assert names == {"Frontend", "Recommendations API"}


def test_agent_context_supports_an_explicit_task_handoff():
    client = build_client()
    response = client.get(
        f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/context",
        params={"scope": "my_work", "task_id": str(DEMO_IDS["ml_task"])},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requested_task"]["id"] == str(DEMO_IDS["ml_task"])
    assert {item["id"] for item in data["tasks"]} == {
        str(DEMO_IDS["frontend_task"]), str(DEMO_IDS["ml_task"])
    }
    assert {item["name"] for item in data["components"]} == {
        "Frontend", "Recommendations API", "ML Service"
    }


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
    assert package["relevant_memories"]
    assert package["recommended_starting_points"]


def test_event_references_are_validated_before_history_is_written():
    from uuid import uuid4

    client = build_client()
    repository = client.app.state.container.repository
    event_count = len(repository.events)
    change_count = len(repository.changes)

    invalid_actor = client.post(
        "/api/v1/events",
        json={
            "project_id": str(DEMO_IDS["project"]),
            "event_type": "task_updated",
            "actor_type": "agent",
            "actor_id": str(uuid4()),
            "summary": "Forged actor",
        },
    )
    invalid_component = client.post(
        "/api/v1/events",
        json={
            "project_id": str(DEMO_IDS["project"]),
            "event_type": "component_changed",
            "summary": "Forged component",
            "change": {
                "component_id": str(uuid4()),
                "summary": "Invalid change",
            },
        },
    )

    assert invalid_actor.status_code == 404
    assert invalid_component.status_code == 400
    assert len(repository.events) == event_count
    assert len(repository.changes) == change_count


def test_message_rejects_components_outside_the_agents_project_before_writing():
    from uuid import uuid4

    client = build_client()
    repository = client.app.state.container.repository
    message_count = len(repository.messages)
    event_count = len(repository.events)
    response = client.post(
        f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/messages",
        json={
            "recipient_agent_id": str(DEMO_IDS["backend_agent"]),
            "subject": "Invalid reference",
            "content": "This must not be recorded.",
            "related_components": [str(uuid4())],
        },
    )

    assert response.status_code == 400
    assert len(repository.messages) == message_count
    assert len(repository.events) == event_count


def test_github_commit_maps_changed_files_to_components_and_notifies_only_relevant_agents():
    client = build_client()
    response = client.post(
        "/api/v1/integrations/github/events",
        json={
            "project_id": str(DEMO_IDS["project"]),
            "event_type": "commit",
            "repository": "PREMBISOY/nodeflow",
            "summary": "Add recommendations endpoint",
            "commit_sha": "abc123",
            "changed_files": ["backend/recommendations.py", "backend/routes.py"],
            "actor_name": "Prem",
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["event"]["event_type"] == "github_commit"
    assert body["event"]["payload"]["changed_files"] == [
        "backend/recommendations.py", "backend/routes.py"
    ]
    assert set(body["propagated_to"]) == {
        str(DEMO_IDS["frontend_agent"]), str(DEMO_IDS["ml_agent"])
    }


def test_github_commit_analyzes_every_independently_changed_component():
    client = build_client()
    response = client.post(
        "/api/v1/integrations/github/events",
        json={
            "project_id": str(DEMO_IDS["project"]),
            "event_type": "commit",
            "repository": "PREMBISOY/nodeflow",
            "summary": "Update backend and marketing",
            "commit_sha": "multi123",
            "changed_files": ["backend/routes.py", "marketing/index.html"],
            "actor_name": "Prem",
        },
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert len(data["impacts"]) == 2
    assert {impact["change"]["component_id"] for impact in data["impacts"]} == {
        str(DEMO_IDS["recommendations_api"]), str(DEMO_IDS["marketing"])
    }
    assert set(data["propagated_to"]) == {
        str(DEMO_IDS["frontend_agent"]),
        str(DEMO_IDS["ml_agent"]),
        str(DEMO_IDS["marketing_agent"]),
    }
    repository = client.app.state.container.repository
    marketing_update = repository.list_updates(DEMO_IDS["marketing_agent"])[0]
    assert marketing_update.related_component_ids == [DEMO_IDS["marketing"]]
    frontend_update = repository.list_updates(DEMO_IDS["frontend_agent"])[0]
    assert DEMO_IDS["marketing"] not in frontend_update.related_component_ids


def test_collaboration_state_explains_timeline_notifications_and_approval_waiting():
    client = build_client()
    client.post(
        "/api/v1/integrations/github/events",
        json={
            "project_id": str(DEMO_IDS["project"]), "event_type": "pull_request",
            "repository": "PREMBISOY/nodeflow", "summary": "Review recommendations PR",
            "changed_files": ["backend/routes.py"], "requires_approval": True,
        },
    )
    response = client.get(f"/api/v1/projects/{DEMO_IDS['project']}/collaboration")

    assert response.status_code == 200
    state = response.json()["data"]
    assert state["timeline"][0]["event_type"] == "github_pull_request"
    assert state["notifications"]["total"] == 2
    assert state["waiting"] == [{
        "kind": "approval", "id": state["timeline"][0]["id"],
        "title": "Review recommendations PR", "status": "waiting_approval",
    }]


def test_human_can_resolve_an_approval_request_once_and_state_reflects_decision():
    client = build_client()
    created = client.post(
        "/api/v1/integrations/github/events",
        json={
            "project_id": str(DEMO_IDS["project"]), "event_type": "pull_request",
            "action": "opened", "repository": "PREMBISOY/nodeflow",
            "summary": "Review recommendations PR", "changed_files": ["backend/routes.py"],
        },
    ).json()["data"]["event"]
    response = client.post(
        f"/api/v1/projects/{DEMO_IDS['project']}/collaboration/approvals/{created['id']}",
        json={"project_id": str(DEMO_IDS["project"]), "decision": "approved",
              "actor_name": "Prem", "comment": "API contract looks good."},
    )

    assert response.status_code == 200
    state = client.get(f"/api/v1/projects/{DEMO_IDS['project']}/collaboration").json()["data"]
    assert state["approvals"] == [{
        "id": created["id"], "title": "Review recommendations PR", "status": "approved",
        "component_ids": [str(DEMO_IDS["recommendations_api"])],
    }]
    assert state["waiting"] == []
    duplicate = client.post(
        f"/api/v1/projects/{DEMO_IDS['project']}/collaboration/approvals/{created['id']}",
        json={"project_id": str(DEMO_IDS["project"]), "decision": "rejected", "actor_name": "Prem"},
    )
    assert duplicate.status_code == 400


def test_git_activity_normalizes_pr_review_and_merge_flow_stages():
    client = build_client()
    for action in ["opened", "merged"]:
        response = client.post(
            "/api/v1/integrations/github/events",
            json={
                "project_id": str(DEMO_IDS["project"]), "event_type": "pull_request", "action": action,
                "repository": "PREMBISOY/nodeflow", "summary": f"Recommendations PR {action}",
                "pull_request_number": 42, "changed_files": ["backend/routes.py"],
            },
        )
        assert response.status_code == 201

    activity = client.get(f"/api/v1/projects/{DEMO_IDS['project']}/git/activity").json()["data"]
    by_action = {item["action"]: item for item in activity}
    assert by_action["merged"]["flow_stage"] == "merged"
    assert by_action["merged"]["requires_approval"] is False
    assert by_action["opened"]["flow_stage"] == "review_required"
    assert by_action["opened"]["requires_approval"] is True


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
