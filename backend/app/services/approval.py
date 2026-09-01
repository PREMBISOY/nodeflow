"""Durable approval persistence service.

Namish owns approval workflow semantics; Aayush owns persistence and
concurrency safety. This module provides the storage layer.

Concurrency safety
------------------
``approval_decisions`` has a UNIQUE constraint on ``approval_request_id``.
Two concurrent threads that attempt to INSERT a decision for the same request
will produce a database IntegrityError on the second INSERT, which is caught
and translated to a clear application error.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:
    """Persist approval requests and concurrency-safe decisions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_request(
        self,
        *,
        project_id: UUID,
        team_id: UUID,
        title: str,
        description: str | None = None,
        source_event_id: UUID | None = None,
    ) -> dict:
        """Create a new approval request.

        Returns the created record as a plain dict compatible with the
        collaboration event format Namish and Prem consume.
        """
        request_id = uuid4()
        now = utc_now()
        self.session.execute(
            text(
                """
                INSERT INTO approval_requests
                  (id, project_id, team_id, source_event_id, title, description,
                   status, created_at, updated_at)
                VALUES
                  (:id, :project, :team, :event, :title, :desc,
                   'waiting_approval', :now, :now)
                """
            ),
            {
                "id": str(request_id),
                "project": str(project_id),
                "team": str(team_id),
                "event": str(source_event_id) if source_event_id else None,
                "title": title,
                "desc": description,
                "now": now,
            },
        )
        return {
            "id": str(request_id),
            "project_id": str(project_id),
            "team_id": str(team_id),
            "source_event_id": str(source_event_id) if source_event_id else None,
            "title": title,
            "description": description,
            "status": "waiting_approval",
            "created_at": now.isoformat(),
        }

    def make_decision(
        self,
        *,
        approval_request_id: UUID,
        project_id: UUID,
        decision: str,
        actor_name: str,
        comment: str | None = None,
    ) -> dict:
        """Record an approve or reject decision.

        Raises ``ValueError`` if the request does not exist, belongs to a
        different project, or already has a final decision.
        The UNIQUE constraint on ``approval_decisions.approval_request_id``
        prevents two concurrent INSERTs from both succeeding.
        """
        if decision not in ("approved", "rejected"):
            raise ValueError("Decision must be 'approved' or 'rejected'")

        # Verify ownership and current status
        row = self.session.execute(
            text(
                """
                SELECT id, status FROM approval_requests
                 WHERE id = :id AND project_id = :project
                """
            ),
            {"id": str(approval_request_id), "project": str(project_id)},
        ).first()
        if row is None:
            raise LookupError(f"ApprovalRequest '{approval_request_id}' was not found")
        if row.status != "waiting_approval":
            raise ValueError(
                f"Approval request already has a final decision: {row.status}"
            )

        decision_id = uuid4()
        now = utc_now()
        try:
            self.session.execute(
                text(
                    """
                    INSERT INTO approval_decisions
                      (id, approval_request_id, decision, actor_name, comment, decided_at)
                    VALUES
                      (:id, :request, :decision, :actor, :comment, :now)
                    """
                ),
                {
                    "id": str(decision_id),
                    "request": str(approval_request_id),
                    "decision": decision,
                    "actor": actor_name,
                    "comment": comment,
                    "now": now,
                },
            )
            # Update the parent request status
            self.session.execute(
                text(
                    """
                    UPDATE approval_requests
                       SET status = :status, updated_at = :now
                     WHERE id = :id
                    """
                ),
                {"status": decision, "now": now, "id": str(approval_request_id)},
            )
        except IntegrityError:
            self.session.rollback()
            raise ValueError(
                "A decision has already been recorded for this approval request"
            )

        return {
            "id": str(decision_id),
            "approval_request_id": str(approval_request_id),
            "decision": decision,
            "actor_name": actor_name,
            "comment": comment,
            "decided_at": now.isoformat(),
        }

    def get_request(self, *, approval_request_id: UUID, project_id: UUID) -> dict:
        """Fetch an approval request with its decision (if any)."""
        row = self.session.execute(
            text(
                """
                SELECT ar.id, ar.project_id, ar.team_id, ar.source_event_id,
                       ar.title, ar.description, ar.status, ar.created_at, ar.updated_at,
                       ad.decision, ad.actor_name, ad.comment, ad.decided_at
                  FROM approval_requests ar
             LEFT JOIN approval_decisions ad ON ad.approval_request_id = ar.id
                 WHERE ar.id = :id AND ar.project_id = :project
                """
            ),
            {"id": str(approval_request_id), "project": str(project_id)},
        ).first()
        if row is None:
            raise LookupError(f"ApprovalRequest '{approval_request_id}' was not found")
        return {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "status": row.status,
            "title": row.title,
            "description": row.description,
            "source_event_id": str(row.source_event_id) if row.source_event_id else None,
            "created_at": row.created_at.isoformat() if hasattr(row.created_at, 'isoformat') else str(row.created_at) if row.created_at else None,
            "decision": {
                "decision": row.decision,
                "actor_name": row.actor_name,
                "comment": row.comment,
                "decided_at": row.decided_at.isoformat() if hasattr(row.decided_at, 'isoformat') else str(row.decided_at) if row.decided_at else None,
            } if row.decision else None,
        }

    def list_requests(
        self,
        *,
        project_id: UUID,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> list[dict]:
        """List approval requests for a project, newest first."""
        query = """
            SELECT ar.id, ar.project_id, ar.source_event_id, ar.title,
                   ar.description, ar.status, ar.created_at, ar.updated_at,
                   ad.decision, ad.actor_name, ad.comment, ad.decided_at
              FROM approval_requests ar
         LEFT JOIN approval_decisions ad ON ad.approval_request_id = ar.id
             WHERE ar.project_id = :project
        """
        params: dict = {"project": str(project_id), "limit": min(limit, 200)}
        if status:
            query += " AND ar.status = :status"
            params["status"] = status
        if cursor:
            query += " AND ar.id < :cursor"
            params["cursor"] = cursor
        query += " ORDER BY ar.created_at DESC LIMIT :limit"

        rows = self.session.execute(text(query), params)
        return [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "status": row.status,
                "title": row.title,
                "description": row.description,
                "source_event_id": str(row.source_event_id) if row.source_event_id else None,
                "created_at": row.created_at.isoformat() if hasattr(row.created_at, 'isoformat') else str(row.created_at) if row.created_at else None,
                "decision": {
                    "decision": row.decision,
                    "actor_name": row.actor_name,
                    "comment": row.comment,
                    "decided_at": row.decided_at.isoformat() if hasattr(row.decided_at, 'isoformat') else str(row.decided_at) if row.decided_at else None,
                } if row.decision else None,
            }
            for row in rows
        ]
