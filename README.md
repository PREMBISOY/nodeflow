# NodeFlow AI

NodeFlow is a model-agnostic shared project-intelligence layer for teams of humans and AI agents. Git remains the source of truth for code; NodeFlow provides structured knowledge about architecture, work, changes, decisions, and agent activity.

**🚀 Live Deployment:** [https://nodeflow.up.railway.app/](https://nodeflow.up.railway.app/)

## Key Features

- **Structured Project Brain retrieval:** Provides AI agents (like Codex, Claude Code, and Antigravity) with contextual history.
- **NodeFlow CLI:** Sync project context seamlessly from your terminal directly to your AI agents.
- **Team Management (RBAC):** Authenticated team platform where creators (`OWNER`) can add participants (`MEMBER`), securely governed by Supabase Row Level Security (RLS).
- **Automatic Context Propagation:** Relevance-scored automatic context for AI coding tools.
- **Agent-to-Agent Communication:** Messages and changes are recorded transparently in the project history.
- **Deterministic Dependency & Change-Impact Analysis.**

## Architecture & Tech Stack

- **Frontend:** React, Vite, Tailwind CSS
- **Backend:** FastAPI, Python, SQLAlchemy, Pydantic
- **Database:** PostgreSQL (Supabase) with strict RLS multi-tenant isolation
- **CLI & SDK:** Python-based Agent Gateway and SDK
- **Deployment:** Docker & Railway

---

## 💻 Getting Started (Local Development)

### 1. Database Setup

Ensure you have a PostgreSQL/Supabase database running. Use the provided `.env.example` as a template and provide your `DATABASE_URL`.

### 2. Backend (FastAPI)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# Run migrations
.venv\Scripts\python -m app.migrate

# Start the server
.venv\Scripts\python -m uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

### 3. Frontend (React/Vite)

```powershell
cd frontend
pnpm install
pnpm run dev
```

### 4. NodeFlow CLI

The CLI tool allows agents and developers to connect to the NodeFlow platform.
```powershell
python cli/nodeflow.py login
```

---

## 🧪 Testing

The test suite ensures RBAC, API endpoints, and core intelligence functionalities are operating correctly.

```powershell
cd backend
.venv\Scripts\python -m pytest
```

The development app starts with deterministic golden-demo data. See [docs/demo.md](docs/demo.md) for IDs and a complete walkthrough.

## 📖 Documentation

- [API Reference](docs/api.md)
- [Team Workflow Guide](docs/team-aware-workflows.md)
- [Agent Gateway Documentation](docs/agent-gateway.md)
