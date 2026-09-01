from uuid import uuid4

from app.models import ContextUpdate, Message
from app.services.agent_gateway import TransportAgentGateway


def test_transport_gateway_emits_provider_neutral_envelopes():
    received = []
    project_id, recipient_id, event_id, sender_id = uuid4(), uuid4(), uuid4(), uuid4()
    gateway = TransportAgentGateway(received.append)
    gateway.publish_context_update(ContextUpdate(project_id=project_id, recipient_agent_id=recipient_id, source_event_id=event_id, subject="API changed", content="Review integration.", relevance_score=0.8))
    gateway.send_message(Message(project_id=project_id, sender_agent_id=sender_id, recipient_agent_id=recipient_id, message_type="context_update", subject="Backend update", content="Endpoint is ready."))
    assert [item["type"] for item in received] == ["context_update", "agent_message"]
    assert all(item["recipient_agent_id"] == str(recipient_id) for item in received)
