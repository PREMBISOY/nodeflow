from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import scoped_session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.container import build_container
from app.core.demo_data import seed_demo
from app.services.agent_gateway import AgentGateway
from app.services.repository import EntityNotFoundError, InMemoryProjectRepository, ProjectKnowledgeRepository
from app.platform import PlatformStore, SessionCodec, SqlPlatformStore, router as platform_router
from app.persistence import SqlAlchemyProjectRepository, build_session_factory


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": None, "error": {"code": code, "message": message}},
    )


def resolve_frontend_file(frontend_dir: Path, requested_path: str) -> Path | None:
    """Resolve an asset without allowing it to escape the built frontend root."""
    root = frontend_dir.resolve()
    candidate = (root / requested_path).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def create_app(
    repository: ProjectKnowledgeRepository | None = None,
    gateway: AgentGateway | None = None,
    load_demo_data: bool = True,
) -> FastAPI:
    app = FastAPI(
        title="NodeFlow Core Intelligence API",
        version="0.1.0",
        description="Shared project brain, impact analysis, context propagation, messaging, and onboarding.",
    )
    database_url = os.getenv("DATABASE_URL")
    platform_store = PlatformStore()
    session_factory = None
    if repository is None and database_url:
        session_factory = build_session_factory(database_url)
        # FastAPI can execute synchronous endpoints concurrently. A plain
        # Session stored on app state is not safe to share between requests;
        # scoped_session provides an independent session for each worker thread.
        sessions = scoped_session(session_factory)
        repository = SqlAlchemyProjectRepository(sessions)
        platform_store = SqlPlatformStore(sessions)
        app.state.database_sessions = sessions
    app.state.database_session_factory = session_factory
    container = build_container(repository, gateway)
    if load_demo_data and isinstance(container.repository, InMemoryProjectRepository):
        seed_demo(container.repository)
    app.state.container = container
    app.state.platform_store = platform_store
    app.state.session_codec = SessionCodec()
    app.state.enforce_tenants = bool(database_url)
    origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        # Participant management uses DELETE from the dashboard.
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(router)
    app.include_router(platform_router)

    @app.middleware("http")
    async def release_database_session(request: Request, call_next):
        try:
            return await call_next(request)
        finally:
            sessions = getattr(request.app.state, "database_sessions", None)
            if sessions is not None:
                sessions.remove()

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "").strip()
        request_id = supplied[:128] if supplied else str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/health/live")
    def liveness():
        return {"success": True, "data": {"status": "alive"}, "error": None}

    @app.get("/health")
    @app.get("/health/ready")
    def readiness(request: Request):
        factory = request.app.state.database_session_factory
        if factory is None:
            return {
                "success": True,
                "data": {"status": "ready", "database": "in-memory"},
                "error": None,
            }
        try:
            with factory() as session:
                session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.exception("Database readiness check failed")
            return error_response(503, "DATABASE_UNAVAILABLE", "Database is not ready")
        return {
            "success": True,
            "data": {"status": "ready", "database": "connected"},
            "error": None,
        }

    frontend_dir = Path(__file__).resolve().parent / "static"
    if frontend_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="frontend-assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                return error_response(404, "NOT_FOUND", "API route was not found")
            requested_file = resolve_frontend_file(frontend_dir, path) if path else None
            if requested_file is not None:
                return FileResponse(requested_file)
            return FileResponse(frontend_dir / "index.html")

    @app.exception_handler(EntityNotFoundError)
    async def not_found_handler(_request: Request, exc: EntityNotFoundError):
        return error_response(404, "NOT_FOUND", str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        message = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'] if part != 'body')}: {error['msg']}"
            for error in exc.errors()
        )
        return error_response(422, "VALIDATION_ERROR", message)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException):
        codes = {
            400: "INVALID_REQUEST",
            401: "AUTHENTICATION_REQUIRED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "VALIDATION_ERROR",
            503: "SERVICE_UNAVAILABLE",
        }
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return error_response(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), message)

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return error_response(400, "INVALID_REQUEST", str(exc))

    @app.exception_handler(LookupError)
    async def lookup_error_handler(_request: Request, exc: LookupError):
        return error_response(404, "NOT_FOUND", str(exc))

    @app.exception_handler(PermissionError)
    async def permission_error_handler(_request: Request, exc: PermissionError):
        return error_response(403, "FORBIDDEN", str(exc))

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled request failure request_id=%s path=%s",
            getattr(request.state, "request_id", "unknown"),
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        response = error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")
        response.headers["X-Request-ID"] = getattr(request.state, "request_id", "unknown")
        return response

    return app


app = create_app()
