from __future__ import annotations

from typing import Protocol

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
