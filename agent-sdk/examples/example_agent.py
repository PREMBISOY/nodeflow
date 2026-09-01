"""Use an existing NodeFlow agent: set PROJECT_ID and AGENT_ID before running."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from nodeflow_sdk import NodeFlowClient

client = NodeFlowClient()
project_id, agent_id = os.environ["PROJECT_ID"], os.environ["AGENT_ID"]
print("Context:", client.context(agent_id))
client.event(project_id, agent_id, "TASK_STARTED", "Agent connected through the NodeFlow SDK")
print("Updates:", client.updates(agent_id))
recipient_id = os.getenv("RECIPIENT_AGENT_ID")
if recipient_id:
    client.message(agent_id, recipient_id, "SDK status", "Agent is connected through NodeFlow.")
