from uuid import uuid4

import httpx
from app.models import ContextUpdate, Message
from app.core.container import build_container
from app.platform import PlatformStore
from tests.fixtures.demo_data import DEMO_IDS, seed_demo
from app.main import create_app, gateway_from_environment
import pytest

from app.services.agent_gateway import DeliveryError, TransportAgentGateway, WebhookAgentTransport
from fastapi.testclient import TestClient


def seeded_client(gateway):
    app = create_app(gateway=gateway)
    seed_demo(app.state.container.repository)
    return TestClient(app)


def test_transport_gateway_emits_provider_neutral_envelopes():
    received = []
    project_id, recipient_id, event_id, sender_id = uuid4(), uuid4(), uuid4(), uuid4()
    gateway = TransportAgentGateway(received.append)
    gateway.publish_context_update(ContextUpdate(project_id=project_id, recipient_agent_id=recipient_id, source_event_id=event_id, subject="API changed", content="Review integration.", relevance_score=0.8))
    gateway.send_message(Message(project_id=project_id, sender_agent_id=sender_id, recipient_agent_id=recipient_id, message_type="context_update", subject="Backend update", content="Endpoint is ready."))
    assert [item["type"] for item in received] == ["context_update", "agent_message"]
    assert all(item["recipient_agent_id"] == str(recipient_id) for item in received)


def test_transport_envelope_carries_authoritative_project_and_team_scope():
    received = []
    project_id, team_id, recipient_id, event_id = uuid4(), uuid4(), uuid4(), uuid4()
    gateway = TransportAgentGateway(received.append, agent_project=lambda _: project_id, project_team=lambda _: team_id)
    gateway.publish_context_update(ContextUpdate(project_id=project_id, recipient_agent_id=recipient_id, source_event_id=event_id, subject="Scoped", content="Scoped update", relevance_score=1))
    assert received[0]["project_id"] == str(project_id)
    assert received[0]["team_id"] == str(team_id)


def test_transport_rejects_cross_project_recipient():
    project_id, other_project, recipient_id, event_id = uuid4(), uuid4(), uuid4(), uuid4()
    gateway = TransportAgentGateway(lambda _: None, agent_project=lambda _: other_project)
    with pytest.raises(DeliveryError, match="outside the message project"):
        gateway.publish_context_update(ContextUpdate(project_id=project_id, recipient_agent_id=recipient_id, source_event_id=event_id, subject="Blocked", content="Blocked", relevance_score=1))


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
        def post(self, endpoint, json, headers=None):
            calls.append((endpoint, json, headers))
            return Response()

    WebhookAgentTransport("https://relay.example/deliver", access_token="relay-token", client=Client()).deliver({"type": "agent_message"})
    assert calls == [("https://relay.example/deliver", {"type": "agent_message"}, {"Authorization": "Bearer relay-token"})]


def test_relay_environment_configures_a_tenant_scoped_gateway(monkeypatch):
    container = build_container()
    seed_demo(container.repository)
    platform = PlatformStore()
    project_team = uuid4()
    platform.project_teams[DEMO_IDS["project"]] = project_team
    monkeypatch.setenv("AGENT_RELAY_URL", "https://relay.example/deliver")
    monkeypatch.setenv("AGENT_RELAY_AUTH_TOKEN", "relay-token")
    gateway = gateway_from_environment(container.repository, platform)
    assert isinstance(gateway, TransportAgentGateway)
    assert gateway.transport.endpoint == "https://relay.example/deliver"
    assert gateway.transport.access_token == "relay-token"
    assert gateway.project_team(DEMO_IDS["project"]) == project_team


def test_webhook_transport_retries_and_reports_a_failed_delivery():
    class Client:
        def __init__(self): self.calls = 0
        def post(self, endpoint, json, headers=None):
            self.calls += 1
            raise httpx.ConnectError("relay unavailable")

    client = Client()
    transport = WebhookAgentTransport("https://relay.example/deliver", max_attempts=3, client=client, sleep=lambda _: None)
    with pytest.raises(DeliveryError):
        transport.deliver({"type": "agent_message", "project_id": "project", "team_id": "team"})
    assert client.calls == 3
    assert transport.metrics.failed == 1 and transport.metrics.retried == 2
