# Agent Transport and Local Bridge

NodeFlow's core services own agent context, updates, and messages. The gateway adapter in `backend/app/services/agent_gateway.py` conforms to the existing `AgentGateway` interface and serializes `ContextUpdate` and `Message` entities as provider-neutral envelopes. Deployment code chooses the transport; no model-provider SDK or direct agent-to-agent dependency is introduced.

The gateway does not authenticate or authorize requests itself. It relies on the platform/auth layer to resolve the authenticated user, team membership, and permitted project before these routes execute. Agents, project IDs, and CLI configuration are identifiers—not authorization.

The local CLI and Python SDK require existing NodeFlow UUIDs. They use only the shared contracts:

| Operation | Contract |
| --- | --- |
| Context | `GET /api/v1/agents/{agent_id}/context` |
| Updates | `GET /api/v1/agents/{agent_id}/updates` |
| Activity | `POST /api/v1/events` |
| Message | `POST /api/v1/agents/{agent_id}/messages` |

## CLI

```powershell
$env:NODEFLOW_API_URL = "https://nodeflow-production.up.railway.app"
$env:NODEFLOW_ACCESS_TOKEN = "<platform-issued-token>"
python cli/nodeflow.py init
python cli/nodeflow.py connect --project PROJECT_UUID --agent AGENT_UUID
python cli/nodeflow.py context --scope related
python cli/nodeflow.py event --type CODE_CHANGED --summary "Updated recommendation API"
python cli/nodeflow.py message --to RECIPIENT_AGENT_UUID --subject "API update" --message "The endpoint is ready."
```

`connect` stores an existing project and agent identity locally; it does not create records or bypass the platform's ownership controls.

The SDK and CLI send `Authorization: Bearer <token>` only when `NODEFLOW_ACCESS_TOKEN` (or the equivalent configured token) is present. Tokens are obtained from the platform layer; the agent bridge neither creates nor validates them.

## Deployment injection

`create_app(gateway=TransportAgentGateway(transport))` injects the adapter without replacing the application bootstrap. `transport` may be an object implementing `deliver(envelope)` or a callable receiving the same generic envelope. `WebhookAgentTransport(endpoint)` is available for a NodeFlow-managed relay endpoint. The default remains the in-memory recorder used by the existing test/demo setup.

## Railway relay configuration

Set these Railway service variables to enable production delivery:

| Variable | Purpose |
| --- | --- |
| `AGENT_RELAY_URL` | NodeFlow-managed relay delivery endpoint. Enables the webhook transport. |
| `AGENT_RELAY_AUTH_TOKEN` | Optional bearer credential presented to the relay. |
| `AGENT_RELAY_MAX_ATTEMPTS` | Delivery attempts, default `3`. |
| `AGENT_RELAY_RETRY_DELAY_SECONDS` | Linear retry base delay, default `0.25`. |

For every delivery, the gateway resolves the recipient agent's project from the repository and rejects mismatches. It derives `team_id` from Aayush's authoritative project-to-team mapping and includes both `project_id` and `team_id` in the relay envelope. The relay must treat this scope as mandatory and must not route an envelope outside it. Failed attempts are logged as `agent_relay_delivery_retry` or `agent_relay_delivery_failed`; the webhook transport also exposes in-process `metrics` (`attempted`, `delivered`, `failed`, `retried`) for deployment monitoring.

## Railway authenticated smoke check

With a real platform-issued token scoped to the intended active team, run:

```powershell
$env:NODEFLOW_API_URL = "https://<your-railway-domain>"
$env:NODEFLOW_ACCESS_TOKEN = "<active-team-token>"
python cli/nodeflow.py init
python cli/nodeflow.py connect --project PROJECT_UUID --agent AGENT_UUID
python cli/nodeflow.py status
```

The equivalent SDK call is `NodeFlowClient().updates("AGENT_UUID")`. A `200` response verifies the deployed URL and bearer-token forwarding. A `404` for an agent/project from a different active team is the expected tenant-isolation result.
