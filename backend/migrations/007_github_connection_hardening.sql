-- Migration 007: GitHub connection hardening.
-- Adds immutable GitHub repo ID, per-connection secrets, and delivery deduplication.
-- Run after 006_outbox_and_delivery.sql.
-- Do NOT modify this migration after it has been applied.

-- Add immutable GitHub repository ID and per-connection security fields.
ALTER TABLE team_github_repositories
  ADD COLUMN IF NOT EXISTS github_repo_id bigint,
  ADD COLUMN IF NOT EXISTS installation_id bigint,
  ADD COLUMN IF NOT EXISTS connection_secret_hash text,
  ADD COLUMN IF NOT EXISTS health_status varchar(40) NOT NULL DEFAULT 'unknown'
    CHECK (health_status IN ('unknown', 'healthy', 'degraded', 'disconnected')),
  ADD COLUMN IF NOT EXISTS last_synced_at timestamptz,
  ADD COLUMN IF NOT EXISTS disconnected_at timestamptz;

-- Unique index on the immutable GitHub repo ID (allows same repo connected by multiple teams).
CREATE INDEX IF NOT EXISTS team_github_repositories_repo_id_idx
  ON team_github_repositories(github_repo_id)
  WHERE github_repo_id IS NOT NULL;

-- Webhook deliveries: records every X-GitHub-Delivery header for idempotency.
CREATE TABLE IF NOT EXISTS github_webhook_deliveries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  connection_id uuid REFERENCES team_github_repositories(id) ON DELETE SET NULL,
  team_id uuid REFERENCES teams(id) ON DELETE SET NULL,
  project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
  github_delivery_id text NOT NULL UNIQUE,
  event_name varchar(80) NOT NULL,
  action varchar(80),
  payload_hash text,
  status varchar(40) NOT NULL DEFAULT 'received'
    CHECK (status IN ('received', 'processed', 'ignored', 'failed')),
  failure_reason text,
  received_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz
);

CREATE INDEX IF NOT EXISTS github_webhook_deliveries_connection_idx
  ON github_webhook_deliveries(connection_id, received_at DESC)
  WHERE connection_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS github_webhook_deliveries_project_idx
  ON github_webhook_deliveries(project_id, received_at DESC)
  WHERE project_id IS NOT NULL;
