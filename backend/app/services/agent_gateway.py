from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import time
from typing import Any, Protocol
from uuid import UUID

import httpx

from app.models import ContextUpdate, Message


logger = logging.getLogger(__name__)


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


class DeliveryError(RuntimeError):
    """Raised only after a relay exhausts its configured delivery attempts."""


@dataclass
class DeliveryMetrics:
    attempted: int = 0
    delivered: int = 0
    failed: int = 0
    retried: int = 0


class WebhookAgentTransport:
    """Posts provider-neutral envelopes to a NodeFlow-managed relay endpoint."""

    def __init__(self, endpoint: str, access_token: str | None = None, max_attempts: int = 3,
                 retry_delay_seconds: float = 0.25, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.endpoint = endpoint
        self.access_token = access_token
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.client = client or httpx.Client(timeout=10)
        self.sleep = sleep
        self.metrics = DeliveryMetrics()

    def deliver(self, envelope: dict[str, Any]) -> None:
        self.metrics.attempted += 1
        headers = {"Authorization": f"Bearer {access_token}"} if (access_token := self.access_token) else None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.post(self.endpoint, json=envelope, headers=headers)
                response.raise_for_status()
                self.metrics.delivered += 1
                logger.info("agent_relay_delivery_succeeded", extra={"attempt": attempt, "type": envelope.get("type"), "project_id": envelope.get("project_id"), "team_id": envelope.get("team_id")})
                return
            except httpx.HTTPError as exc:
                if attempt == self.max_attempts:
                    self.metrics.failed += 1
                    logger.error("agent_relay_delivery_failed", extra={"attempts": attempt, "type": envelope.get("type"), "project_id": envelope.get("project_id"), "team_id": envelope.get("team_id")}, exc_info=exc)
                    raise DeliveryError("Agent relay delivery failed") from exc
                self.metrics.retried += 1
                logger.warning("agent_relay_delivery_retry", extra={"attempt": attempt, "type": envelope.get("type"), "project_id": envelope.get("project_id"), "team_id": envelope.get("team_id")})
                self.sleep(self.retry_delay_seconds * attempt)


class TransportAgentGateway:
    """Adapts core updates and messages to a configured NodeFlow transport.

    The adapter does not call model providers or connect agents directly. It emits
    generic envelopes to a transport selected by deployment code (for example, a
    local bridge, websocket hub, or webhook relay).
    """

    def __init__(self, transport: AgentTransport | Callable[[dict[str, Any]], None],
                 agent_project: Callable[[UUID], UUID] | None = None,
                 project_team: Callable[[UUID], UUID] | None = None) -> None:
        self.transport = transport
        self.agent_project = agent_project
        self.project_team = project_team

    def _deliver(self, envelope: dict[str, Any]) -> None:
        if callable(self.transport):
            self.transport(envelope)
        else:
            self.transport.deliver(envelope)

    def publish_context_update(self, update: ContextUpdate) -> None:
        self._deliver(self._envelope("context_update", update.project_id, update.recipient_agent_id, update.model_dump(mode="json")))

    def send_message(self, message: Message) -> None:
        self._deliver(self._envelope("agent_message", message.project_id, message.recipient_agent_id, message.model_dump(mode="json")))

    def _envelope(self, event_type: str, project_id: UUID, recipient_agent_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        if self.agent_project and self.agent_project(recipient_agent_id) != project_id:
            raise DeliveryError("Recipient agent is outside the message project")
        envelope = {
            "type": event_type,
            "project_id": str(project_id),
            "recipient_agent_id": str(recipient_agent_id),
            "payload": payload,
        }
        if self.project_team:
            envelope["team_id"] = str(self.project_team(project_id))
        return envelope
