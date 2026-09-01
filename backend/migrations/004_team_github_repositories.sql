-- Public GitHub repository connections are team- and project-scoped.
-- This stores repository metadata only; no GitHub OAuth access token is retained.
CREATE TABLE IF NOT EXISTS team_github_repositories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  full_name varchar(300) NOT NULL,
  html_url text NOT NULL,
  default_branch varchar(255) NOT NULL DEFAULT 'main',
  connected_by uuid NOT NULL REFERENCES users(id),
  connected_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(team_id, project_id),
  UNIQUE(team_id, full_name)
);
CREATE INDEX IF NOT EXISTS team_github_repositories_team_idx ON team_github_repositories(team_id);
