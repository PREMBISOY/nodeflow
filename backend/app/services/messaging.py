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
        if not sender.active:
            raise ValueError("Inactive agents cannot send messages")
        if not recipient.active:
            raise ValueError("Messages cannot be sent to an inactive agent")
        project_component_ids = {
            component.id for component in self.repository.list_components(sender.project_id)
        }
        related_component_ids = list(dict.fromkeys(request.related_components))
        invalid_component_ids = [
            component_id
            for component_id in related_component_ids
            if component_id not in project_component_ids
        ]
        if invalid_component_ids:
            raise ValueError(
                f"Related component '{invalid_component_ids[0]}' does not belong to the agents' project"
            )
        message = Message(
            project_id=sender.project_id,
            sender_agent_id=sender.id,
            recipient_agent_id=recipient.id,
            message_type=request.message_type,
            subject=request.subject,
            content=request.content,
            related_component_ids=related_component_ids,
        )
        self.repository.add_message(message)
        self.repository.add_event(
            Event(
                project_id=sender.project_id,
                event_type="agent_message",
                actor_type="agent",
                actor_id=sender.id,
                entity_id=message.id,
                component_ids=related_component_ids,
                summary=f"{sender.name} messaged {recipient.name}: {request.subject}",
                payload={"message_type": request.message_type, "recipient_agent_id": str(recipient.id)},
            )
        )
        self.gateway.send_message(message)
        return message
