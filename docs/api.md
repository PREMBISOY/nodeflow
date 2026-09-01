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
| GET | `/api/v1/agents/{id}/context?scope=related` | Scoped agent context |
| GET | `/api/v1/agents/{id}/updates` | Relevant propagated updates |
| POST | `/api/v1/events` | Record and process an event/change |
| POST | `/api/v1/agents/{id}/messages` | Send and record an agent message |
| POST | `/api/v1/onboarding` | Generate a role-specific briefing |

Event ingestion accepts an optional nested `change`. When present, NodeFlow analyzes the graph and propagates only to agents whose deterministic relevance score meets the threshold.

Standalone state-of-the-world, living-architecture, decision-memory, and project-memory routes are intentionally not implemented here because those features are outside Prem's ownership. Their data may still be consumed through the Project Brain repository boundary when needed for Prem-owned reasoning and onboarding.
