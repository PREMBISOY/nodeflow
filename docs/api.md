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
| GET | `/api/v1/projects/{id}/collaboration` | Human–AI–AI–Human timeline, agents, notifications, and waiting approvals |
| GET | `/api/v1/agents/{id}/context?scope=related&task_id={taskId}` | Scoped, optionally task-aware agent context |
| GET | `/api/v1/agents/{id}/updates` | Relevant propagated updates |
| POST | `/api/v1/events` | Record and process an event/change |
| POST | `/api/v1/integrations/github/events` | Ingest a thin GitHub commit, PR, or branch event |
| POST | `/api/v1/agents/{id}/messages` | Send and record an agent message |
| POST | `/api/v1/onboarding` | Generate a role-specific briefing |

Event ingestion accepts an optional nested `change`. When present, NodeFlow analyzes the graph and propagates only to agents whose deterministic relevance score meets the threshold.

Impact responses include `affected_component_distances`, where each UUID maps to its dependency-hop distance from the changed component. Propagated updates include a rounded `relevance_score` from `0.00` to `1.00` and a human-readable explanation of why the recipient needs the change.

`task_id` is optional. When supplied, its components are added to the assembled context and the selected task is returned as `requested_task`. This supports an agent beginning a newly assigned task without exposing an unrelated project-wide context.

Standalone state-of-the-world, living-architecture, decision-memory, and project-memory routes are intentionally not implemented here because those features are outside Prem's ownership. Their data may still be consumed through the Project Brain repository boundary when needed for Prem-owned reasoning and onboarding.

## GitHub event ingestion

GitHub remains the source of truth for source code. NodeFlow stores a compact event containing the repository, ref/commit or PR metadata, and changed paths; it does not mirror repositories. Components opt into path mapping through `path:<prefix>` tags supplied by the persistence layer. The first mapped component drives existing impact analysis, while all mapped components remain attached to the event.

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

## Frontend collaboration requirements

Build the collaboration panel from `GET /projects/{id}/collaboration`: render the ordered `timeline` as who initiated work and what changed, `agents` as active role/model work, `notifications` as propagation count, and `waiting` as the human-action queue. A timeline item can declare `requires_approval`; show this as a clear approve/reject state, not an implicit agent action. Empty lists mean no current activity or no pending human action; API errors use the standard response envelope.
