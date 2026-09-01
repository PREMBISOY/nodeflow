from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.models import ContextUpdate, Message


class AgentGateway(Protocol):
    def publish_context_update(self, update: ContextUpdate) -> None: ...
    def send_message(self, message: Message) -> None: ...


class RecordingAgentGateway:
    """Demo gateway that records deliveries for easy replacement by Sunal's gateway."""

    def __init__(self) -> None:
        self.published_updates: list[ContextUpdate] = []
        self.sent_messages: list[Message] = []

    def publish_context_update(self, update: ContextUpdate) -> None:
        self.published_updates.append(update)

    def send_message(self, message: Message) -> None:
        self.sent_messages.append(message)


class AgentTransport(Protocol):
    """Provider-neutral delivery boundary owned by the NodeFlow gateway."""

    def deliver(self, envelope: dict[str, Any]) -> None: ...


class WebhookAgentTransport:
    """Posts provider-neutral envelopes to a NodeFlow-managed relay endpoint."""

    def __init__(self, endpoint: str, client: httpx.Client | None = None) -> None:
        self.endpoint = endpoint
        self.client = client or httpx.Client(timeout=10)

    def deliver(self, envelope: dict[str, Any]) -> None:
        response = self.client.post(self.endpoint, json=envelope)
        response.raise_for_status()


class TransportAgentGateway:
    """Adapts core updates and messages to a configured NodeFlow transport.

    The adapter does not call model providers or connect agents directly. It emits
    generic envelopes to a transport selected by deployment code (for example, a
    local bridge, websocket hub, or webhook relay).
    """

    def __init__(self, transport: AgentTransport | Callable[[dict[str, Any]], None]) -> None:
        self.transport = transport

    def _deliver(self, envelope: dict[str, Any]) -> None:
        if callable(self.transport):
            self.transport(envelope)
        else:
            self.transport.deliver(envelope)

    def publish_context_update(self, update: ContextUpdate) -> None:
        self._deliver({
            "type": "context_update",
            "recipient_agent_id": str(update.recipient_agent_id),
            "payload": update.model_dump(mode="json"),
        })

    def send_message(self, message: Message) -> None:
        self._deliver({
            "type": "agent_message",
            "recipient_agent_id": str(message.recipient_agent_id),
            "payload": message.model_dump(mode="json"),
        })
