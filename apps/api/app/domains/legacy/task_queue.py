"""Caller-scoped async task queue (``/api/v1/tasks``).

The task queue is the "everything I have rendering" view the mobile app shows.
It merges two sources, both strictly scoped to the authenticated caller:

* the caller's product **jobs** (``Job`` rows: reels, B-roll, speak, dubs, ...),
  which is where every real render lives; and
* the caller's **legacy** MoneyPrinter tasks (only present when the operator
  enabled the legacy generation surface), identified by their owner marker.

Every item is normalized to the task-queue wire schema (``task_id``,
``task_type``, ``status`` in ``pending|running|completed|failed|cancelled``, a
``progress`` object, timestamps, ``result``/``error``). ``DELETE`` cancels an
in-flight job: it is marked failed at the ``cancelled`` stage (the pipeline
workers check this before and after every stage and stop), its Celery task is
revoked best-effort, and any wallet reservation is released.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models import const
from app.models.exception import HttpException
from app.utils import utils

from .access import owns_task, require_caller

try:
    from app.models.db.base import get_session
    from app.models.db.repositories import JobRepository

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    get_session = None  # type: ignore[assignment]
    JobRepository = None  # type: ignore[assignment,misc]
    _DB_IMPORT_ERROR = exc

try:
    from app.services import state as sm
    from app.services import task as tm
except Exception as exc:  # pragma: no cover - legacy engine optional
    sm = None  # type: ignore[assignment]
    tm = None  # type: ignore[assignment]
    logger.warning(f"legacy task state unavailable for the task queue: {exc}")


router = new_router()

# Stage name recorded on a job the owner cancelled. Workers treat a FAILED job
# with this failed_stage as "stop, do nothing more" (see workers/tasks.py).
CANCELLED_STAGE = "cancelled"
CANCELLED_ERROR = "cancelled by user"

TASK_STATUSES = ("pending", "running", "completed", "failed", "cancelled")
_MAX_SCAN = 1000


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    except Exception:  # noqa: BLE001 - never fail a read on a timestamp
        return str(value)


def _public_stages(job: Any) -> dict[str, str]:
    stages = dict(getattr(job, "stages", None) or {})
    return {
        str(k): str(v)
        for k, v in stages.items()
        if not str(k).startswith("_") and isinstance(v, str)
    }


def _job_status(job: Any, stages: dict[str, str]) -> str:
    if job.state == const.TASK_STATE_COMPLETE:
        return "completed"
    if job.state == const.TASK_STATE_FAILED:
        if (getattr(job, "failed_stage", "") or "") == CANCELLED_STAGE:
            return "cancelled"
        return "failed"
    started = int(getattr(job, "progress", 0) or 0) > 0 or any(
        v in (const.REELFORGE_STAGE_RUNNING, const.REELFORGE_STAGE_COMPLETE)
        for v in stages.values()
    )
    return "running" if started else "pending"


def _job_progress(job: Any, stages: dict[str, str], status: str) -> dict[str, Any]:
    kind = str(getattr(job, "kind", "") or "avatar_reel")
    # The reel DAG runs every stage but ``upload`` (publishing happens after the
    # render through the owner's connections); other kinds report their own map.
    reel_total = len(const.REELFORGE_DAG) - 1 if kind == "avatar_reel" else 1
    total = max(len(stages), reel_total)
    done = sum(1 for v in stages.values() if v == const.REELFORGE_STAGE_COMPLETE)
    running = [k for k, v in stages.items() if v == const.REELFORGE_STAGE_RUNNING]
    if status == "completed":
        message, done = "Done", total
    elif status == "cancelled":
        message = "Cancelled"
    elif status == "failed":
        message = f"Failed at {getattr(job, 'failed_stage', '') or 'an unknown stage'}"
    elif running:
        message = f"Running: {', '.join(running)}"
    else:
        message = "Queued"
    percentage = 100 if status == "completed" else int(getattr(job, "progress", 0) or 0)
    return {
        "current": done,
        "total": total,
        "percentage": max(0, min(100, percentage)),
        "message": message,
    }


def job_to_task(job: Any) -> dict[str, Any]:
    """Normalize a ``Job`` row to the task-queue wire schema."""
    stages = _public_stages(job)
    status = _job_status(job, stages)
    params = getattr(job, "params", None)
    params = params if isinstance(params, dict) else {}
    request_params = {
        k: v for k, v in params.items() if not str(k).startswith("_")
    }
    is_terminal = status in ("completed", "failed", "cancelled")
    return {
        "task_id": job.id,
        "task_type": str(getattr(job, "kind", "") or "avatar_reel"),
        "source": "job",
        "status": status,
        "progress": _job_progress(job, stages, status),
        "result": (
            {"job_id": job.id, "stages": stages, "has_result": bool(job.result_key)}
            if status == "completed"
            else None
        ),
        "error": (job.error or None) if status in ("failed", "cancelled") else None,
        "created_at": _iso(getattr(job, "created_at", None)),
        "started_at": _iso(getattr(job, "created_at", None)) if status != "pending" else None,
        "completed_at": _iso(getattr(job, "updated_at", None)) if is_terminal else None,
        "request_params": request_params or None,
    }


def _legacy_file_uri(path: str) -> str:
    """Turn a legacy artifact path into its owner-only ``/api/v1/stream`` URL."""
    if path.startswith(("http://", "https://")):
        return path
    tasks_root = os.path.realpath(utils.task_dir())
    real = os.path.realpath(path)
    if os.path.commonpath([tasks_root, real]) != tasks_root:
        return ""
    rel = os.path.relpath(real, tasks_root).replace("\\", "/")
    return f"/api/v1/stream/{rel}"


def legacy_to_task(task: dict) -> dict[str, Any]:
    """Normalize a legacy MoneyPrinter state record to the task-queue schema."""
    state = task.get("state")
    try:
        state = int(state)
    except (TypeError, ValueError):
        state = const.TASK_STATE_PROCESSING
    try:
        progress = max(0, min(100, int(task.get("progress") or 0)))
    except (TypeError, ValueError):
        progress = 0
    if state == const.TASK_STATE_COMPLETE:
        status, message = "completed", "Done"
    elif state == const.TASK_STATE_FAILED:
        status, message = "failed", f"Failed at {task.get('failed_stage') or 'unknown'}"
    else:
        status = "running" if progress > 0 else "pending"
        message = "Running" if progress > 0 else "Queued"
    result = None
    if status == "completed":
        result = {}
        for key in ("videos", "combined_videos"):
            files = task.get(key)
            if isinstance(files, list):
                result[key] = [u for u in (_legacy_file_uri(str(f)) for f in files) if u]
        result = result or None
    return {
        "task_id": str(task.get("task_id") or ""),
        "task_type": "video_generation",
        "source": "legacy",
        "status": status,
        "progress": {
            "current": progress,
            "total": 100,
            "percentage": progress,
            "message": message,
        },
        "result": result,
        "error": (str(task.get("error") or "") or None) if status == "failed" else None,
        "created_at": None,
        "started_at": None,
        "completed_at": None,
        "request_params": None,
    }


def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or JobRepository is None:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _owned_legacy_tasks(user_id: str) -> list[dict]:
    if sm is None:
        return []
    try:
        tasks, _total = sm.state.get_all_tasks(1, _MAX_SCAN)
    except Exception as exc:  # noqa: BLE001 - legacy state is best-effort here
        logger.warning(f"legacy task listing failed: {exc}")
        return []
    return [
        task
        for task in tasks
        if owns_task(str(task.get("task_id") or ""), user_id)
    ]


@router.get("/tasks", summary="List the caller's async tasks (newest first)")
def list_tasks(
    request: Request,
    status: str | None = Query(None, description="pending|running|completed|failed|cancelled"),
    limit: int = Query(100, ge=1, le=1000),
    user_id: str = Depends(require_caller),
):
    request_id = base.get_task_id(request)
    if status is not None and status not in TASK_STATUSES:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: status must be one of {', '.join(TASK_STATUSES)}",
        )
    _require_db(request_id)
    with get_session() as session:
        rows = JobRepository(session).list_for_user(user_id, limit=limit, offset=0)
        items = [job_to_task(job) for job in rows]
    items.extend(legacy_to_task(task) for task in _owned_legacy_tasks(user_id))
    if status is not None:
        items = [item for item in items if item["status"] == status]
    # Newest first; legacy records carry no timestamp and sort last.
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    items = items[:limit]
    return utils.get_response(200, {"tasks": items, "total": len(items)})


@router.get("/tasks/{task_id}", summary="Get one of the caller's tasks")
def get_task(
    request: Request,
    task_id: str = Path(..., description="Task ID (a job id or legacy task id)"),
    user_id: str = Depends(require_caller),
):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        job = JobRepository(session).get(task_id)
        if job is not None and str(job.user_id) == user_id:
            return utils.get_response(200, job_to_task(job))
    if sm is not None and owns_task(task_id, user_id):
        task = sm.state.get_task(task_id)
        if task:
            return utils.get_response(200, legacy_to_task(task))
    raise HttpException(
        task_id=request_id, status_code=404, message=f"{request_id}: task not found"
    )


def _cancel_legacy(task_id: str, request_id: str) -> dict:
    task = sm.state.get_task(task_id) if sm is not None else None
    if not task:
        raise HttpException(
            task_id=request_id, status_code=404, message=f"{request_id}: task not found"
        )
    if tm is not None and tm.is_task_busy(task):
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message=f"{request_id}: this task is already rendering and cannot be stopped",
        )
    current_task_dir = os.path.join(utils.task_dir(), task_id)
    if os.path.isdir(current_task_dir):
        shutil.rmtree(current_task_dir, ignore_errors=True)
    sm.state.delete_task(task_id)
    return {"success": True, "message": "Task removed."}


@router.delete("/tasks/{task_id}", summary="Cancel one of the caller's tasks")
def cancel_task(
    request: Request,
    task_id: str = Path(..., description="Task ID (a job id or legacy task id)"),
    user_id: str = Depends(require_caller),
):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        job = JobRepository(session).get(task_id)
        is_owned_job = (
            job is not None
            and str(job.user_id) == user_id
            and getattr(job, "deleted_at", None) is None
        )
    if is_owned_job:
        # Shared with POST /jobs/{id}/cancel: commit the cancelled FAILED state,
        # revoke the chain, release a wallet hold, and refund a credit-funded
        # reel's debit exactly once to the pool it came from.
        from app.domains.reels.refunds import cancel_job

        result = cancel_job(task_id, user_id, request_id, any_kind=True)
        message = "Task cancelled."
        if result.get("refunded_credits"):
            message = f"Task cancelled. {result['refunded_credits']} credit(s) refunded."
        return utils.get_response(200, {"success": True, "message": message, **result})
    if owns_task(task_id, user_id):
        return utils.get_response(200, _cancel_legacy(task_id, request_id))
    raise HttpException(
        task_id=request_id, status_code=404, message=f"{request_id}: task not found"
    )
