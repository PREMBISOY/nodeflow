# Railway + Supabase deployment

Create one Supabase PostgreSQL project for the whole team, set its pooled PostgreSQL URL as `DATABASE_URL` in Railway, then run the automated migration suite locally using `python -m app.migrate` to apply all migrations safely with checksum tracking and locking. Do not commit credentials.

Set `JWT_SECRET` to a long random value and `CORS_ORIGINS` to the deployed frontend URL (comma-separated for multiple trusted origins). Railway should start the service with `uvicorn app.main:app --host 0.0.0.0 --port $PORT` from `backend/`; use `GET /health` as its health check. With `DATABASE_URL` present, both project intelligence persistence and authentication/team state use the shared Supabase database.

For local development, install `backend/requirements.txt`, set the variables from `.env.example`, and run the same Uvicorn command with `--reload`. Every browser should authenticate, join the same team code, and operate through the team encoded in its signed active session.

## GitHub OAuth and public repositories

Set `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, and a long random `GITHUB_WEBHOOK_SECRET` in Railway. The GitHub OAuth App callback URL must be `https://nodeflow.up.railway.app/api/v1/auth/github/callback` (or the matching value of `GITHUB_OAUTH_REDIRECT_URI`). GitHub sign-in uses PKCE and a one-time, cookie-bound state; its GitHub access token is used only during sign-in and is never stored. A team member can connect a public `owner/repository` to a project with `POST /api/v1/teams/{team_id}/projects/{project_id}/github/repositories`. Configure the returned `/api/v1/integrations/github/webhook/{connection_id}` URL in GitHub using the connection-specific generated secret returned by the connect endpoint; only valid signed `push` and `pull_request` deliveries are ingested with idempotency enforcement.
