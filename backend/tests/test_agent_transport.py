from uuid import uuid4

from app.models import ContextUpdate, Message
from tests.fixtures.demo_data import DEMO_IDS
from app.main import create_app
from app.services.agent_gateway import TransportAgentGateway, WebhookAgentTransport
from fastapi.testclient import TestClient


def seeded_client(gateway):
    return TestClient(create_app(gateway=gateway))


def test_transport_gateway_emits_provider_neutral_envelopes():
    received = []
    project_id, recipient_id, event_id, sender_id = uuid4(), uuid4(), uuid4(), uuid4()
    gateway = TransportAgentGateway(received.append)
    gateway.publish_context_update(ContextUpdate(project_id=project_id, recipient_agent_id=recipient_id, source_event_id=event_id, subject="API changed", content="Review integration.", relevance_score=0.8))
    gateway.send_message(Message(project_id=project_id, sender_agent_id=sender_id, recipient_agent_id=recipient_id, message_type="context_update", subject="Backend update", content="Endpoint is ready."))
    assert [item["type"] for item in received] == ["context_update", "agent_message"]
    assert all(item["recipient_agent_id"] == str(recipient_id) for item in received)


def test_transport_adapter_can_be_injected_into_the_application():
    received = []
    client = seeded_client(TransportAgentGateway(received.append))
    response = client.post(f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/messages", json={
        "recipient_agent_id": str(DEMO_IDS["backend_agent"]),
        "message_type": "acknowledgement",
        "subject": "Integration status",
        "content": "The frontend can proceed.",
    })
    assert response.status_code == 201
    assert received[0]["type"] == "agent_message"
    assert received[0]["recipient_agent_id"] == str(DEMO_IDS["backend_agent"])


def test_impact_propagation_reaches_the_injected_transport():
    received = []
    client = seeded_client(TransportAgentGateway(received.append))
    response = client.post("/api/v1/events", json={
        "project_id": str(DEMO_IDS["project"]),
        "event_type": "API_CHANGED",
        "actor_type": "agent",
        "actor_id": str(DEMO_IDS["backend_agent"]),
        "component_ids": [str(DEMO_IDS["recommendations_api"])],
        "summary": "Recommendations API changed",
        "change": {
            "component_id": str(DEMO_IDS["recommendations_api"]),
            "summary": "Updated recommendations response.",
        },
    })
    assert response.status_code == 201
    updates = [item for item in received if item["type"] == "context_update"]
    assert {item["recipient_agent_id"] for item in updates} == {
        str(DEMO_IDS["frontend_agent"]), str(DEMO_IDS["ml_agent"]),
    }


def test_webhook_transport_posts_to_a_nodeflow_relay():
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    class Client:
        def post(self, endpoint, json):
            calls.append((endpoint, json))
            return Response()

    WebhookAgentTransport("https://relay.example/deliver", client=Client()).deliver({"type": "agent_message"})
    assert calls == [("https://relay.example/deliver", {"type": "agent_message"})]
