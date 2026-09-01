# NodeFlow data contracts

`backend/app/models/entities.py` is the shared Pydantic contract. `backend/app/db.py` maps it to PostgreSQL/Supabase tables, and `SqlAlchemyProjectRepository` is the only persistence interface application services should use. Roles, messages, and context updates are durable first-class records.

The `relationships` table is polymorphic: `source_entity_id`, `target_entity_id`, and `relationship_type` model component dependencies plus task ownership and decision impact without arbitrary dependency strings. Event rows are append-only application records; replay `GET /api/v1/events?before=<UTC timestamp>` to reconstruct a historical view.

Context scopes (`my_work`, `team`, `related`, `project`) are retrieval filters. `AccessControlService` decides whether a user can read a resource; it intentionally does not decide relevance. Grant `project:read`, a resource-specific permission, or `admin` to permit a read. Material component events create durable context updates for agents with assigned affected work; delivery remains a pluggable Agent Infrastructure responsibility.

`GET /api/v1/projects/{id}/state/at?timestamp=<UTC>` replays the append-only event timeline into a lightweight historical state summary. This deliberately avoids a full event-sourcing framework.

Run `backend/migrations/001_initial_postgres.sql` in Supabase before setting `DATABASE_URL`. With no `DATABASE_URL`, the API intentionally uses deterministic in-memory golden data for local demos.
