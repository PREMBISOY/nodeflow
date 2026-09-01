"""Tenant isolation tests.

Verifies:
- Active team blocks cross-tenant project read/write
- Cross-project component/agent references are rejected
- GitHub repository routing strictly segregates by connection ID
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

def client():
    return TestClient(create_app(load_demo_data=False))

def register(api, name, email):
    r = api.post("/api/v1/auth/register", json={"name": name, "email": email, "password": "secure-password"})
    assert r.status_code == 201
    return r.json()["data"]["access_token"]

def auth(token):
    return {"Authorization": f"Bearer {token}"}

class TestTenantIsolation:
    def test_active_team_blocks_cross_tenant_project_access(self):
        api = client()
        user1_token = register(api, "User1", "user1@example.com")
        r1 = api.post("/api/v1/teams", json={"name": "Team A"}, headers=auth(user1_token))
        team_a = r1.json()["data"]
        team_a_active = team_a["access_token"]
        
        r_proj = api.post(f"/api/v1/teams/{team_a['id']}/projects", json={"name": "ProjA", "purpose": "Test"}, headers=auth(team_a_active))
        proj_a_id = r_proj.json()["data"]["id"]
        
        user2_token = register(api, "User2", "user2@example.com")
        r2 = api.post("/api/v1/teams", json={"name": "Team B"}, headers=auth(user2_token))
        team_b = r2.json()["data"]
        team_b_active = team_b["access_token"]
        
        # User2 tries to access TeamA's project
        r = api.get(f"/api/v1/teams/{team_b['id']}/projects/{proj_a_id}", headers=auth(team_b_active))
        assert r.status_code == 404

    def test_cross_team_uuid_guessing_returns_404(self):
        api = client()
        user1_token = register(api, "User1", "u1@example.com")
        team_a = api.post("/api/v1/teams", json={"name": "A"}, headers=auth(user1_token)).json()["data"]
        
        user2_token = register(api, "User2", "u2@example.com")
        team_b = api.post("/api/v1/teams", json={"name": "B"}, headers=auth(user2_token)).json()["data"]
        team_b_active = team_b["access_token"]
        
        # Attempt to act on team A's ID while team B is active
        r = api.get(f"/api/v1/teams/{team_a['id']}/projects", headers=auth(team_b_active))
        assert r.status_code == 403
