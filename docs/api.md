# Core Intelligence API

FastAPI publishes the complete OpenAPI document at `/openapi.json` and interactive documentation at `/docs`.

All success responses are:

```json
{"success": true, "data": {}, "error": null}
```

All handled failures are:

```json
{"success": false, "data": null, "error": {"code": "ERROR_CODE", "message": "Readable message"}}
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/projects/{id}` | Project metadata |
| GET | `/api/v1/projects/{id}/context` | Structured Project Brain context |
| GET | `/api/v1/projects/{id}/state` | Current project state summary |
| GET | `/api/v1/projects/{id}/architecture` | Components and dependency relationships |
| GET | `/api/v1/projects/{id}/components/{componentId}/context` | One-hop component context |
| GET | `/api/v1/projects/{id}/decisions` | Project decisions |
| GET | `/api/v1/projects/{id}/memory?query={query}` | Ranked project-memory retrieval |
| GET | `/api/v1/projects/{id}/collaboration` | Human–AI–AI–Human timeline, agents, notifications, and waiting approvals |
| POST | `/api/v1/projects/{id}/collaboration/approvals/{eventId}` | Record an explicit human approval or rejection |
| GET | `/api/v1/agents/{id}/context?scope=related&task_id={taskId}` | Scoped, optionally task-aware agent context |
| GET | `/api/v1/agents/{id}/updates` | Relevant propagated updates |
| POST | `/api/v1/events` | Record and process an event/change |
| POST | `/api/v1/integrations/github/events` | Ingest a thin GitHub commit, PR, or branch event |
| GET | `/api/v1/projects/{id}/git/activity` | Git event activity normalized for product flows |
| POST | `/api/v1/agents/{id}/messages` | Send and record an agent message |
| POST | `/api/v1/onboarding` | Generate a role-specific briefing |
| GET | `/api/v1/teams/{teamId}/members` | List the active team's participant name, user ID, and role |
| POST | `/api/v1/teams/{teamId}/members` | Add an existing account to a team (team creator only) |
| DELETE | `/api/v1/teams/{teamId}/members/{userId}` | Remove a participant (team creator only) |
| GET | `/health/live` | Process liveness |
| GET | `/health/ready` | Database-aware readiness |

Event ingestion accepts an optional nested `change`. When present, NodeFlow analyzes the graph and propagates only to agents whose deterministic relevance score meets the threshold.

Event ingestion also accepts `changes`, an array using the same change shape. This is used for commits that touch independent components. The compatibility `impact` field contains the first analysis, while `impacts` contains every analysis; each relevant agent receives at most one consolidated context update.

Impact responses include `affected_component_distances`, where each UUID maps to its dependency-hop distance from the changed component. Propagated updates include a rounded `relevance_score` from `0.00` to `1.00` and a human-readable explanation of why the recipient needs the change.

`task_id` is optional. When supplied, its components are added to the assembled context and the selected task is returned as `requested_task`. This supports a deliberate task handoff without turning a focused request into an unrelated project-wide context dump.

State, architecture, decision, and memory endpoints are read-only Project Brain views. Their persistence and mutation contracts remain owned by the data/platform layer.

## GitHub event ingestion

GitHub remains the source of truth for source code. NodeFlow stores a compact event containing the repository, ref/commit or PR metadata, and changed paths; it does not mirror repositories. Components opt into path mapping through `path:<prefix>` tags supplied by the persistence layer. Every mapped component receives an impact analysis, including independent components changed by the same commit.

```json
{
  "project_id": "10000000-0000-0000-0000-000000000001",
  "event_type": "commit",
  "repository": "PREMBISOY/nodeflow",
  "summary": "Add recommendations endpoint",
  "commit_sha": "abc123",
  "changed_files": ["backend/recommendations.py", "backend/routes.py"]
}
```

Pull-request events may include an `action`. `opened` and `synchronized` default to `review_required` and require approval unless `requires_approval` is explicitly set. A merged PR receives the `merged` flow stage. Read normalized history from `GET /projects/{id}/git/activity`.

## Active team scope

In production, every Project Brain, collaboration, Git, event, onboarding, and agent workflow request is authorized from the session's active team. A caller can access a project only when they are a member of that team and the project belongs to it. Team switching must clear selected project state before requesting a new project context.

Agent-authored events are accepted only when the actor exists in the same project. Event, change, and message component references are validated against the project before Prem's orchestration layer records history. Database constraints remain the persistence layer's additional enforcement boundary.

## Team participants

The person who creates a team is its leader (`OWNER`). Any team member can read
the participant list, which includes `id` (the user ID), `name`, and `role`.
Only that creator can add a registered NodeFlow account by email or remove a
participant. The creator cannot be removed, preserving a team leader.

## Error and request tracing

Handled FastAPI, authentication, authorization, validation, and Core Intelligence errors use the documented response envelope. Responses include `X-Request-ID`; clients may supply a bounded `X-Request-ID` for correlation. Unexpected failures return a generic `INTERNAL_ERROR` without exposing internal exception or database details.

## Approval workflow

`GET /projects/{id}/collaboration` returns `approvals` with a `waiting_approval`, `approved`, or `rejected` status. To make a decision, post an explicit human action:

```json
{
  "project_id": "10000000-0000-0000-0000-000000000001",
  "decision": "approved",
  "actor_name": "Prem",
  "comment": "API contract looks good."
}
```

The endpoint is append-only: it records a project event and rejects a second decision for the same approval. It deliberately does not mutate task state or execute a deployment.

## Frontend collaboration requirements

Build the collaboration panel from `GET /projects/{id}/collaboration`: render the ordered `timeline` as who initiated work and what changed, `agents` as active role/model work, `notifications` as propagation count, and `waiting` as the human-action queue. A timeline item can declare `requires_approval`; show this as a clear approve/reject state, not an implicit agent action. Empty lists mean no current activity or no pending human action; API errors use the standard response envelope.
