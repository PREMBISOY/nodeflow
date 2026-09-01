from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.container import build_container
from app.core.demo_data import seed_demo
from app.services.agent_gateway import AgentGateway
from app.services.repository import EntityNotFoundError, InMemoryProjectRepository, ProjectKnowledgeRepository


logging.basicConfig(level=logging.INFO)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": None, "error": {"code": code, "message": message}},
    )


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
    container = build_container(repository, gateway)
    if load_demo_data and isinstance(container.repository, InMemoryProjectRepository):
        seed_demo(container.repository)
    app.state.container = container
    app.include_router(router)

    @app.get("/health")
    def health():
        return {"success": True, "data": {"status": "ok"}, "error": None}

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
