"""RBAC tests — every role/action combination.

Verifies:
- OWNER can perform all actions
- ADMIN cannot perform OWNER-only actions (transfer_ownership, change_member_role)
- MEMBER cannot perform admin actions
- Last owner cannot be removed or demoted
- Join codes are not exposed in /me or /teams
- Join codes are only available via the /join-code endpoint to OWNER/ADMIN
- Role enforcement on project create and GitHub connect
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.auth.policy import Policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def client():
    return TestClient(create_app(load_demo_data=False))


def register(api, name, email, password="secure-password"):
    r = api.post("/api/v1/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, f"Register failed: {r.text}"
    return r.json()["data"]["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_team_as(api, token, name="TestTeam"):
    r = api.post("/api/v1/teams", json={"name": name}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["data"]


def join_team(api, token, code):
    r = api.post("/api/v1/teams/join", json={"team_code": code}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def team_token(api, token, team_id):
    r = api.post("/api/v1/me/active-team", json={"team_id": team_id}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


# ---------------------------------------------------------------------------
# Policy unit tests (no HTTP)
# ---------------------------------------------------------------------------

class TestPolicyMatrix:
    def test_owner_can_transfer_ownership(self):
        assert Policy.check("OWNER", "transfer_ownership") is True

    def test_admin_cannot_transfer_ownership(self):
        assert Policy.check("ADMIN", "transfer_ownership") is False

    def test_member_cannot_transfer_ownership(self):
        assert Policy.check("MEMBER", "transfer_ownership") is False

    def test_owner_can_change_member_role(self):
        assert Policy.check("OWNER", "change_member_role", "MEMBER") is True
        assert Policy.check("OWNER", "change_member_role", "ADMIN") is True

    def test_admin_cannot_change_member_role(self):
        assert Policy.check("ADMIN", "change_member_role", "MEMBER") is False

    def test_admin_cannot_remove_admin(self):
        assert Policy.check("ADMIN", "remove_member", "ADMIN") is False

    def test_admin_cannot_remove_owner(self):
        assert Policy.check("ADMIN", "remove_member", "OWNER") is False

    def test_admin_can_remove_member(self):
        assert Policy.check("ADMIN", "remove_member", "MEMBER") is True

    def test_owner_can_remove_anyone(self):
        assert Policy.check("OWNER", "remove_member", "ADMIN") is True
        assert Policy.check("OWNER", "remove_member", "MEMBER") is True

    def test_member_cannot_create_project(self):
        assert Policy.check("MEMBER", "create_project") is False

    def test_admin_can_create_project(self):
        assert Policy.check("ADMIN", "create_project") is True

    def test_member_can_read_project(self):
        assert Policy.check("MEMBER", "read_project") is True

    def test_member_can_post_event(self):
        assert Policy.check("MEMBER", "post_event") is True

    def test_member_cannot_connect_integration(self):
        assert Policy.check("MEMBER", "connect_integration") is False

    def test_admin_can_rotate_join_code(self):
        assert Policy.check("ADMIN", "rotate_join_code") is True

    def test_member_cannot_rotate_join_code(self):
        assert Policy.check("MEMBER", "rotate_join_code") is False


# ---------------------------------------------------------------------------
# HTTP-level RBAC tests
# ---------------------------------------------------------------------------

class TestRBACEndpoints:
    def _setup(self):
        api = client()
        owner_token = register(api, "Owner", "owner@rbac.com")
        admin_token = register(api, "Admin", "admin@rbac.com")
        member_token = register(api, "Member", "member@rbac.com")
        team_data = create_team_as(api, owner_token, "RBACTeam")
        team_id = team_data["id"]
        join_code = team_data["team_code"]

        # Admin and member join the team
        join_team(api, admin_token, join_code)
        join_team(api, member_token, join_code)

        # Get user IDs from members endpoint
        owner_active = team_data["access_token"]
        members_r = api.get(f"/api/v1/teams/{team_id}/members", headers=auth(owner_active))
        members = members_r.json()["data"]
        admin_user_id = next(m["user_id"] for m in members if m["role"] == "MEMBER"
                             and m["user_id"] != members[0]["user_id"]  # first MEMBER entry
                             )
        # Elevate admin user to ADMIN
        api.patch(
            f"/api/v1/teams/{team_id}/members/{admin_user_id}",
            json={"role": "ADMIN"}, headers=auth(owner_active),
        )

        return api, team_id, join_code, owner_active, team_token(api, admin_token, team_id), team_token(api, member_token, team_id)

    def test_member_cannot_create_project(self):
        api = client()
        owner_token = register(api, "O", "o@m.com")
        team_data = create_team_as(api, owner_token, "T")
        team_id = team_data["id"]
        member_token = register(api, "M", "m@m.com")
        join_team(api, member_token, team_data["team_code"])
        member_active = team_token(api, member_token, team_id)
        r = api.post(
            f"/api/v1/teams/{team_id}/projects",
            json={"name": "P", "purpose": "X"},
            headers=auth(member_active),
        )
        assert r.status_code == 403

    def test_admin_can_create_project(self):
        api = client()
        owner_token = register(api, "O2", "o2@m.com")
        team_data = create_team_as(api, owner_token, "T2")
        team_id = team_data["id"]
        admin_token = register(api, "A2", "a2@m.com")
        join_team(api, admin_token, team_data["team_code"])
        owner_active = team_data["access_token"]

        # Get admin user ID and elevate
        members_r = api.get(f"/api/v1/teams/{team_id}/members", headers=auth(owner_active))
        admin_user_id = next(m["user_id"] for m in members_r.json()["data"] if m["role"] == "MEMBER")
        api.patch(f"/api/v1/teams/{team_id}/members/{admin_user_id}", json={"role": "ADMIN"}, headers=auth(owner_active))

        admin_active = team_token(api, admin_token, team_id)
        r = api.post(
            f"/api/v1/teams/{team_id}/projects",
            json={"name": "AdminProject", "purpose": "Test"},
            headers=auth(admin_active),
        )
        assert r.status_code == 201

    def test_join_code_not_in_team_list(self):
        api = client()
        owner_token = register(api, "O3", "o3@m.com")
        team_data = create_team_as(api, owner_token, "T3")
        team_id = team_data["id"]

        # /teams list should not include team_code
        r = api.get("/api/v1/teams", headers=auth(owner_token))
        assert r.status_code == 200
        for t in r.json()["data"]:
            assert "team_code" not in t

    def test_join_code_not_in_me(self):
        api = client()
        owner_token = register(api, "O4", "o4@m.com")
        create_team_as(api, owner_token, "T4")
        r = api.get("/api/v1/me", headers=auth(owner_token))
        assert r.status_code == 200
        for t in r.json()["data"]["teams"]:
            assert "team_code" not in t

    def test_owner_can_read_join_code(self):
        api = client()
        owner_token = register(api, "O5", "o5@m.com")
        team_data = create_team_as(api, owner_token, "T5")
        team_id = team_data["id"]
        r = api.get(f"/api/v1/teams/{team_id}/join-code", headers=auth(team_data["access_token"]))
        assert r.status_code == 200
        assert "team_code" in r.json()["data"]

    def test_member_cannot_read_join_code(self):
        api = client()
        owner_token = register(api, "O6", "o6@m.com")
        team_data = create_team_as(api, owner_token, "T6")
        team_id = team_data["id"]
        member_token = register(api, "M6", "m6@m.com")
        member_data = join_team(api, member_token, team_data["team_code"])
        member_active = team_token(api, member_token, team_id)
        r = api.get(f"/api/v1/teams/{team_id}/join-code", headers=auth(member_active))
        assert r.status_code == 403

    def test_cannot_remove_last_owner(self):
        api = client()
        owner_token = register(api, "O7", "o7@m.com")
        team_data = create_team_as(api, owner_token, "T7")
        team_id = team_data["id"]
        owner_active = team_data["access_token"]
        members = api.get(f"/api/v1/teams/{team_id}/members", headers=auth(owner_active)).json()["data"]
        owner_id = next(m["user_id"] for m in members if m["role"] == "OWNER")
        r = api.delete(f"/api/v1/teams/{team_id}/members/{owner_id}", headers=auth(owner_active))
        # Should fail — cannot remove last owner
        assert r.status_code in (409, 403)

    def test_rotate_join_code_changes_code(self):
        api = client()
        owner_token = register(api, "O8", "o8@m.com")
        team_data = create_team_as(api, owner_token, "T8")
        team_id = team_data["id"]
        old_code = team_data["team_code"]
        r = api.post(f"/api/v1/teams/{team_id}/join-code/rotate", headers=auth(team_data["access_token"]))
        assert r.status_code == 200
        new_code = r.json()["data"]["team_code"]
        assert new_code != old_code
        # Old code no longer works
        other_token = register(api, "O9", "o9@m.com")
        r2 = api.post("/api/v1/teams/join", json={"team_code": old_code}, headers=auth(other_token))
        assert r2.status_code == 404

    def test_transfer_ownership_changes_roles(self):
        api = client()
        owner_token = register(api, "OA", "oa@m.com")
        team_data = create_team_as(api, owner_token, "TA")
        team_id = team_data["id"]
        new_owner_token = register(api, "OB", "ob@m.com")
        join_team(api, new_owner_token, team_data["team_code"])
        owner_active = team_data["access_token"]
        members = api.get(f"/api/v1/teams/{team_id}/members", headers=auth(owner_active)).json()["data"]
        new_owner_id = next(m["user_id"] for m in members if m["role"] == "MEMBER")
        r = api.post(f"/api/v1/teams/{team_id}/transfer-ownership", json={"new_owner_id": new_owner_id}, headers=auth(owner_active))
        assert r.status_code == 200
        updated = api.get(f"/api/v1/teams/{team_id}/members", headers=auth(owner_active)).json()["data"]
        new_owner_role = next(m["role"] for m in updated if m["user_id"] == new_owner_id)
        assert new_owner_role == "OWNER"
