# Database Migration Handoff

Prem, the migration pipeline has been hardened to run securely in production against the Supabase instance.

## Why this is required
Because of tight permissions, only you (Prem) have direct Supabase CLI access to run production schema changes. This doc explains the automated guardrails now protecting that process.

## Safe Migration Strategy
NodeFlow now uses a strict advisory lock and checksum strategy:
- `pg_try_advisory_lock` prevents concurrent Railway containers from racing to apply migrations on startup.
- SHA-256 checksums are stored for every applied migration. 
- If an already-applied migration file is modified, the migration runner will **hard fail on startup** to prevent schema corruption.
- Every migration is wrapped in its own transactional savepoint. If a failure occurs, only the failed migration rolls back and it will record the exact `failure_reason` in the `nodeflow_schema_migrations` tracking table.

## The Migrations

These five new migrations complete the Core Intelligence hardening (006 - 010):

| File | Purpose |
|------|---------|
| `006_outbox_and_delivery.sql` | Transactional outbox for Agent Gateway events to prevent dual-write failure. |
| `007_github_connection_hardening.sql` | Adds specific connection UUIDs and idempotent delivery tracking. |
| `008_approval_state.sql` | Hardened approval decisions with UNIQUE constraint on decisions vs requests. |
| `009_migration_checksums.sql` | Extends the migrations table with `checksum` and timestamps. |
| `010_rls_and_tenant_integrity.sql` | Revokes public access, enforces Row Level Security, and checks `projects.team_id`. |

### Important Execution Notes

1. **Do not modify 001 - 005.** They have been locked into the system.
2. The migration runner uses `DATABASE_URL`. Ensure this contains the `postgres://` connection string.
3. You can verify the current migration state via `python -m app.migrate --status`.

## Verification SQL

To verify the migrations ran successfully on Supabase, use the following SQL:
```sql
SELECT name, applied_at, checksum, started_at, completed_at
FROM nodeflow_schema_migrations 
ORDER BY name;
```

All 10 migrations should show a checksum and a `completed_at` timestamp.
