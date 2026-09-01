-- One append-only human decision is allowed for each project approval request.
-- This is the database-level concurrency guard for collaboration approvals.
CREATE UNIQUE INDEX IF NOT EXISTS events_one_approval_decision_per_request_idx
ON events (project_id, (payload->>'approval_event_id'))
WHERE event_type = 'collaboration_approval_decision';
