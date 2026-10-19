"""Hook Performance Loop — v1 API controller.

Auth-gated, strictly caller-scoped endpoints under ``/api/v1`` that let a creator
LOG the real-world outcome of a reel they posted and read back the aggregated
"win score" signal the SPARK idea engine biases toward:

* ``POST /jobs/{job_id}/performance`` — log/update (idempotent upsert) the metrics
  the caller's OWN job earned. Ownership is verified in
  :func:`app.services.hook_performance.log_performance` BEFORE any write: a
  missing job is a clean ``404`` and a job owned by another creator is a ``403``
  (never a cross-user write). All numeric inputs are validated here (non-negative
  counts, ``retention_pct`` in ``[0, 100]``) and surface a clean ``400``.
* ``GET /jobs/{job_id}/performance`` — the caller's logged metrics for that job
  (owner-scoped in the repository; a missing/foreign id is a ``404``).
* ``GET /me/performance?limit=&offset=`` — list the caller's logged reels, newest
  first (owner-scoped; ``limit`` clamped ``[1, 100]``, ``offset`` ``>= 0``).
* ``GET /me/winning-hooks?limit=`` and ``GET /me/winning-templates?limit=`` — the
  caller's top hooks/templates by deterministic win score (``limit`` clamped
  ``[1, 100]``).

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard block behind the single ``base.verify_token`` gate) so both auth paths
  (Clerk JWT + ``x-api-key``) and the get-or-create behaviour are identical to the
  rest of the API and this module stays import-safe.
* **Import-safe optional deps.** The hook-performance service and repository are
  imported inside guarded blocks; when they are absent the endpoints degrade to a
  clean ``503`` at request time instead of an ``ImportError`` at startup
  (mirroring ``ideas.py`` / ``jobs.py``).
* **Every path traces back to ``_resolve_user(caller)``** — a creator can only log
  metrics for, or read aggregates of, their own jobs. No cross-user code path
  exists. Every response uses the MPT envelope ``utils.get_response`` and every
  error is raised as :class:`HttpException`. No secrets are hardcoded.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Query, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.models.schema import (
    JobPerformanceModel,  # noqa: F401 (re-exported: response_model reference)
    LogPerformanceRequest,
    PerformanceListResponse,
    WinningHooksResponse,
    WinningTemplatesResponse,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded optional imports (persistence + scoring; may be absent at compile
# time). Keeping them guarded makes the module import-safe: a missing dependency
# degrades to a clean 503 at request time instead of an ImportError at startup.
# --------------------------------------------------------------------------- #
try:
    from app.services import hook_performance as perf_service

    _PERF_SERVICE_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the service exists
    perf_service = None  # type: ignore[assignment]
    _PERF_SERVICE_IMPORT_ERROR = exc

try:
    from app.models.db.models import JobPerformance  # noqa: F401 (re-exported for tests)
    from app.models.db.repositories import JobPerformanceRepository

    _PERF_REPO_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    JobPerformance = None  # type: ignore[assignment,misc]
    JobPerformanceRepository = None  # type: ignore[assignment,misc]
    _PERF_REPO_IMPORT_ERROR = exc


router = new_router()

# --------------------------------------------------------------------------- #
# Tunables. The list/ranking limits are clamped so an untrusted query value can
# never request an unbounded scan.
# --------------------------------------------------------------------------- #
_LIMIT_MIN: int = 1
_LIMIT_MAX: int = 100
_DEFAULT_LIST_LIMIT: int = 50
_DEFAULT_WINNERS_LIMIT: int = 10

# The numeric metric keys a creator may log. Each is validated non-negative here
# before it ever reaches the repository (which clamps again, defense-in-depth).
_COUNT_KEYS: tuple[str, ...] = ("views", "likes", "comments", "shares", "saves")


def _clamp_limit(value: Any, default: int) -> int:
    """Clamp a requested page/ranking size into ``[1, 100]`` (default on garbage)."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(_LIMIT_MIN, min(parsed, _LIMIT_MAX))


def _clamp_offset(value: Any) -> int:
    """Clamp a requested offset to ``>= 0`` (0 on garbage)."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_perf_service(request_id: str) -> None:
    """Raise 503 when the hook-performance scoring service is unavailable."""
    if perf_service is None:
        logger.error(
            f"hook-performance service unavailable, request_id: {request_id}, "
            f"error: {_PERF_SERVICE_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: performance service is not available",
        )


def _require_perf_repo(request_id: str) -> None:
    """Raise 503 when the performance persistence layer is unavailable."""
    if _PERF_REPO_IMPORT_ERROR is not None or JobPerformanceRepository is None:
        logger.error(
            f"performance persistence unavailable, request_id: {request_id}, "
            f"error: {_PERF_REPO_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: performance storage is not available",
        )


def _validated_metrics(body: LogPerformanceRequest, request_id: str) -> dict:
    """Build the clamped metrics dict from the request, or raise a clean ``400``.

    Only fields the creator actually supplied are included (so a partial log
    leaves the other stored values untouched on re-log). Counts must be
    non-negative and ``retention_pct`` must lie in ``[0, 100]`` — an out-of-range
    value is a ``400`` here rather than a raw ``422`` so the error shape matches
    the rest of the API. The repository clamps again as defense-in-depth.
    """
    metrics: dict[str, Any] = {}

    platform = getattr(body, "platform", None)
    if platform is not None:
        metrics["platform"] = str(platform)

    for key in _COUNT_KEYS:
        value = getattr(body, key, None)
        if value is None:
            continue
        if int(value) < 0:
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: {key} must be non-negative",
            )
        metrics[key] = int(value)

    retention = getattr(body, "retention_pct", None)
    if retention is not None:
        retention_val = float(retention)
        if retention_val < 0.0 or retention_val > 100.0:
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: retention_pct must be between 0 and 100",
            )
        metrics["retention_pct"] = retention_val

    return metrics


def _performance_public_data(row: Any) -> dict:
    """Serialise a ``JobPerformance`` row to its public, JSON-safe envelope."""
    logged_at = getattr(row, "logged_at", None)
    updated_at = getattr(row, "updated_at", None)
    return {
        "id": row.id,
        "job_id": row.job_id,
        "platform": row.platform,
        "views": int(row.views or 0),
        "likes": int(row.likes or 0),
        "comments": int(row.comments or 0),
        "shares": int(row.shares or 0),
        "saves": int(row.saves or 0),
        "retention_pct": float(row.retention_pct or 0.0),
        "logged_at": logged_at.isoformat() if logged_at is not None else None,
        "updated_at": updated_at.isoformat() if updated_at is not None else None,
    }


# --------------------------------------------------------------------------- #
# POST /jobs/{job_id}/performance  (log / update)
# --------------------------------------------------------------------------- #
@router.post(
    "/jobs/{job_id}/performance",
    summary="Log (upsert) the real-world outcome of the caller's own reel",
)
def log_performance_endpoint(
    request: Request,
    body: LogPerformanceRequest,
    job_id: str = Path(..., description="The caller's own job ID"),
):
    """Log/update the metrics the caller's OWN job earned (idempotent upsert).

    Order: auth -> validate metrics (``400`` on a negative count / out-of-range
    retention) -> verify ownership + upsert. A missing job is a clean ``404`` and
    a job owned by another creator is a ``403`` (ownership is enforced in
    :func:`app.services.hook_performance.log_performance` before any write, so a
    guessed id can neither write to nor confirm another user's job).
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_perf_service(request_id)
    _require_perf_repo(request_id)

    metrics = _validated_metrics(body, request_id)

    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            row = perf_service.log_performance(
                session, user.id, job_id, metrics=metrics
            )
            data = _performance_public_data(row)
    except HttpException:
        raise
    except PermissionError:
        # The job exists but belongs to another creator — never a cross-user write.
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: job does not belong to the requesting user",
        )
    except ValueError:
        # Blank/unknown job id — indistinguishable from "not found" so a guessed
        # id can never confirm the existence of another user's job.
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: job not found",
        )
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to log performance, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to log performance",
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /jobs/{job_id}/performance  (read one)
# --------------------------------------------------------------------------- #
@router.get(
    "/jobs/{job_id}/performance",
    summary="Read the caller's logged metrics for their own job",
)
def get_performance_endpoint(
    request: Request,
    job_id: str = Path(..., description="The caller's own job ID"),
):
    """Return the caller's logged metrics for ``job_id``.

    Owner-scoped in the repository: a missing row, or a row belonging to another
    creator, is indistinguishable from "not found" (``404``) so a guessed id can
    never read another user's outcome.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_perf_repo(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row = JobPerformanceRepository(session).get_for_job(job_id, user.id)
        if row is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: performance not found",
            )
        data = _performance_public_data(row)

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /me/performance  (list)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/performance",
    response_model=PerformanceListResponse,
    summary="List the caller's logged reel outcomes (newest first)",
)
def list_performance_endpoint(
    request: Request,
    limit: int = Query(_DEFAULT_LIST_LIMIT, description="Max rows (1..100)"),
    offset: int = Query(0, description="Rows to skip (>= 0)"),
):
    """Return the caller's logged reel outcomes, newest first (scoped to caller)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_perf_repo(request_id)

    safe_limit = _clamp_limit(limit, _DEFAULT_LIST_LIMIT)
    safe_offset = _clamp_offset(offset)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = JobPerformanceRepository(session).list_for_user(
            user.id, limit=safe_limit, offset=safe_offset
        )
        data = [_performance_public_data(r) for r in rows]

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /me/winning-hooks
# --------------------------------------------------------------------------- #
@router.get(
    "/me/winning-hooks",
    response_model=WinningHooksResponse,
    summary="Rank the caller's hooks by aggregated win score",
)
def winning_hooks_endpoint(
    request: Request,
    limit: int = Query(_DEFAULT_WINNERS_LIMIT, description="Max hooks (1..100)"),
):
    """Return the caller's top hooks by deterministic win score (owner-scoped)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_perf_service(request_id)

    safe_limit = _clamp_limit(limit, _DEFAULT_WINNERS_LIMIT)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        data = perf_service.winning_hooks(session, user.id, limit=safe_limit)

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /me/winning-templates
# --------------------------------------------------------------------------- #
@router.get(
    "/me/winning-templates",
    response_model=WinningTemplatesResponse,
    summary="Rank the caller's templates by aggregated win score",
)
def winning_templates_endpoint(
    request: Request,
    limit: int = Query(_DEFAULT_WINNERS_LIMIT, description="Max templates (1..100)"),
):
    """Return the caller's top templates by deterministic win score (owner-scoped)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_perf_service(request_id)

    safe_limit = _clamp_limit(limit, _DEFAULT_WINNERS_LIMIT)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        data = perf_service.winning_templates(session, user.id, limit=safe_limit)

    return utils.get_response(200, data)
