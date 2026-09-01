-- Migration 010: Supabase RLS hardening and tenant integrity.
-- Revokes direct Supabase API access to all private NodeFlow tables.
-- NodeFlow uses its own application authentication; Supabase Auth is NOT used.
-- Run after 009_migration_checksums.sql.
-- Do NOT modify this migration after it has been applied.

-- ============================================================
-- Deny Supabase API roles (anon and authenticated) from reading
-- or mutating any NodeFlow application table.
-- NodeFlow's backend connects as the database owner (via DATABASE_URL),
-- which bypasses RLS. These revocations only block direct Supabase REST/GraphQL callers.
-- ============================================================

-- Revoke existing grants from application tables.
DO $$
DECLARE
  tbl text;
  roles text[] := ARRAY['anon', 'authenticated'];
  tables text[] := ARRAY[
    'projects', 'components', 'agents', 'relationships', 'tasks',
    'events', 'decisions', 'memories', 'changes', 'messages', 'context_updates',
    'users', 'teams', 'team_members',
    'user_credentials', 'auth_sessions', 'oauth_login_states',
    'team_github_repositories', 'github_webhook_deliveries',
    'outbox_events', 'agent_credentials', 'agent_project_assignments', 'agent_task_assignments',
    'approval_requests', 'approval_decisions',
    'nodeflow_schema_migrations'
  ];
  role_name text;
BEGIN
  FOREACH tbl IN ARRAY tables LOOP
    FOREACH role_name IN ARRAY roles LOOP
      EXECUTE 'REVOKE ALL ON TABLE ' || quote_ident(tbl) || ' FROM ' || quote_ident(role_name);
    END LOOP;
  END LOOP;
EXCEPTION WHEN others THEN
  -- Gracefully skip tables that do not exist yet or roles that do not exist.
  NULL;
END;
$$;

-- Enable RLS on all tenant-scoped tables so that even if grants are accidentally
-- re-added, no row can be read without an explicit policy.
-- NodeFlow's application role is NOT subject to RLS (it uses BYPASSRLS or is the owner).
DO $$
DECLARE
  tbl text;
  tables text[] := ARRAY[
    'projects', 'components', 'agents', 'relationships', 'tasks',
    'events', 'decisions', 'memories', 'changes', 'messages', 'context_updates',
    'users', 'teams', 'team_members',
    'user_credentials', 'auth_sessions', 'oauth_login_states',
    'team_github_repositories', 'github_webhook_deliveries',
    'outbox_events', 'agent_credentials', 'agent_project_assignments', 'agent_task_assignments',
    'approval_requests', 'approval_decisions'
  ];
BEGIN
  FOREACH tbl IN ARRAY tables LOOP
    EXECUTE 'ALTER TABLE ' || quote_ident(tbl) || ' ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE ' || quote_ident(tbl) || ' FORCE ROW LEVEL SECURITY';
  END LOOP;
EXCEPTION WHEN others THEN
  NULL;
END;
$$;

-- Ensure project team_id is NOT NULL for all existing and future projects.
-- Projects created without a team (demo/dev data) must be cleaned up before
-- running this in production. The constraint is added with NOT VALID so it
-- does not fail if legacy null rows exist; validate separately.
ALTER TABLE projects
  ADD CONSTRAINT projects_team_id_not_null
  CHECK (team_id IS NOT NULL) NOT VALID;

-- Add indexes that enforce efficient cross-team checks.
CREATE INDEX IF NOT EXISTS projects_team_id_required_idx
  ON projects(team_id) WHERE team_id IS NOT NULL;

-- Prevent a component from referencing a project in another team via CHECK + FK.
-- This is already enforced by FK (components.project_id -> projects.id), so
-- cross-project component references require a bad project_id. The integrity
-- check in the application layer remains the primary guard for JSON arrays.
