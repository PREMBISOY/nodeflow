"""Centralized RBAC policy for the NodeFlow platform.

All permission checks go through this module. Routes must not scatter role
comparisons inline; they call :func:`Policy.require` or :func:`Policy.check`.

Role hierarchy (from most to least privileged):
  OWNER > ADMIN > MEMBER

Permission matrix
-----------------
Action                        OWNER  ADMIN  MEMBER
transfer_ownership              ✓      ✗      ✗
change_member_role              ✓      ✗      ✗
remove_member                   ✓      ✓*     ✗
rotate_join_code                ✓      ✓      ✗
read_join_code                  ✓      ✓      ✗
create_project                  ✓      ✓      ✗
archive_project                 ✓      ✓      ✗
connect_integration             ✓      ✓      ✗
disconnect_integration          ✓      ✓      ✗
manage_member                   ✓      ✓      ✗
read_project                    ✓      ✓      ✓
post_event                      ✓      ✓      ✓
send_message                    ✓      ✓      ✓
read_team                       ✓      ✓      ✓

*ADMIN cannot remove or demote another ADMIN or the last OWNER.
"""

from __future__ import annotations

from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Permission sets
# ---------------------------------------------------------------------------

_OWNER_ONLY: frozenset[str] = frozenset({
    "transfer_ownership",
    "change_member_role",
})

_ADMIN_PLUS: frozenset[str] = frozenset({
    "remove_member",
    "rotate_join_code",
    "read_join_code",
    "create_project",
    "archive_project",
    "connect_integration",
    "disconnect_integration",
    "manage_member",
    "update_project",
})

_MEMBER_PLUS: frozenset[str] = frozenset({
    "read_project",
    "post_event",
    "send_message",
    "read_team",
    "list_projects",
    "read_component",
    "read_task",
    "read_agent",
    "read_decision",
    "read_memory",
    "read_event",
    "read_approval",
    "create_approval_request",
})

_ALL_ACTIONS: frozenset[str] = _OWNER_ONLY | _ADMIN_PLUS | _MEMBER_PLUS


class Policy:
    """Centralized authorization service.

    Usage::

        Policy.require(membership, "create_project")
        Policy.require(membership, "remove_member", target_role="ADMIN")
    """

    @staticmethod
    def role_level(role: str) -> int:
        """Return numeric level for role comparison (higher = more privilege)."""
        return {"OWNER": 3, "ADMIN": 2, "MEMBER": 1}.get(role.upper(), 0)

    @staticmethod
    def check(role: str, action: str, target_role: str | None = None) -> bool:
        """Return True if *role* is permitted to perform *action*.

        When *target_role* is provided (e.g. for ``remove_member``), the policy
        also ensures an ADMIN cannot act on another ADMIN or any OWNER.
        """
        role_upper = role.upper()
        if action not in _ALL_ACTIONS:
            return False

        if action in _OWNER_ONLY:
            return role_upper == "OWNER"

        if action in _ADMIN_PLUS:
            if role_upper not in ("OWNER", "ADMIN"):
                return False
            # ADMIN cannot act on a member whose role >= their own
            if target_role is not None and role_upper == "ADMIN":
                if Policy.role_level(target_role) >= Policy.role_level("ADMIN"):
                    return False
            return True

        if action in _MEMBER_PLUS:
            return role_upper in ("OWNER", "ADMIN", "MEMBER")

        return False

    @staticmethod
    def require(
        role: str,
        action: str,
        target_role: str | None = None,
        *,
        http_status: int = 403,
    ) -> None:
        """Assert that *role* is permitted to perform *action*.

        Raises :class:`fastapi.HTTPException` with ``http_status`` when denied.
        Uses 403 by default; callers may pass 404 when revealing the target's
        existence would be a security concern.
        """
        if not Policy.check(role, action, target_role):
            codes = {403: "FORBIDDEN", 404: "NOT_FOUND"}
            code = codes.get(http_status, "FORBIDDEN")
            raise HTTPException(
                status_code=http_status,
                detail={
                    "code": code,
                    "message": "You do not have permission to perform this action",
                },
            )

    @staticmethod
    def require_owner(role: str) -> None:
        """Shorthand: require OWNER role."""
        Policy.require(role, "transfer_ownership")

    @staticmethod
    def require_admin_plus(role: str) -> None:
        """Shorthand: require OWNER or ADMIN role."""
        Policy.require(role, "create_project")
