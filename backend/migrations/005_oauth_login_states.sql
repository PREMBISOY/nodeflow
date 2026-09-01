-- One-time, server-side OAuth state records. The browser receives only a
-- matching HttpOnly cookie containing the PKCE verifier.
CREATE TABLE IF NOT EXISTS oauth_login_states (
  nonce text PRIMARY KEY,
  expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS oauth_login_states_expires_idx ON oauth_login_states(expires_at);
