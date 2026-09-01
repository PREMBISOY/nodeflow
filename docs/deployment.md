# Railway + Supabase deployment

Create one Supabase PostgreSQL project for the whole team, set its pooled PostgreSQL URL as `DATABASE_URL` in Railway, then run migrations `001_project_knowledge.sql` and `002_platform_identity_tenants.sql` in order. Do not commit credentials.

Set `JWT_SECRET` to a long random value and `CORS_ORIGINS` to the deployed frontend URL (comma-separated for multiple trusted origins). Railway should start the service with `uvicorn app.main:app --host 0.0.0.0 --port $PORT` from `backend/`; use `GET /health` as its health check.

For local development, install `backend/requirements.txt`, set the variables from `.env.example`, and run the same Uvicorn command with `--reload`. Every browser should authenticate, join the same team code, and operate through the team encoded in its signed active session.
