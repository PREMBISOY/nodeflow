"""Minimal local-agent bridge for the existing NodeFlow REST contracts."""
import argparse
import json
import os
from pathlib import Path

import httpx

CONFIG = Path(".nodeflow.json")


def load_config():
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def save_config(value):
    CONFIG.write_text(json.dumps(value, indent=2))


def request(method, path, payload=None, params=None):
    config = load_config()
    result = httpx.request(method, config.get("base_url", os.getenv("NODEFLOW_URL", "http://localhost:8000")).rstrip("/") + path, json=payload, params=params, timeout=15).json()
    if not result["success"]:
        raise SystemExit(result["error"]["message"])
    print(json.dumps(result["data"], indent=2))
    return result["data"]


def connected():
    config = load_config()
    if not config.get("agent_id") or not config.get("project_id"):
        raise SystemExit("Run nodeflow connect --project UUID --agent UUID first.")
    return config


parser = argparse.ArgumentParser(prog="nodeflow")
sub = parser.add_subparsers(dest="command", required=True)
init = sub.add_parser("init"); init.add_argument("--url", default="http://localhost:8000")
connect = sub.add_parser("connect"); connect.add_argument("--project", required=True); connect.add_argument("--agent", required=True)
context = sub.add_parser("context"); context.add_argument("--scope", default="related", choices=["my_work", "team", "related", "project"])
sub.add_parser("status")
task = sub.add_parser("task"); task.add_argument("description")
event = sub.add_parser("event"); event.add_argument("--type", required=True); event.add_argument("--summary", required=True); event.add_argument("--payload", default="{}")
message = sub.add_parser("message"); message.add_argument("--to", required=True); message.add_argument("--subject", required=True); message.add_argument("--message", required=True)

args = parser.parse_args()
if args.command == "init":
    save_config({"base_url": args.url}); print("Initialized .nodeflow.json")
elif args.command == "connect":
    config = load_config(); config.update(project_id=args.project, agent_id=args.agent); save_config(config); print("Connected existing agent identity")
else:
    config = connected()
    if args.command == "context": request("GET", f"/api/v1/agents/{config['agent_id']}/context", params={"scope": args.scope})
    elif args.command == "status": request("GET", f"/api/v1/agents/{config['agent_id']}/updates")
    elif args.command == "task": request("POST", "/api/v1/events", {"project_id": config["project_id"], "event_type": "TASK_STARTED", "actor_type": "agent", "actor_id": config["agent_id"], "summary": args.description})
    elif args.command == "event": request("POST", "/api/v1/events", {"project_id": config["project_id"], "event_type": args.type, "actor_type": "agent", "actor_id": config["agent_id"], "summary": args.summary, "payload": json.loads(args.payload)})
    elif args.command == "message": request("POST", f"/api/v1/agents/{config['agent_id']}/messages", {"recipient_agent_id": args.to, "subject": args.subject, "content": args.message})
