from fastapi.testclient import TestClient
from app.main import create_app

def test_golden_state_and_event_contract():
    client=TestClient(create_app())
    project=client.app.state.repository.list_projects()[0]
    state=client.get(f"/api/v1/projects/{project.id}/state")
    assert state.status_code == 200 and state.json()["success"]
    event=client.post("/api/v1/events",json={"project_id":str(project.id),"event_type":"TEST_COMPLETED","description":"Persistence contract verified"})
    assert event.status_code == 201
    assert client.get("/api/v1/events",params={"project_id":str(project.id)}).json()["data"][0]["event_type"] == "TEST_COMPLETED"

def test_task_updates_messages_context_updates_and_time_travel():
    client=TestClient(create_app())
    repo=client.app.state.repository; project=repo.list_projects()[0]
    task=repo.list_tasks(project.id)[0]; agents=repo.list_agents(project.id)
    changed=client.patch(f"/api/v1/tasks/{task.id}",json={"status":"COMPLETED"})
    assert changed.status_code == 200 and changed.json()["data"]["status"] == "COMPLETED"
    assert client.get(f"/api/v1/agents/{task.agent_id}/updates").status_code == 200
    recipient=next(agent for agent in agents if agent.id != task.agent_id)
    sent=client.post(f"/api/v1/agents/{task.agent_id}/messages",json={"project_id":str(project.id),"recipient_agent_id":str(recipient.id),"subject":"Work complete","content":"The persistence task is complete."})
    assert sent.status_code == 201
    messages=client.get(f"/api/v1/agents/{recipient.id}/messages",params={"project_id":str(project.id)})
    assert messages.json()["data"][0]["subject"] == "Work complete"
    history=client.get(f"/api/v1/projects/{project.id}/state/at",params={"timestamp":"2030-01-01T00:00:00Z"})
    assert history.status_code == 200 and history.json()["data"]["events_replayed"] >= 2
