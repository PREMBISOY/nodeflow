"""Apply NodeFlow SQL migrations once per production database."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to run migrations")
    engine = create_engine(database_url, pool_pre_ping=True)
    migration_dir = Path("/app/migrations")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS nodeflow_schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"))
        for path in sorted(migration_dir.glob("*.sql")):
            applied = connection.execute(text("SELECT 1 FROM nodeflow_schema_migrations WHERE name = :name"), {"name": path.name}).first()
            if applied:
                continue
            connection.exec_driver_sql(path.read_text(encoding="utf-8"))
            connection.execute(text("INSERT INTO nodeflow_schema_migrations (name) VALUES (:name)"), {"name": path.name})
            print(f"Applied migration: {path.name}")


if __name__ == "__main__":
    main()
