# NodeFlow

NodeFlow is a model-agnostic shared project-intelligence layer for teams of humans and AI agents. Git remains the source of truth for code; NodeFlow provides structured knowledge about architecture, work, changes, decisions, and agent activity.

This repository currently implements the core intelligence subsystem:

- structured Project Brain retrieval
- deterministic dependency and change-impact analysis
- relevance-scored automatic context propagation
- agent-to-agent messages recorded in project history
- role-aware new-member onboarding
- Prem-owned `/api/v1` contracts and golden demo data

## Run locally

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for interactive API documentation.

## Test

```powershell
cd backend
.venv\Scripts\python -m pytest
```

The development app starts with deterministic golden-demo data. See [docs/demo.md](docs/demo.md) for IDs and a complete walkthrough. The in-memory adapter is intentionally behind a repository protocol so the persistence and agent-gateway owners can replace adapters without rewriting intelligence logic.
