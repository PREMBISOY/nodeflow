# Core Intelligence Integration Contracts

## Ownership boundary

Core Intelligence consumes project entities through `ProjectKnowledgeRepository` and publishes delivery requests through `AgentGateway`. It does not own PostgreSQL, agent registration, the external gateway, CLI, or frontend.

```text
HTTP event -> EventProcessor -> ChangeImpactAnalyzer -> RelevanceEngine
                                      |                    |
                               Project repository     ContextUpdate
                                                           |
                                                     AgentGateway
```

## Persistence integration (Aayush)

Implement the protocol in `backend/app/services/repository.py`. Database entities should map to the Pydantic contracts in `backend/app/models/entities.py`. UUIDs and UTC-aware timestamps are required. Replace the repository passed to `create_app`; no engine changes are needed.

The repository must provide structured project, component, relationship, task, agent, event, decision, memory, change, message, and context-update reads/writes. The bundled `InMemoryProjectRepository` is for the demo and tests only.

## Agent gateway integration (Sunal)

Implement `AgentGateway.publish_context_update` and `AgentGateway.send_message` in `backend/app/services/agent_gateway.py`, then inject that implementation into the container. Publishing is deliberately separate from persistence: updates/messages are recorded first and delivered second.

## Frontend integration (Aarya)

Use `GET /api/v1/projects/{id}/state`, `GET /api/v1/projects/{id}/architecture`, and agent context/update endpoints. All responses use `{success, data, error}`. Dependency relationship direction is `source_component_id depends_on target_component_id`.

## Product workflow integration (Namish)

Use `POST /api/v1/onboarding` with `role` and `scope`, and `POST /api/v1/agents/{id}/messages` for agent acknowledgements. Supported scopes are `my_work`, `team`, `related`, and `project`.

## Assumptions

- Permission checks happen upstream; this subsystem computes relevance after permission is granted.
- An agent's `component_ids` and `current_task_ids` are current and authoritative.
- Graph traversal is bidirectional to capture both dependencies and dependents, with a maximum impact distance of two.
- The external gateway provides retries and transport guarantees.
