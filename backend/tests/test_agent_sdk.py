import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent-sdk" / "python"))
from nodeflow_sdk import NodeFlowClient


def test_sdk_uses_configured_deployment_url_and_bearer_token():
    observed = {}

    def handler(request):
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"success": True, "data": [], "error": None})

    client = NodeFlowClient(
        base_url="https://nodeflow-production.up.railway.app",
        access_token="platform-token",
        client=httpx.Client(base_url="https://nodeflow-production.up.railway.app", headers={"Authorization": "Bearer platform-token"}, transport=httpx.MockTransport(handler)),
    )
    client.updates("00000000-0000-0000-0000-000000000001")
    assert observed == {
        "url": "https://nodeflow-production.up.railway.app/api/v1/agents/00000000-0000-0000-0000-000000000001/updates",
        "authorization": "Bearer platform-token",
    }
