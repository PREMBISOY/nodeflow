import os
import sys
import tempfile
from pathlib import Path

os.environ["NODEFLOW_DATABASE"] = str(Path(tempfile.gettempdir()) / "nodeflow_agent_gateway_test.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def register(name):
    return client.post("/api/v1/agents/register", json={"project_id":"p1", "owner_id":"h1", "name":name, "provider":"custom", "model":"test", "role":"Engineer", "capabilities":["events"]}).json()["data"]

def test_register_context_event_message_and_updates():
    with TestClient(app):
        sender, recipient = register("Backend"), register("Frontend")
        assert client.get(f"/api/v1/agents/{sender['id']}/context").json()["data"]["project_id"] == "p1"
        event = client.post(f"/api/v1/agents/{sender['id']}/events", json={"event_type":"API_CREATED", "payload":{"path":"/recommendations", "affected_agent_ids":[recipient["id"]], "impact_message":"Backend created /recommendations. You may need to integrate it.", "related_components":["frontend"]}}).json()
        assert event["data"]["event_type"] == "API_CREATED"
        updates = client.get(f"/api/v1/agents/{recipient['id']}/updates").json()["data"]
        assert updates[0]["content"] == "Backend created /recommendations. You may need to integrate it."

def test_approval_and_verification():
    with TestClient(app):
        agent = register("Verifier")
        proposed = client.post(f"/api/v1/agents/{agent['id']}/collaborate", json={"action":"create_branch", "details":{"branch":"agent/test"}}).json()["data"]
        decided = client.post(f"/api/v1/approvals/{proposed['id']}/decision", json={"approved":True, "decided_by":"human-1"}).json()["data"]
        assert decided["status"] == "approved"
        verification = client.post(f"/api/v1/agents/{agent['id']}/verifications", json={"test_type":"integration", "status":"passed", "affected_components":["backend"], "summary":"Gateway test passed"}).json()
        assert verification["data"]["status"] == "passed"
