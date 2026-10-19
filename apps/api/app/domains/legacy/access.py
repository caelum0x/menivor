"""Caller resolution + ownership for the legacy (MoneyPrinter) task surface.

The legacy ``/videos``, ``/tasks``, ``/musics``, ``/video_materials``,
``/stream`` and ``/download`` routes predate per-user accounts. This module
gives them the same principal resolution every product domain uses (Clerk JWT,
personal/device API key) plus a durable owner record so each caller only ever
sees and touches their own tasks and uploads.

Ownership of a legacy task is stored as a small marker file inside the task's
own artifact directory (``storage/tasks/<task_id>/.owner``). The artifacts the
``/stream`` and ``/download`` routes serve already live there, so the owner
record shares their lifetime (deleting the task directory removes both) and is
visible to every API worker process on the box without extra infrastructure.
"""

from __future__ import annotations

import os
import re

from fastapi import Request
from loguru import logger

from app.controllers import base
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.auth import resolve_principal
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


OWNER_MARKER = ".owner"
# Per-user upload namespaces live under this sub-directory of each library root.
USER_UPLOAD_DIR = "users"
# Legacy generation endpoints run LLM/TTS/render work on the operator's keys and
# are not metered by the credit/wallet system, so they stay off unless the
# operator opts in explicitly (mirrors REELFORGE_EXPOSE_LEGACY_TASKS in asgi.py).
LEGACY_GENERATION_ENV = "REELFORGE_EXPOSE_LEGACY_GENERATION"

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def legacy_generation_enabled() -> bool:
    """Whether the unmetered legacy generation endpoints are switched on."""
    return os.getenv(LEGACY_GENERATION_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_legacy_generation(request_id: str) -> None:
    """Raise ``404`` unless the operator enabled the legacy generation surface."""
    if legacy_generation_enabled():
        return
    raise HttpException(
        task_id=request_id,
        status_code=404,
        message=(
            f"{request_id}: legacy generation endpoints are disabled; "
            "create videos with POST /api/v1/jobs"
        ),
    )


def require_caller(request: Request) -> str:
    """FastAPI dependency: resolve the authenticated caller's user id or raise.

    Raises ``401`` for missing/invalid credentials and ``503`` when the
    persistence layer is unavailable (identity cannot be established, so the
    request must fail closed rather than fall back to anonymous access).
    """
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None or resolve_principal is None or get_session is None:
        logger.error(
            f"legacy surface auth unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )
    with get_session() as session:
        user = resolve_principal(request, session, request_id)
        user_id = str(user.id)
    request.state.caller_user_id = user_id
    return user_id


def _safe_segment(value: str) -> str:
    """Return ``value`` when it is a safe single path segment, else ``""``."""
    value = str(value or "").strip()
    return value if _SAFE_ID.match(value) else ""


def record_task_owner(task_id: str, user_id: str) -> None:
    """Persist ``user_id`` as the owner of legacy task ``task_id``."""
    task_id = _safe_segment(task_id)
    if not task_id:
        raise ValueError("invalid task id")
    directory = utils.task_dir(task_id)
    with open(os.path.join(directory, OWNER_MARKER), "w", encoding="utf-8") as fh:
        fh.write(str(user_id))


def task_owner(task_id: str) -> str:
    """Return the recorded owner of a legacy task, or ``""`` when unknown."""
    task_id = _safe_segment(task_id)
    if not task_id:
        return ""
    path = os.path.join(utils.storage_dir(), "tasks", task_id, OWNER_MARKER)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def owns_task(task_id: str, user_id: str) -> bool:
    """Whether ``user_id`` owns legacy task ``task_id`` (unowned tasks: never)."""
    owner = task_owner(task_id)
    return bool(owner) and owner == str(user_id)


def user_upload_subdir(user_id: str) -> str:
    """The caller's relative upload namespace, e.g. ``users/<user_id>``."""
    segment = _safe_segment(user_id)
    if not segment:
        raise ValueError("invalid user id")
    return f"{USER_UPLOAD_DIR}/{segment}"
