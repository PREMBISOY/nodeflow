from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: ErrorDetail | None = None


def success(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "error": None}
