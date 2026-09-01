"""Transactional outbox service.

The outbox provides Sunal's delivery transport with a clean repository/service
interface. Outbox records are written in the same transaction as the domain
operation they represent. Sunal's gateway claims and delivers them separately.

Usage (within a request-scoped session transaction)::

    outbox.enqueue(
        session=db,
        team_id=team_id,
        project_id=project_id,
        destination="agent-gateway",
        event_type="context_update",
        payload=update.model_dump(mode="json"),
        idempotency_key=f"ctx:{update.id}",
    )
    # The record is flushed but NOT committed here.
    # The request-scoped unit-of-work commits everything atomically.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OutboxRepository:
    """Low-level outbox repository used by the application layer."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        *,
        team_id: UUID,
        project_id: UUID | None,
        destination: str,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        available_at: datetime | None = None,
    ) -> None:
        """Insert an outbox record.

        Called within the same database transaction as the domain write.
        Uses INSERT … ON CONFLICT DO NOTHING for idempotency: if the same
        (idempotency_key, destination) pair is enqueued twice, the second
        call silently succeeds without creating a duplicate.
        """
        import json

        self.session.execute(
            text(
                """
                INSERT INTO outbox_events
                  (team_id, project_id, destination, event_type, payload,
                   idempotency_key, available_at)
                VALUES
                  (:team, :project, :dest, :etype, :payload,
                   :idem_key, :available)
                ON CONFLICT (idempotency_key, destination) DO NOTHING
                """
            ),
            {
                "team": str(team_id),
                "project": str(project_id) if project_id else None,
                "dest": destination,
                "etype": event_type,
                "payload": json.dumps(payload),
                "idem_key": idempotency_key,
                "available": available_at or utc_now(),
            },
        )

    def claim_pending(self, limit: int = 50) -> list[dict[str, Any]]:
        """Atomically claim up to *limit* pending outbox records for delivery.

        Sets status to ``delivering`` so concurrent claims do not overlap.
        Returns the claimed records. Sunal's transport must mark each as
        ``delivered`` or ``failed`` by calling :meth:`mark_delivered` /
        :meth:`mark_failed`.
        """
        import json

        rows = self.session.execute(
            text(
                """
                UPDATE outbox_events
                   SET status = 'delivering',
                       attempt_count = attempt_count + 1,
                       updated_at = now()
                 WHERE id IN (
                   SELECT id FROM outbox_events
                    WHERE status = 'pending'
                      AND available_at <= now()
                    ORDER BY available_at
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                 )
                RETURNING id, team_id, project_id, destination, event_type,
                          payload, idempotency_key, attempt_count, available_at,
                          created_at
                """
            ),
            {"limit": limit},
        )
        return [
            {
                "id": str(row.id),
                "team_id": str(row.team_id),
                "project_id": str(row.project_id) if row.project_id else None,
                "destination": row.destination,
                "event_type": row.event_type,
                "payload": row.payload if isinstance(row.payload, dict) else json.loads(row.payload),
                "idempotency_key": row.idempotency_key,
                "attempt_count": row.attempt_count,
                "available_at": row.available_at.isoformat() if row.available_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    def mark_delivered(self, record_id: str) -> None:
        """Mark an outbox record as delivered."""
        self.session.execute(
            text(
                """
                UPDATE outbox_events
                   SET status = 'delivered',
                       delivered_at = now(),
                       updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": record_id},
        )

    def mark_failed(self, record_id: str, error: str, retry_after_seconds: int = 60) -> None:
        """Mark an outbox record as failed and schedule a retry."""
        self.session.execute(
            text(
                """
                UPDATE outbox_events
                   SET status = 'pending',
                       last_error = :error,
                       available_at = now() + (:retry * interval '1 second'),
                       updated_at = now()
                 WHERE id = :id
                   AND attempt_count < 10
                """
            ),
            {"id": record_id, "error": error[:2000], "retry": retry_after_seconds},
        )
        # Permanently fail after 10 attempts
        self.session.execute(
            text(
                """
                UPDATE outbox_events
                   SET status = 'failed',
                       last_error = :error,
                       updated_at = now()
                 WHERE id = :id
                   AND attempt_count >= 10
                """
            ),
            {"id": record_id, "error": error[:2000]},
        )

    def backlog_count(self) -> int:
        """Return the number of pending outbox records (for metrics/health)."""
        row = self.session.execute(
            text("SELECT count(*) FROM outbox_events WHERE status = 'pending'")
        ).first()
        return int(row[0]) if row else 0
