"""Provider-neutral client for NodeFlow's authenticated shared API."""
import os

import httpx


class NodeFlowClient:
    def __init__(self, base_url: str | None = None, access_token: str | None = None,
                 client: httpx.Client | None = None):
        self.base_url = (base_url or os.getenv("NODEFLOW_API_URL") or "").rstrip("/")
        if not self.base_url:
            raise ValueError("Set NODEFLOW_API_URL or pass base_url for the shared NodeFlow deployment.")
        token = access_token or os.getenv("NODEFLOW_ACCESS_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self.client = client or httpx.Client(base_url=self.base_url, timeout=15, headers=headers)

    def _request(self, method: str, path: str, **kwargs):
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        body = response.json()
        if not body["success"]:
            raise RuntimeError(body["error"]["message"])
        return body["data"]

    def context(self, agent_id: str, scope: str = "related"):
        return self._request("GET", f"/api/v1/agents/{agent_id}/context", params={"scope": scope})

    def updates(self, agent_id: str):
        return self._request("GET", f"/api/v1/agents/{agent_id}/updates")

    def event(self, project_id: str, agent_id: str, event_type: str, summary: str, **kwargs):
        return self._request("POST", "/api/v1/events", json={"project_id": project_id, "event_type": event_type, "actor_type": "agent", "actor_id": agent_id, "summary": summary, **kwargs})

    def message(self, sender_agent_id: str, recipient_agent_id: str, subject: str, content: str, **kwargs):
        return self._request("POST", f"/api/v1/agents/{sender_agent_id}/messages", json={"recipient_agent_id": recipient_agent_id, "subject": subject, "content": content, **kwargs})
