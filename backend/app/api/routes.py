from __future__ import annotations
from collections import Counter
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from app.models import Decision, Event, Memory, Message, Task
from app.schemas.persistence import ContextScope, DecisionCreate, EventCreate, MemoryCreate, MessageCreate, TaskCreate, TaskUpdate

router = APIRouter(prefix="/api/v1")
def ok(data): return {"success": True, "data": data, "error": None}
def repo(request: Request): return request.app.state.repository
def context(request: Request): return request.app.state.context_queries
def collaboration(request: Request): return request.app.state.collaboration
def replay(request: Request): return request.app.state.replay

@router.get("/projects/{project_id}")
def get_project(project_id: UUID, request: Request): return ok(repo(request).get_project(project_id))

@router.get("/projects/{project_id}/state")
def project_state(project_id: UUID, request: Request):
    r=repo(request); project=r.get_project(project_id); tasks=r.list_tasks(project_id); agents=r.list_agents(project_id)
    return ok({"project":project,"components":len(r.list_components(project_id)),"task_counts":dict(Counter(t.status for t in tasks)),"agent_counts":dict(Counter(a.status for a in agents)),"recent_events":r.list_events(project_id,limit=20)})

@router.get("/projects/{project_id}/architecture")
def architecture(project_id: UUID, request: Request):
    r=repo(request); r.get_project(project_id); return ok({"components":r.list_components(project_id),"relationships":r.list_relationships(project_id)})

@router.get("/agents")
def agents(project_id: UUID = Query(...), request: Request = None): return ok(repo(request).list_agents(project_id))
@router.get("/agents/{agent_id}")
def agent(agent_id: UUID, request: Request): return ok(repo(request).get_agent(agent_id))
@router.get("/agents/{agent_id}/context")
def agent_context(agent_id: UUID, request: Request, scope: ContextScope = Query("related")):
    return ok(context(request).for_agent(repo(request).get_agent(agent_id), scope))

@router.get("/tasks")
def tasks(project_id: UUID = Query(...), request: Request = None): return ok(repo(request).list_tasks(project_id))
@router.post("/tasks", status_code=201)
def create_task(payload: TaskCreate, request: Request): return ok(repo(request).create_task(Task(status="TODO", **payload.model_dump())))
@router.patch("/tasks/{task_id}")
def update_task(task_id: UUID, payload: TaskUpdate, request: Request):
    task=repo(request).update_task(task_id,**payload.model_dump(exclude_none=True))
    collaboration(request).record_event(Event(project_id=task.project_id,event_type=f"TASK_{task.status}",description=f"Task updated: {task.title}",actor_type="system",affected_components=task.affected_components,metadata={"task_id":str(task.id),"task_status":task.status}))
    return ok(task)
@router.get("/events")
def events(project_id: UUID = Query(...), before: datetime | None = None, request: Request = None): return ok(repo(request).list_events(project_id,before=before))
@router.post("/events", status_code=201)
def create_event(payload: EventCreate, request: Request): return ok(collaboration(request).record_event(Event(**payload.model_dump())))
@router.get("/decisions")
def decisions(project_id: UUID = Query(...), request: Request = None): return ok(repo(request).list_decisions(project_id))
@router.post("/decisions", status_code=201)
def create_decision(payload: DecisionCreate, request: Request): return ok(repo(request).create_decision(Decision(**payload.model_dump())))
@router.get("/memory")
def memory(project_id: UUID = Query(...), query: str = "", request: Request = None):
    values=repo(request).list_memories(project_id); terms=set(query.lower().split()); return ok([m for m in values if not terms or terms.intersection(m.content.lower().split())])
@router.post("/memory", status_code=201)
def create_memory(payload: MemoryCreate, request: Request): return ok(repo(request).create_memory(Memory(**payload.model_dump())))
@router.post("/agents/{agent_id}/messages", status_code=201)
def send_message(agent_id: UUID, payload: MessageCreate, request: Request):
    return ok(collaboration(request).send_message(Message(sender_agent_id=agent_id,**payload.model_dump())))
@router.get("/agents/{agent_id}/messages")
def messages(agent_id: UUID, project_id: UUID = Query(...), request: Request = None): return ok(repo(request).list_messages(project_id,agent_id))
@router.get("/agents/{agent_id}/updates")
def updates(agent_id: UUID, request: Request): return ok(repo(request).list_updates(agent_id))
@router.get("/projects/{project_id}/state/at")
def state_at(project_id: UUID, timestamp: datetime, request: Request):
    repo(request).get_project(project_id); return ok(replay(request).at(project_id,timestamp))
