-- Run after 001_project_knowledge.sql. Production target: Supabase PostgreSQL.
CREATE TABLE users (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(200) NOT NULL, email varchar(320) NOT NULL UNIQUE, auth_subject text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE teams (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(200) NOT NULL, team_code varchar(32) NOT NULL UNIQUE, created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE team_members (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), team_id uuid NOT NULL REFERENCES teams(id), user_id uuid NOT NULL REFERENCES users(id), role varchar(20) NOT NULL CHECK (role IN ('OWNER','ADMIN','MEMBER')), joined_at timestamptz NOT NULL DEFAULT now(), UNIQUE(team_id, user_id));
ALTER TABLE projects ADD COLUMN IF NOT EXISTS team_id uuid REFERENCES teams(id);
CREATE INDEX projects_team_idx ON projects(team_id);
CREATE INDEX team_members_user_idx ON team_members(user_id);
