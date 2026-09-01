# Golden Demo

The development server loads stable UUIDs from `backend/app/core/demo_data.py`.

- Project: `10000000-0000-0000-0000-000000000001`
- Recommendations API: `20000000-0000-0000-0000-000000000002`
- Backend agent: `30000000-0000-0000-0000-000000000001`
- Frontend agent: `30000000-0000-0000-0000-000000000002`
- ML agent: `30000000-0000-0000-0000-000000000003`
- Marketing agent: `30000000-0000-0000-0000-000000000004`

Post an `api_changed` event with a nested change for the Recommendations API. The graph identifies Frontend and ML Service, then sends updates to the frontend and ML agents. The unrelated marketing agent gets no update.

### Git-to-collaboration story

1. Connect the repository name `PREMBISOY/nodeflow` in the host integration.
2. Send a `commit` event to `/api/v1/integrations/github/events` with `backend/...` files. The demo's `path:backend` mapping resolves those files to Recommendations API.
3. NodeFlow records `github_commit`, runs the existing impact analysis, and notifies only the frontend and ML agents.
4. Send the frontend agent's acknowledgement through `/api/v1/agents/{id}/messages`.
5. Read `/api/v1/projects/{id}/collaboration` to show the human initiator, Git change, participating agents, notification count, and any approval waiting.
6. For a new frontend teammate, call `/api/v1/onboarding` with role `Frontend Engineer` and scope `related`; their briefing contains Frontend, the API contract, relevant task, decision, and recent change.

The frontend agent can acknowledge with `POST /api/v1/agents/{frontend-agent-id}/messages`; the message becomes an `agent_message` event in Project Brain history.

Finally, post this onboarding request:

```json
{
  "project_id": "10000000-0000-0000-0000-000000000001",
  "name": "Rahul",
  "role": "Frontend Engineer",
  "scope": "related",
  "question": "Explain this project to me."
}
```

The briefing includes frontend-owned work plus the related Recommendations API, relevant decisions, and recent API changes.
