"""ReelForge AI Social Caption & Hashtags controller.

Served under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`. For a
finished (or in-progress) reel this generates an optimized post ``title`` +
``caption`` + ``hashtags`` tailored to a target social platform so a creator can
copy them when posting.

Design notes
------------
* **Built on the vendored MPT LLM.** The heavy lifting is
  :func:`app.services.llm.generate_social_metadata` — the same helper the
  cross-post flow already uses for YouTube. This controller only handles auth,
  ownership, rate-limiting and platform validation, then delegates.
* **Per-user auth + ownership.** Mirrors ``jobs.py``: the caller is resolved to a
  ``User`` row (Clerk JWT or ``x-api-key``) and must OWN the job (404 with no
  existence leak otherwise). The subject/script the copy is built from come from
  the *job's own* persisted data, never from client input.
* **Rate-limited.** Each call spends LLM tokens, so it is capped per-user
  (default 30/hour, config-overridable) — fail-open if Redis is down.
* **Import-safe & never-crash.** The persistence layer and the LLM module are
  imported inside guarded blocks so merely importing this module never crashes
  app startup; a missing layer degrades to a clean 503 at request time and a
  generation failure to a clean 502 (never a 500 leak).
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import SocialRequest, SocialResponse
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import (authored by sibling agents; may be absent at
# compile time). Keeps this module import-safe — a missing layer degrades to a
# 503 at request time instead of an ImportError at startup (mirrors jobs.py).
# --------------------------------------------------------------------------- #
try:
    from app.models.db.base import get_session
    from app.models.db.models import User
    from app.models.db.repositories import JobRepository

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    get_session = None  # type: ignore[assignment]
    User = None  # type: ignore[assignment]
    JobRepository = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()

# The platforms the API accepts, mapped to the ``llm.SOCIAL_PLATFORMS`` id the
# generator is tuned for. Kept small + explicit (the task's contract is exactly
# ``tiktok`` / ``instagram`` / ``youtube_shorts``); ``instagram`` maps to the
# LLM's ``instagram_reels`` spec. ``name`` is UI copy for the catalog endpoint.
_SUPPORTED_PLATFORMS: dict[str, dict[str, str]] = {
    "tiktok": {"name": "TikTok", "llm_platform": "tiktok"},
    "instagram": {"name": "Instagram", "llm_platform": "instagram_reels"},
    "youtube_shorts": {"name": "YouTube Shorts", "llm_platform": "youtube_shorts"},
}

# Per-user social-metadata rate limit (fixed window). Each call spends LLM tokens
# so it gets its own budget, independent of job creation; both overridable.
_DEFAULT_SOCIAL_RATE_LIMIT: int = 30
_DEFAULT_SOCIAL_RATE_WINDOW_S: int = 3600


def _social_rate_limit() -> int:
    """Max social generations per window per user (config ``reelforge_social_rate_limit``)."""
    return int(
        config.app.get("reelforge_social_rate_limit", _DEFAULT_SOCIAL_RATE_LIMIT)
    )


def _social_rate_window_s() -> int:
    """Social rate-limit window in seconds (config ``reelforge_social_rate_window_s``)."""
    return int(
        config.app.get("reelforge_social_rate_window_s", _DEFAULT_SOCIAL_RATE_WINDOW_S)
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_db(request_id: str) -> None:
    """Raise 503 when the persistence layer could not be imported."""
    if _DB_IMPORT_ERROR is not None or get_session is None:
        logger.error(
            f"persistence layer unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    """Resolve the caller to a ``User`` row (Clerk JWT, else ``x-api-key``).

    Delegates to the shared ``jobs`` controller resolver so the two auth paths
    (get-or-create Clerk user / api-key hash) stay in lock-step and are never
    duplicated. Raises 401 when neither path yields a user.
    """
    from app.controllers.v1 import jobs as jobs_mod

    return jobs_mod._resolve_user(request, session, request_id)


def _resolve_platform(platform: str | None, request_id: str) -> dict[str, str]:
    """Validate + resolve the requested platform to its spec (400 on unknown).

    Accepts only the API-facing ids (``tiktok`` / ``instagram`` /
    ``youtube_shorts``); anything else is rejected with a clean 400 *before* any
    LLM token is spent, so a hostile/typo'd platform never reaches the generator.
    """
    value = (platform or "").strip().lower()
    spec = _SUPPORTED_PLATFORMS.get(value)
    if spec is None:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: unsupported platform {platform!r} "
                f"(allowed: {', '.join(sorted(_SUPPORTED_PLATFORMS))})"
            ),
        )
    return spec


def _job_social_context(job: Any) -> tuple[str, str, str]:
    """Extract the ``(subject, script, language)`` the copy is generated from.

    All three are derived from the *job's own* persisted data — never from client
    input — so the caller cannot inject an arbitrary prompt. ``subject`` is the
    job's ``video_subject``; ``script`` prefers the finalized narration
    (``Job.script``, written by the script stage) and falls back to any manual
    ``params.video_script``; ``language`` is the job's configured language.
    """
    params = dict(job.params) if isinstance(getattr(job, "params", None), dict) else {}
    subject = str(params.get("video_subject") or "").strip()
    script = (getattr(job, "script", "") or "").strip()
    if not script:
        script = str(params.get("video_script") or "").strip()
    language = str(params.get("language") or "").strip()
    return subject, script, language


def _import_llm(request_id: str):
    """Lazily import the vendored LLM module (503 when absent).

    Guarded like the ``jobs`` service imports so a missing / broken LLM module
    degrades to a clean 503 at request time instead of an ImportError at startup.
    """
    try:
        from app.services import llm

        return llm
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 503
        logger.error(f"llm module unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: caption generation is not available",
        )


def _generate_metadata(
    llm, subject: str, script: str, language: str, llm_platform: str, request_id: str
) -> dict[str, Any]:
    """Call ``llm.generate_social_metadata`` and normalise its result.

    Any generation failure is surfaced as a clean 502 (external dependency
    failure) rather than a 500 leak. The generator's own contract already falls
    back to a heuristic when the model is unavailable, so reaching this except
    branch means a truly unexpected error.
    """
    try:
        metadata = llm.generate_social_metadata(
            video_subject=subject,
            video_script=script,
            language=language,
            platform=llm_platform,
        )
    except Exception as exc:  # noqa: BLE001 - external LLM failure -> 502
        logger.error(
            f"social metadata generation failed, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to generate social metadata",
        )

    if not isinstance(metadata, dict):
        logger.error(
            f"social metadata generator returned {type(metadata)!r}, "
            f"request_id: {request_id}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: caption generator returned an invalid response",
        )

    hashtags = metadata.get("hashtags") or []
    if not isinstance(hashtags, list):
        hashtags = []
    return {
        "title": str(metadata.get("title") or ""),
        "caption": str(metadata.get("caption") or ""),
        "hashtags": [str(tag) for tag in hashtags],
    }


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
@router.post(
    "/jobs/{job_id}/social",
    response_model=SocialResponse,
    summary="Generate social caption + hashtags for a job",
)
def generate_social(
    request: Request,
    body: SocialRequest,
    job_id: str = Path(..., description="Job ID"),
):
    """Generate optimized post copy for a reel, tailored to a social platform.

    Order: auth -> ownership (404 on unknown/foreign job, no existence leak) ->
    per-user rate limit (each call spends LLM tokens) -> validate ``platform``
    (400 unless one of ``tiktok`` / ``instagram`` / ``youtube_shorts``) -> call
    ``llm.generate_social_metadata`` with the *job's own* subject/script and the
    requested (or job) language. Returns ``{title, caption, hashtags: [...]}``.
    A generation failure surfaces as a clean 502, never a 500.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)

    # Validate the platform up front (before touching the DB / LLM) so a bad
    # platform is a clean 400 with nothing spent.
    spec = _resolve_platform(body.platform, request_id)

    # Resolve auth + ownership + context inside the session, then close it before
    # the (slow, external) LLM call so we never hold a DB connection across I/O.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = JobRepository(session).get(job_id)
        if job is None or job.user_id != user.id:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        # Rate limit AFTER ownership so only the owner's own calls draw down their
        # budget. Fail-open if Redis is down (mirrors the jobs limiter).
        enforce_rate_limit(
            request,
            f"social:{user.id}",
            limit=_social_rate_limit(),
            window_s=_social_rate_window_s(),
        )
        subject, script, job_language = _job_social_context(job)

    llm = _import_llm(request_id)
    # A client-supplied language overrides the job's configured one; the generator
    # normalises/defaults an empty value to ``auto`` internally.
    language = (body.language or "").strip() or job_language

    data = _generate_metadata(
        llm, subject, script, language, spec["llm_platform"], request_id
    )
    return utils.get_response(200, data)
