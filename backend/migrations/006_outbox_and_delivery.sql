-- Migration 006: Transactional outbox, webhook delivery idempotency, and agent credentials.
-- Run after 005_oauth_login_states.sql.
-- Do NOT modify this migration after it has been applied.

-- Transactional outbox: written in the same transaction as the domain operation.
-- Sunal's delivery transport claims and delivers pending records.
CREATE TABLE IF NOT EXISTS outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
  destination text NOT NULL,
  event_type varchar(100) NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}',
  idempotency_key text NOT NULL,
  status varchar(40) NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'delivering', 'delivered', 'failed')),
  attempt_count int NOT NULL DEFAULT 0,
  available_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz,
  last_error text,
  UNIQUE (idempotency_key, destination)
);

CREATE INDEX IF NOT EXISTS outbox_events_status_idx
  ON outbox_events(status, available_at)
  WHERE status IN ('pending', 'delivering');

CREATE INDEX IF NOT EXISTS outbox_events_team_idx
  ON outbox_events(team_id, created_at DESC);

-- Agent credentials: gateway-consumable, never returned to API callers.
CREATE TABLE IF NOT EXISTS agent_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  credential_type varchar(80) NOT NULL,
  credential_hash text NOT NULL,
  label text,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  revoked_at timestamptz
);

CREATE INDEX IF NOT EXISTS agent_credentials_agent_idx
  ON agent_credentials(agent_id)
  WHERE revoked_at IS NULL;

-- Agent-project assignments (normalized; no longer relying on JSONB arrays only).
CREATE TABLE IF NOT EXISTS agent_project_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (agent_id, project_id)
);

-- Agent-task assignments (normalized).
CREATE TABLE IF NOT EXISTS agent_task_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (agent_id, task_id)
);
