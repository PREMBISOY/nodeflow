from __future__ import annotations
import os
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.routes import router
from app.core.seed import seed_demo
from app.db import Base, session_factory
from app.services.repository import CollaborationService, ContextQueryService, EntityNotFoundError, InMemoryProjectRepository, PermissionDeniedError, SqlAlchemyProjectRepository, StateReplayService

def create_app(repository=None, seed: bool = True) -> FastAPI:
    app=FastAPI(title="NodeFlow Data & Persistence API",version="0.2.0")
    if repository is None:
        database_url=os.getenv("DATABASE_URL")
        if database_url:
            factory=session_factory(database_url); Base.metadata.create_all(factory.kw["bind"]); repository=SqlAlchemyProjectRepository(factory())
        else: repository=InMemoryProjectRepository()
    if seed: seed_demo(repository)
    app.state.repository=repository; app.state.context_queries=ContextQueryService(repository); app.state.collaboration=CollaborationService(repository); app.state.replay=StateReplayService(repository); app.include_router(router)
    @app.get("/health")
    def health(): return {"success":True,"data":{"status":"ok"},"error":None}
    @app.exception_handler(EntityNotFoundError)
    async def missing(_: Request, exc: EntityNotFoundError): return JSONResponse(404,{"success":False,"data":None,"error":{"code":"NOT_FOUND","message":str(exc)}})
    @app.exception_handler(PermissionDeniedError)
    async def forbidden(_: Request, exc: PermissionDeniedError): return JSONResponse(403,{"success":False,"data":None,"error":{"code":"FORBIDDEN","message":str(exc)}})
    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError): return JSONResponse(422,{"success":False,"data":None,"error":{"code":"VALIDATION_ERROR","message":str(exc)}})
    return app
app=create_app()
