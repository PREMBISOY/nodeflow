from __future__ import annotations

from uuid import UUID

from app.models import Event, Message
from app.schemas.intelligence import MessageCreate
from app.services.agent_gateway import AgentGateway
from app.services.repository import ProjectKnowledgeRepository


class MessagingService:
    def __init__(self, repository: ProjectKnowledgeRepository, gateway: AgentGateway):
        self.repository = repository
        self.gateway = gateway

    def send(self, sender_agent_id: UUID, request: MessageCreate) -> Message:
        sender = self.repository.get_agent(sender_agent_id)
        recipient = self.repository.get_agent(request.recipient_agent_id)
        if sender.project_id != recipient.project_id:
            raise ValueError("Agents must belong to the same project")
        message = Message(
            project_id=sender.project_id,
            sender_agent_id=sender.id,
            recipient_agent_id=recipient.id,
            message_type=request.message_type,
            subject=request.subject,
            content=request.content,
            related_component_ids=request.related_components,
        )
        self.repository.add_message(message)
        self.repository.add_event(
            Event(
                project_id=sender.project_id,
                event_type="agent_message",
                actor_type="agent",
                actor_id=sender.id,
                entity_id=message.id,
                component_ids=request.related_components,
                summary=f"{sender.name} messaged {recipient.name}: {request.subject}",
                payload={"message_type": request.message_type, "recipient_agent_id": str(recipient.id)},
            )
        )
        self.gateway.send_message(message)
        return message
