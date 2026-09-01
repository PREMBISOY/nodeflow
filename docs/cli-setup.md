# NodeFlow CLI Setup and Demo Guide

The NodeFlow CLI lets a local AI agent use the shared Railway deployment. It does not start a local backend or create a separate database.

## Prerequisites

- Python 3.11 or later
- A NodeFlow account
- A platform-issued access token with an active team
- An existing project UUID and agent UUID for that team

For the current demo deployment, use `https://nodeflow.up.railway.app`.

## Install once

From the repository root:

```powershell
python -m pip install -e .
nodeflow --help
```

This installs `nodeflow` as a Python console command. It can then be run from any directory.

### If PowerShell says `nodeflow` is not recognized

Close and reopen PowerShell first. If the current window still needs it, run:

```powershell
$env:Path += ";C:\Users\sunal\AppData\Local\Python\pythoncore-3.14-64\Scripts"
nodeflow --help
```

The Python path differs by machine. To find it, run:

```powershell
python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

Then append the printed directory to the current session's `$env:Path`.

Fallback form, which works without PATH configuration:

```powershell
python C:\path\to\nodeflow\cli\nodeflow.py --help
```

## Authenticate and configure the shared deployment

Get an access token through the NodeFlow platform login. The token must have the intended team selected as its active team. Do not place a token in source code or commit it.

For a single terminal session:

```powershell
$env:NODEFLOW_API_URL = "https://nodeflow.up.railway.app"
$env:NODEFLOW_ACCESS_TOKEN = "<platform-issued-token>"
nodeflow init
```

Or persist the deployment configuration in the current working directory:

```powershell
nodeflow init --url https://nodeflow.up.railway.app --token <platform-issued-token>
```

This writes `.nodeflow.json` in that directory. Keep it private because it can contain a token.

## Select an authorized identity

Use project and agent IDs supplied by the platform for the same active team:

```powershell
nodeflow connect --project PROJECT_UUID --agent AGENT_UUID
```

`connect` only stores these existing identifiers locally. It does not register an agent, create a team, or bypass tenant controls.

## Commands

| Command | What it does |
| --- | --- |
| `nodeflow --help` | Shows every command. |
| `nodeflow init --url URL` | Configures the shared API URL. |
| `nodeflow connect --project ID --agent ID` | Selects existing project and agent context. |
| `nodeflow context --scope related` | Retrieves authorized agent context. |
| `nodeflow status` | Retrieves authorized agent updates. |
| `nodeflow task "Description"` | Reports `TASK_STARTED`. |
| `nodeflow event --type TYPE --summary TEXT` | Reports an extensible agent event. |
| `nodeflow message --to ID --subject TEXT --message TEXT` | Sends a routed message. |

Every command has its own help page:

```powershell
nodeflow event --help
nodeflow message --help
```

Do not type `--help` or `-h` alone; PowerShell treats those as commands. Always prefix them with `nodeflow`.

## Demo flow

```powershell
nodeflow context --scope related
nodeflow event --type CODE_CHANGED --summary "Updated relay transport"
nodeflow message --to RECIPIENT_AGENT_UUID --subject "Relay update" --message "The tenant-scoped relay is ready."
nodeflow status
```

The platform enforces active-team and project access. A `404` for an agent or project from another team is the expected tenant-isolation behavior.

## Production relay configuration

Set these Railway service variables on the NodeFlow backend:

| Variable | Purpose |
| --- | --- |
| `AGENT_RELAY_URL` | NodeFlow-managed relay delivery endpoint. |
| `AGENT_RELAY_AUTH_TOKEN` | Optional bearer token sent to the relay. |
| `AGENT_RELAY_MAX_ATTEMPTS` | Delivery attempts; default is `3`. |
| `AGENT_RELAY_RETRY_DELAY_SECONDS` | Linear retry base delay; default is `0.25`. |

The backend includes the authorized project and team scope in every relay envelope, rejects cross-project recipients, and logs delivery retry/failure events.
