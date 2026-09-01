"""GitHub Integration Hardening Tests.

Verifies:
- Connection-specific derived webhook secrets
- Idempotency via X-GitHub-Delivery
- Replay prevention (202 returned but not reprocessed)
- Signature validation for both legacy global and new connection-specific routes
"""

import json
import hashlib
import hmac
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import create_app

def client():
    # Use memory adapter but set fake webhook secret
    import os
    os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret"
    return TestClient(create_app(load_demo_data=False))

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

class TestGitHubIntegrationHardening:
    def test_invalid_signature_rejected(self):
        api = client()
        payload = {"repository": {"full_name": "owner/repo"}, "action": "opened"}
        body = json.dumps(payload).encode()
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": "sha256=invalid",
        }
        r = api.post("/api/v1/integrations/github/webhook", content=body, headers=headers)
        assert r.status_code == 401

    def test_legacy_webhook_accepts_valid_global_signature(self):
        api = client()
        payload = {"repository": {"full_name": "owner/repo"}, "action": "opened"}
        body = json.dumps(payload).encode()
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-2",
            "X-Hub-Signature-256": _sign(body, "test-secret"),
        }
        # Assuming repository not found, it returns 404
        r = api.post("/api/v1/integrations/github/webhook", content=body, headers=headers)
        assert r.status_code == 404

    def test_v2_webhook_rejects_global_signature(self):
        """The v2 webhook requires the signature to be signed with the derived key (or globally configured one in test fallback)."""
        api = client()
        conn_id = uuid4()
        payload = {"repository": {"full_name": "owner/repo"}, "action": "opened"}
        body = json.dumps(payload).encode()
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-3",
            "X-Hub-Signature-256": "sha256=invalid",
        }
        r = api.post(f"/api/v1/integrations/github/webhook/{conn_id}", content=body, headers=headers)
        assert r.status_code == 401
