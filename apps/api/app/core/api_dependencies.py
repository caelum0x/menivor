"""Shared HTTP-domain dependencies that do not belong to a feature router."""

from __future__ import annotations

from app.core.auth import resolve_principal
from app.models.exception import HttpException

try:
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - optional persistence dependency
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


def require_database(request_id: str) -> None:
    """Raise a stable 503 when persistence cannot be imported."""
    if _DB_IMPORT_ERROR is not None or get_session is None:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


__all__ = ["get_session", "require_database", "resolve_principal"]
