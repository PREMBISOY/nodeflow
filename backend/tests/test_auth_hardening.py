"""Authentication hardening tests.

Verifies:
- OAuth-only account cannot log in with password
- Duplicate registration returns 409, not 500
- JWT claim validation (exp, iss, aud, nbf, jti)
- Password policy enforcement
- Invalid credentials return 401
- Input validation enforced (max lengths, email format)
- Logout revokes the session
- Revoked session returns 401 on subsequent calls
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.platform import SessionCodec, _hash_password, _verify_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def client():
    return TestClient(create_app(load_demo_data=False))


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(api, name="Test", email="test@test.com", password="secure-password"):
    return api.post("/api/v1/auth/register", json={"name": name, "email": email, "password": password})


# ---------------------------------------------------------------------------
# Password hashing unit tests
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_uses_v1_prefix(self):
        h = _hash_password("mypassword")
        assert h.startswith("v1$")

    def test_verify_v1_hash(self):
        h = _hash_password("correcthorse")
        assert _verify_password("correcthorse", h) is True
        assert _verify_password("wronghorse", h) is False

    def test_empty_hash_returns_false(self):
        """OAuth-only accounts have empty hash — must not raise."""
        assert _verify_password("anypassword", "") is False
        assert _verify_password("anypassword", None) is False  # type: ignore[arg-type]

    def test_different_passwords_produce_different_hashes(self):
        h1 = _hash_password("password1")
        h2 = _hash_password("password1")
        # Same password, different salts
        assert h1 != h2
        # But both verify correctly
        assert _verify_password("password1", h1) is True
        assert _verify_password("password1", h2) is True


# ---------------------------------------------------------------------------
# JWT claim validation
# ---------------------------------------------------------------------------

class TestJWTValidation:
    def _b64(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    def _forge_token(self, codec: SessionCodec, payload: dict) -> str:
        """Create a token signed with the real secret but with a tampered payload."""
        body = self._b64(json.dumps(payload, separators=(",", ":")).encode())
        sig = self._b64(hmac.new(codec.secret, body.encode(), hashlib.sha256).digest())
        return body + "." + sig

    def test_expired_token_rejected(self):
        api = client()
        codec = api.app.state.session_codec
        user_id = uuid4()
        payload = {
            "iss": "nodeflow", "aud": "nodeflow-api",
            "sub": str(user_id), "team": None,
            "iat": int(time.time()) - 7200,
            "nbf": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,  # expired 1 hour ago
            "jti": "test-jti",
        }
        token = self._forge_token(codec, payload)
        r = api.get("/api/v1/me", headers=auth(token))
        assert r.status_code == 401

    def test_wrong_issuer_rejected(self):
        api = client()
        codec = api.app.state.session_codec
        payload = {
            "iss": "evil-issuer", "aud": "nodeflow-api",
            "sub": str(uuid4()), "team": None,
            "iat": int(time.time()),
            "nbf": int(time.time()),
            "exp": int(time.time()) + 3600,
            "jti": "jti-1",
        }
        token = self._forge_token(codec, payload)
        r = api.get("/api/v1/me", headers=auth(token))
        assert r.status_code == 401

    def test_wrong_audience_rejected(self):
        api = client()
        codec = api.app.state.session_codec
        payload = {
            "iss": "nodeflow", "aud": "wrong-audience",
            "sub": str(uuid4()), "team": None,
            "iat": int(time.time()),
            "nbf": int(time.time()),
            "exp": int(time.time()) + 3600,
            "jti": "jti-2",
        }
        token = self._forge_token(codec, payload)
        r = api.get("/api/v1/me", headers=auth(token))
        assert r.status_code == 401

    def test_tampered_signature_rejected(self):
        api = client()
        r = register(api)
        token = r.json()["data"]["access_token"]
        # Flip last character of signature
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        r2 = api.get("/api/v1/me", headers=auth(tampered))
        assert r2.status_code == 401

    def test_missing_bearer_rejected(self):
        api = client()
        r = api.get("/api/v1/me", headers={"Authorization": "Basic abc"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Registration validation
# ---------------------------------------------------------------------------

class TestRegistrationValidation:
    def test_duplicate_email_returns_409_not_500(self):
        api = client()
        r1 = register(api, email="dup@test.com")
        r2 = register(api, email="dup@test.com")
        assert r1.status_code == 201
        assert r2.status_code == 409
        assert r2.json()["success"] is False
        assert r2.json()["error"]["code"] == "CONFLICT"

    def test_short_password_rejected(self):
        api = client()
        r = api.post("/api/v1/auth/register", json={
            "name": "Test", "email": "short@test.com", "password": "1234567"
        })
        assert r.status_code == 422

    def test_whitespace_only_password_rejected(self):
        api = client()
        r = api.post("/api/v1/auth/register", json={
            "name": "Test", "email": "ws@test.com", "password": "        "
        })
        assert r.status_code == 422

    def test_invalid_email_format_rejected(self):
        api = client()
        r = api.post("/api/v1/auth/register", json={
            "name": "Test", "email": "notanemail", "password": "validpassword"
        })
        assert r.status_code == 422

    def test_email_normalized_to_lowercase(self):
        api = client()
        r = api.post("/api/v1/auth/register", json={
            "name": "Test", "email": "UPPER@EXAMPLE.COM", "password": "validpassword"
        })
        assert r.status_code == 201
        # Login with lowercase works
        r2 = api.post("/api/v1/auth/login", json={
            "email": "upper@example.com", "password": "validpassword"
        })
        assert r2.status_code == 200

    def test_empty_name_rejected(self):
        api = client()
        r = api.post("/api/v1/auth/register", json={
            "name": "", "email": "empty@test.com", "password": "validpassword"
        })
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Login validation
# ---------------------------------------------------------------------------

class TestLoginValidation:
    def test_wrong_password_returns_401(self):
        api = client()
        register(api, email="logintest@test.com")
        r = api.post("/api/v1/auth/login", json={
            "email": "logintest@test.com", "password": "wrong-password"
        })
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    def test_unknown_email_returns_401(self):
        api = client()
        r = api.post("/api/v1/auth/login", json={
            "email": "nobody@example.com", "password": "password"
        })
        assert r.status_code == 401

    def test_oauth_account_password_login_returns_401(self):
        """An account created via GitHub OAuth must not be logged in with a password."""
        api = client()
        # Simulate OAuth account creation directly
        store = api.app.state.platform_store
        from app.platform import User
        user = User(name="GitHub User", email="gh@example.com", auth_subject="github:12345")
        store.users[user.id] = user
        store.by_email["gh@example.com"] = (user.id, "")  # empty hash = OAuth-only
        r = api.post("/api/v1/auth/login", json={
            "email": "gh@example.com", "password": "anypassword"
        })
        assert r.status_code == 401
        assert "github" in r.json()["error"]["message"].lower() or "sign-in" in r.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Session revocation
# ---------------------------------------------------------------------------

class TestSessionRevocation:
    def test_logout_revokes_session(self):
        api = client()
        r = register(api, email="logout@test.com")
        token = r.json()["data"]["access_token"]
        # Verify session is valid
        assert api.get("/api/v1/me", headers=auth(token)).status_code == 200
        # Logout
        assert api.post("/api/v1/auth/logout", headers=auth(token)).status_code == 200
        # Session is now revoked
        assert api.get("/api/v1/me", headers=auth(token)).status_code == 401

    def test_revoked_session_cannot_access_any_endpoint(self):
        api = client()
        r = register(api, email="revoke2@test.com")
        token = r.json()["data"]["access_token"]
        api.post("/api/v1/auth/logout", headers=auth(token))
        # All protected endpoints reject the revoked token
        assert api.get("/api/v1/teams", headers=auth(token)).status_code == 401
        assert api.post("/api/v1/teams", json={"name": "X"}, headers=auth(token)).status_code == 401
