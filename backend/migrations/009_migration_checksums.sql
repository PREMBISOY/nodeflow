-- Migration 009: Migration runner metadata hardening.
-- Adds checksum, timing, and failure tracking to the migrations table.
-- Run after 008_approval_state.sql.
-- Do NOT modify this migration after it has been applied.

ALTER TABLE nodeflow_schema_migrations
  ADD COLUMN IF NOT EXISTS checksum text,
  ADD COLUMN IF NOT EXISTS started_at timestamptz,
  ADD COLUMN IF NOT EXISTS completed_at timestamptz,
  ADD COLUMN IF NOT EXISTS failed_at timestamptz,
  ADD COLUMN IF NOT EXISTS failure_reason text;
