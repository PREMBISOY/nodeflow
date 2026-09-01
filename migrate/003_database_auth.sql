CREATE TABLE IF NOT EXISTS user_credentials (user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, password_hash text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS auth_sessions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid REFERENCES users(id) ON DELETE CASCADE, jti text NOT NULL UNIQUE, revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL);
CREATE INDEX IF NOT EXISTS auth_sessions_jti_idx ON auth_sessions(jti);
