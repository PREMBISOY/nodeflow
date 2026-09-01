# Collaboration UI Contract

This is Namish's handoff to the frontend/visualization owner. It specifies product behavior only; it does not prescribe a dashboard layout or replace the visualization system.

## Data sources

| User need | API | Required fields |
|---|---|---|
| See the Project Brain | `GET /api/v1/projects/{id}/context` | project, components, relationships, tasks, agents, recent_events, decisions, recent_changes |
| Understand the work chain | `GET /api/v1/projects/{id}/collaboration` | timeline, agents, notifications, waiting, summary |
| Prepare an agent for work | `GET /api/v1/agents/{id}/context?scope={scope}&task_id={taskId}` | requested_task, components, tasks, decisions, memories, recent_events |
| See delivered impact | `GET /api/v1/agents/{id}/updates` | subject, content, related_component_ids, relevance_score, read |
| Let an agent acknowledge work | `POST /api/v1/agents/{id}/messages` | recipient_agent_id, message_type, subject, content, related_components |
| Brief a new member | `POST /api/v1/onboarding` | role, major_components, relevant_tasks, recent_changes, briefing |

All APIs use `{ success, data, error }`. Show a recoverable error state whenever `success` is false or a request fails.

## Required collaboration states

1. **Project overview** — components, dependency edges, current task count, active agent count, and recent changes.
2. **Work chain** — ordered timeline showing initiator, change/event, components affected, agents involved, and timestamps. Do not imply a human actor where `actor_name` is null.
3. **Agent activity** — agent name, role, active state, current task IDs, and notification count. Agent model/provider belongs to Project Brain context if shown.
4. **Context handoff** — a scope selector (`my_work`, `team`, `related`, `project`) and optional task selection. Display the returned `requested_task` separately from the broader task list.
5. **Human attention** — render `waiting` items as pending information only. `waiting_approval` must not show an approve/reject control until an approval mutation API is delivered by the workflow/persistence integration.
6. **Onboarding** — role selection, scope selection, briefing, recommended starting points, and relevant architecture/tasks/changes.

## Empty, loading, and error behavior

- Loading: preserve page structure with non-interactive placeholders; do not display stale agents as active.
- No timeline: say “No collaboration events yet.”
- No notifications: say “No agent updates are waiting.”
- No waiting items: say “Nothing requires human attention.”
- No role match during onboarding: use the API's fallback project overview and clearly label it as broad project context.
- Error: display `error.message`, retain any last successful read-only data with a timestamp, and offer retry. Do not fabricate project state.

## Interaction rules

- Selecting a timeline component may focus the existing architecture visualization using its UUID; dependency direction is `source_component_id depends_on target_component_id`.
- Selecting an agent opens its context at `related` scope by default. Selecting a task adds `task_id` to produce a deliberate task handoff.
- Sending an acknowledgement is explicit user/agent action and uses the messages endpoint; optimistically render only after the server accepts it.
- Poll/refetch collaboration state after sending a message or ingesting a new project event. Delivery/read semantics remain owned by the agent gateway and persistence adapters.

## Non-goals and integration dependencies

- The UI must not infer permissions, mutate task status, approve work, or create graph edges. Those require contracts from the permissions, persistence, and workflow owners.
- GitHub authentication, webhook registration, signature validation, and repository synchronization belong to the external integration layer. The current product API accepts normalized GitHub events only.
- The dashboard's graph rendering remains with the frontend/visualization owner; this contract supplies the interaction and state requirements.
