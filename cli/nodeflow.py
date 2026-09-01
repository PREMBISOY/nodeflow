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
    base_url = config.get("base_url") or os.getenv("NODEFLOW_API_URL")
    if not base_url:
        raise SystemExit("Set NODEFLOW_API_URL or run nodeflow init --url DEPLOYED_NODEFLOW_URL.")
    token = config.get("access_token") or os.getenv("NODEFLOW_ACCESS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    result = httpx.request(method, base_url.rstrip("/") + path, json=payload, params=params, headers=headers, timeout=15).json()
    if not result["success"]:
        raise SystemExit(result["error"]["message"])
    print(json.dumps(result["data"], indent=2))
    return result["data"]


def connected():
    config = load_config()
    if not config.get("agent_id") or not config.get("project_id"):
        raise SystemExit("Run nodeflow connect --project UUID --agent UUID first.")
    return config


def build_parser():
    parser = argparse.ArgumentParser(prog="nodeflow")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init"); init.add_argument("--url", default=os.getenv("NODEFLOW_API_URL")); init.add_argument("--token", default=os.getenv("NODEFLOW_ACCESS_TOKEN"))
    connect = sub.add_parser("connect"); connect.add_argument("--project", required=True); connect.add_argument("--agent", required=True)
    context = sub.add_parser("context"); context.add_argument("--scope", default="related", choices=["my_work", "team", "related", "project"])
    sub.add_parser("status")
    task = sub.add_parser("task"); task.add_argument("description")
    event = sub.add_parser("event"); event.add_argument("--type", required=True); event.add_argument("--summary", required=True); event.add_argument("--payload", default="{}")
    message = sub.add_parser("message"); message.add_argument("--to", required=True); message.add_argument("--subject", required=True); message.add_argument("--message", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "init":
        if not args.url:
            raise SystemExit("Provide --url or set NODEFLOW_API_URL.")
        config = {"base_url": args.url}
        if args.token:
            config["access_token"] = args.token
        save_config(config); print("Initialized .nodeflow.json")
    elif args.command == "connect":
        config = load_config(); config.update(project_id=args.project, agent_id=args.agent); save_config(config); print("Connected existing agent identity")
    else:
        config = connected()
        if args.command == "context": request("GET", f"/api/v1/agents/{config['agent_id']}/context", params={"scope": args.scope})
        elif args.command == "status": request("GET", f"/api/v1/agents/{config['agent_id']}/updates")
        elif args.command == "task": request("POST", "/api/v1/events", {"project_id": config["project_id"], "event_type": "TASK_STARTED", "actor_type": "agent", "actor_id": config["agent_id"], "summary": args.description})
        elif args.command == "event": request("POST", "/api/v1/events", {"project_id": config["project_id"], "event_type": args.type, "actor_type": "agent", "actor_id": config["agent_id"], "summary": args.summary, "payload": json.loads(args.payload)})
        elif args.command == "message": request("POST", f"/api/v1/agents/{config['agent_id']}/messages", {"recipient_agent_id": args.to, "subject": args.subject, "content": args.message})


if __name__ == "__main__":
    main()
