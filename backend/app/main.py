from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.container import build_container
from app.services.agent_gateway import AgentGateway
from app.services.repository import EntityNotFoundError, ProjectKnowledgeRepository
from app.platform import PlatformStore, SessionCodec, SqlPlatformStore, router as platform_router
from app.persistence import SqlAlchemyProjectRepository, build_session_factory


logging.basicConfig(level=logging.INFO)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": None, "error": {"code": code, "message": message}},
    )


def create_app(
    repository: ProjectKnowledgeRepository | None = None,
    gateway: AgentGateway | None = None,
    load_demo_data: bool = False,
) -> FastAPI:
    app = FastAPI(
        title="NodeFlow Core Intelligence API",
        version="0.1.0",
        description="Shared project brain, impact analysis, context propagation, messaging, and onboarding.",
    )
    database_url = os.getenv("DATABASE_URL")
    platform_store = PlatformStore()
    if repository is None and database_url:
        session_factory = build_session_factory(database_url)
        repository = SqlAlchemyProjectRepository(session_factory())
        platform_store = SqlPlatformStore(session_factory())
    container = build_container(repository, gateway)
    # Application startup never inserts showcase data. Test code may inject its
    # isolated fixtures directly into an in-memory repository when needed.
    app.state.container = container
    app.state.platform_store = platform_store
    app.state.session_codec = SessionCodec()
    app.state.enforce_tenants = bool(database_url)
    origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if origin.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])
    app.include_router(router)
    app.include_router(platform_router)

    @app.get("/health")
    def health():
        return {"success": True, "data": {"status": "ok"}, "error": None}

    frontend_dir = Path(__file__).resolve().parent / "static"
    if frontend_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="frontend-assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            requested_file = frontend_dir / path
            if path and requested_file.is_file():
                return FileResponse(requested_file)
            return FileResponse(frontend_dir / "index.html")

    @app.exception_handler(EntityNotFoundError)
    async def not_found_handler(_request: Request, exc: EntityNotFoundError):
        return error_response(404, "NOT_FOUND", str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        message = "; ".join(error["msg"] for error in exc.errors())
        return error_response(422, "VALIDATION_ERROR", message)

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return error_response(400, "INVALID_REQUEST", str(exc))

    @app.exception_handler(LookupError)
    async def lookup_error_handler(_request: Request, exc: LookupError):
        return error_response(404, "NOT_FOUND", str(exc))

    return app


app = create_app()
