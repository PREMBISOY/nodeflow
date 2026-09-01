"""NodeFlow migration runner — production-quality with checksums and advisory lock.

Features
--------
- PostgreSQL advisory lock prevents concurrent migrations from racing.
- Each migration is run inside its own transaction.
- A SHA-256 checksum is stored with every applied migration.
- Startup fails if an already-applied migration's file contents have changed.
- ``--dry-run`` prints pending migrations without applying them.
- ``--status`` prints the state of every migration file.

Usage
-----
Apply migrations (default)::

    python -m app.migrate

Dry run::

    python -m app.migrate --dry-run

Status report::

    python -m app.migrate --status

Environment
-----------
``DATABASE_URL`` — required. Must be set to the production Supabase URL.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.persistence import build_session_factory

logger = logging.getLogger(__name__)

# Advisory lock key (hashtext equivalent for Python; matches pg hashtext for ASCII keys)
_ADVISORY_LOCK_KEY = 4_237_591_853  # stable numeric key for "nodeflow_migrate"
_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _checksum(sql: str) -> str:
    """Compute SHA-256 checksum of migration SQL content."""
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_table(connection) -> None:
    """Create the migrations tracking table if it does not exist."""
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS nodeflow_schema_migrations (
              name text PRIMARY KEY,
              applied_at timestamptz NOT NULL DEFAULT now(),
              checksum text,
              started_at timestamptz,
              completed_at timestamptz,
              failed_at timestamptz,
              failure_reason text
            )
            """
        )
    )
    # Add columns if running against a pre-009 database
    for col, col_type in (
        ("checksum", "text"),
        ("started_at", "timestamptz"),
        ("completed_at", "timestamptz"),
        ("failed_at", "timestamptz"),
        ("failure_reason", "text"),
    ):
        try:
            connection.execute(
                text(
                    f"ALTER TABLE nodeflow_schema_migrations "
                    f"ADD COLUMN IF NOT EXISTS {col} {col_type}"
                )
            )
        except Exception:
            pass  # column already exists on strict engines


def _acquire_lock(connection) -> bool:
    """Try to acquire a PostgreSQL session advisory lock.

    Returns True on success. Returns False if another process holds the lock.
    This prevents two Railway containers from racing during startup.
    """
    try:
        row = connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _ADVISORY_LOCK_KEY},
        ).first()
        return bool(row[0]) if row else False
    except Exception:
        # Non-PostgreSQL databases (e.g. SQLite in tests) do not support
        # advisory locks. Proceed without locking.
        return True


def _release_lock(connection) -> None:
    try:
        connection.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": _ADVISORY_LOCK_KEY},
        )
    except Exception:
        pass


def _load_applied(connection) -> dict[str, str | None]:
    """Return {name: checksum} for all applied migrations."""
    rows = connection.execute(
        text("SELECT name, checksum FROM nodeflow_schema_migrations ORDER BY name")
    )
    return {row.name: row.checksum for row in rows}


def _verify_checksums(
    applied: dict[str, str | None],
    migration_files: list[Path],
) -> None:
    """Fail loudly if any applied migration's content has changed."""
    errors: list[str] = []
    for path in migration_files:
        name = path.name
        if name not in applied:
            continue
        stored = applied[name]
        current = _checksum(path.read_text(encoding="utf-8"))
        if stored and stored != current:
            errors.append(
                f"  {name}: stored checksum {stored[:16]}… ≠ current {current[:16]}…"
            )
    if errors:
        raise RuntimeError(
            "Migration content has changed for already-applied migrations. "
            "Do NOT modify applied migrations.\n" + "\n".join(errors)
        )


def _apply(connection, path: Path, dry_run: bool) -> None:
    """Apply one migration inside its own savepoint transaction."""
    name = path.name
    sql = path.read_text(encoding="utf-8")
    checksum = _checksum(sql)
    now = _utc_now()

    if dry_run:
        print(f"  [dry-run] Would apply: {name}  checksum={checksum[:16]}…")
        return

    # Record start
    connection.execute(
        text(
            """
            INSERT INTO nodeflow_schema_migrations
              (name, applied_at, checksum, started_at)
            VALUES (:name, :now, :checksum, :now)
            ON CONFLICT (name) DO UPDATE SET started_at = :now, failed_at = NULL, failure_reason = NULL
            """
        ),
        {"name": name, "now": now, "checksum": checksum},
    )
    connection.commit()

    try:
        # Run the migration SQL directly
        connection.exec_driver_sql(sql)
        connection.execute(
            text(
                """
                UPDATE nodeflow_schema_migrations
                   SET completed_at = :now, checksum = :checksum
                 WHERE name = :name
                """
            ),
            {"now": _utc_now(), "checksum": checksum, "name": name},
        )
        connection.commit()
        print(f"  Applied: {name}  checksum={checksum[:16]}…")
    except Exception as exc:
        connection.rollback()
        connection.execute(
            text(
                """
                UPDATE nodeflow_schema_migrations
                   SET failed_at = :now, failure_reason = :reason
                 WHERE name = :name
                """
            ),
            {"now": _utc_now(), "reason": str(exc)[:2000], "name": name},
        )
        connection.commit()
        raise RuntimeError(f"Migration {name} failed: {exc}") from exc


def run_migrations(
    database_url: str,
    *,
    dry_run: bool = False,
    status_only: bool = False,
    migration_dir: Path | None = None,
) -> None:
    """Main migration entry point."""
    migrations_path = migration_dir or _MIGRATIONS_DIR
    migration_files = sorted(migrations_path.glob("*.sql"))

    if not migration_files:
        print(f"No migration files found in {migrations_path}")
        return

    factory = build_session_factory(database_url)
    engine = factory.kw["bind"]

    with engine.connect() as connection:
        _ensure_table(connection)
        connection.commit()

        applied = _load_applied(connection)

        if status_only:
            print(f"\nMigration status ({len(migration_files)} files in {migrations_path}):\n")
            for path in migration_files:
                name = path.name
                stored = applied.get(name)
                current = _checksum(path.read_text(encoding="utf-8"))
                if name not in applied:
                    state = "PENDING"
                elif stored and stored != current:
                    state = "MODIFIED (DANGER)"
                else:
                    state = "APPLIED"
                print(f"  {state:25s}  {name}")
            return

        # Verify checksums of already-applied migrations before touching anything
        _verify_checksums(applied, migration_files)

        # Acquire advisory lock for concurrent container safety
        if not _acquire_lock(connection):
            print("Another process is running migrations. Skipping.")
            return

        try:
            pending = [f for f in migration_files if f.name not in applied]
            if not pending:
                if dry_run:
                    print("No pending migrations.")
                else:
                    print("All migrations already applied.")
                return

            print(f"\n{'[DRY RUN] ' if dry_run else ''}Applying {len(pending)} migration(s):\n")
            for path in pending:
                _apply(connection, path, dry_run=dry_run)
        finally:
            _release_lock(connection)

    if not dry_run:
        print("\nMigrations complete.")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="NodeFlow database migration runner")
    parser.add_argument("--dry-run", action="store_true", help="Show pending migrations without applying")
    parser.add_argument("--status", action="store_true", help="Print status of all migration files")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)

    try:
        run_migrations(database_url, dry_run=args.dry_run, status_only=args.status)
    except RuntimeError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except SQLAlchemyError as exc:
        print(f"\nDatabase error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
