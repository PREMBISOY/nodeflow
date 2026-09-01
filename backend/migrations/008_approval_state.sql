-- Migration 008: Durable approval state.
-- Replaces event-scan-based approval with a persistent, concurrency-safe model.
-- Run after 007_github_connection_hardening.sql.
-- Do NOT modify this migration after it has been applied.

-- Approval requests: one per agent-initiated action that requires human sign-off.
CREATE TABLE IF NOT EXISTS approval_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  source_event_id uuid REFERENCES events(id) ON DELETE SET NULL,
  title text NOT NULL,
  description text,
  status varchar(40) NOT NULL DEFAULT 'waiting_approval'
    CHECK (status IN ('waiting_approval', 'approved', 'rejected')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS approval_requests_project_idx
  ON approval_requests(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS approval_requests_status_idx
  ON approval_requests(project_id, status)
  WHERE status = 'waiting_approval';

-- Approval decisions: append-only, exactly one decision per request enforced by UNIQUE.
-- The UNIQUE constraint on approval_request_id prevents concurrent double-decisions.
CREATE TABLE IF NOT EXISTS approval_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  approval_request_id uuid NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
  decision varchar(20) NOT NULL CHECK (decision IN ('approved', 'rejected')),
  actor_name text NOT NULL,
  comment text,
  decided_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (approval_request_id)
);
