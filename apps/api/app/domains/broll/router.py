"""AI B-roll Studio API controller — async text/image → motion clip generation.

Complements the job-scoped ``POST /jobs/{id}/broll/suggest`` (which derives
prompts server-side and can run stock *or* AI) with a **standalone studio**: a
creator submits a free-text prompt (or an owned reference image for i2v) and gets
back a generation they poll to completion. Because a ComfyUI/Wan clip is
30-120s of GPU, generation is **async** — one ``Job(kind="broll_gen")`` per
request on the dedicated ``generation`` queue — so the request returns immediately instead of
risking a gateway timeout.

Routes (all under ``/api/v1``):

* ``POST /generation/broll/generate`` — auth → rate-limit → prompt moderation → (i2v) image
  ownership → atomic credit debit + ``Job`` create → enqueue → return the
  generation id + initial state.
* ``GET /generation/broll/generations/{gid}`` — owner-scoped poll of one generation
  (state/progress and, once complete, the rendered ``broll_key``).

Design notes
------------
* Reuses the guarded persistence + auth helpers from ``jobs.py`` and the image
  ownership guard from ``studio.py`` (import-safe: a missing DB layer degrades to
  a clean ``503``).
* Credit discipline mirrors ``jobs.create_job``: debit is committed *before* the
  task is enqueued (a generation can never run for free); an enqueue failure
  refunds via :func:`app.domains.broll.service.refund_broll_generation`.
* The generation IS a ``Job``, so ``result_key`` carries the finished clip key
  and the existing job download/presign flow serves it for free.

The same handlers declare both route families. New clients use
``/api/v1/generation/broll/*``; the deprecated ``/api/v1/broll/*`` paths remain
an alias-only compatibility surface with identical envelopes.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.auth import resolve_principal
from app.core.idempotency import (
    hash_request_payload,
    read_idempotency_key,
    reserve_idempotency_key,
)
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.base import get_session
from app.models.exception import HttpException
from app.models.schema import (
    BrollGenerateRequest,
    BrollGenerationResponse,
    BrollGenerationsResponse,
    BrollPresetsResponse,
    VideoAspect,
)
from app.domains.broll.workflows import require_approved_workflow
from app.domains.media.service import MediaDomainError, require_owned_asset
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()


def _require_db(_request_id: str) -> None:
    """The canonical product app requires its persistence package at startup."""


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


def _verify_image_ownership(
    session: Any, user_id: str, image_key: str, request_id: str
) -> None:
    try:
        require_owned_asset(session, user_id=user_id, key=image_key)
    except MediaDomainError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc


# ``Job.kind`` discriminator for a standalone studio generation.
_BROLL_GEN_KIND: str = "broll_gen"

_MODE_T2V: str = "t2v"
_MODE_I2V: str = "i2v"
_VALID_MODES: frozenset[str] = frozenset({_MODE_T2V, _MODE_I2V})

_BROLL_GEN_REFUND_REASON: str = "broll_gen_refund"

# Defaults (all config-overridable via the ``[app]`` section). AI generation is
# far costlier than a stock fetch, so it is priced and rate-limited tighter.
_DEFAULT_BROLL_GEN_COST: int = 5
_DEFAULT_BROLL_GEN_RATE_LIMIT: int = 20
_DEFAULT_BROLL_GEN_RATE_WINDOW_S: int = 3600

_DEFAULT_CLIP_SECONDS: float = 5.0

# Minimal prompt-safety denylist (v1). A cheap pre-filter that blocks the most
# clearly-prohibited categories before spending GPU; not a substitute for a full
# moderation model, which is the intended follow-up (§8 prompt safety).
_PROMPT_DENYLIST: tuple[str, ...] = (
    "child sexual",
    "csam",
    "child porn",
    "underage",
)


#: Estimated provider cost of one AI clip (Replicate), USD. Overridable with
#: ``AI_VIDEO_CLIP_COST_USD`` once real per-clip spend is measured.
_DEFAULT_CLIP_PROVIDER_USD: float = 0.50


def _clip_provider_usd() -> float:
    import os

    raw = (os.getenv("AI_VIDEO_CLIP_COST_USD") or "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        logger.warning("invalid AI_VIDEO_CLIP_COST_USD; using the default estimate")
    return _DEFAULT_CLIP_PROVIDER_USD


def _broll_ai_video_credits() -> int:
    """AI-video credits per generation: 3x the provider cost, in cents.

    A standard reel credit never pays for an AI-video provider call, so AI
    B-roll is charged to the separate AI-video credit balance.
    """
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    return max(1, ai_video_credits_for_usd(_clip_provider_usd()))


def _broll_gen_rate_limit() -> int:
    return int(
        config.app.get("reelforge_broll_gen_rate_limit", _DEFAULT_BROLL_GEN_RATE_LIMIT)
    )


def _broll_gen_rate_window_s() -> int:
    return int(
        config.app.get(
            "reelforge_broll_gen_rate_window_s", _DEFAULT_BROLL_GEN_RATE_WINDOW_S
        )
    )


def _aspect_dimensions(aspect: VideoAspect | None) -> tuple[int, int]:
    """Map an aspect to ``(width, height)``; default portrait 1080x1920."""
    if aspect == VideoAspect.landscape:
        return 1920, 1080
    if aspect == VideoAspect.square:
        return 1080, 1080
    return 1080, 1920


def _moderate_prompt(prompt: str, request_id: str) -> None:
    """Reject clearly-prohibited prompts with a ``400`` before any GPU spend."""
    lowered = prompt.lower()
    if any(term in lowered for term in _PROMPT_DENYLIST):
        logger.warning(
            f"broll_gen: rejected disallowed prompt, request_id={request_id}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: prompt violates content policy",
        )


def _require_enabled_provider(request_id: str) -> None:
    """Fail clean when the ``broll_gen`` provider is not configured.

    Checked BEFORE any credit debit so a disabled feature never charges a user.
    A deliberately disabled (``BROLL_GEN_PROVIDER=none``, free public tier) or
    unconfigured provider is a locked premium format -> ``402 format_locked``;
    a registry/import failure stays a ``503``.
    """
    import os

    from app.core.launch.formats import raise_format_locked

    if (os.getenv("BROLL_GEN_PROVIDER") or "").strip().lower() == "none":
        raise_format_locked(request_id, "ai_broll", "AI B-roll is not enabled")
    try:
        from app.domains.broll import get_broll_provider

        provider = get_broll_provider()
    except Exception as exc:  # noqa: BLE001 - no provider registered
        logger.error(f"broll_gen provider unavailable, request_id={request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: AI B-roll generation is not available",
        )
    if not provider.is_enabled():
        raise_format_locked(request_id, "ai_broll", "AI B-roll generation is not configured")


def _generation_snapshot(job: Any, correlation_id: str = "") -> dict[str, Any]:
    """Build the ``BrollGeneration`` payload from a ``broll_gen`` job row."""
    broll_key = job.result_key if job.state == TASK_STATE_COMPLETE else ""
    result_url = ""
    if broll_key:
        try:
            from app.platform.storage.r2 import get_r2_client

            result_url = get_r2_client().presign_result_get(broll_key)
        except Exception as exc:  # noqa: BLE001 - preview is best-effort
            logger.warning(f"broll_gen preview presign failed for {job.id}: {exc}")
    params = job.params if isinstance(job.params, dict) else {}
    stable_correlation_id = str(params.get("_correlation_id") or correlation_id)
    data = {
        "generation_id": job.id,
        "state": job.state,
        "progress": job.progress,
        "broll_key": broll_key or "",
        "result_url": result_url,
        "duration": float(params.get("duration_s") or 0.0),
        "error": job.error or "",
        # Failed B-roll generations are refunded and can be resubmitted from the
        # retained studio inputs. They are not retried in-place by the reel DAG.
        "retry_eligible": False,
    }
    if stable_correlation_id:
        data["correlation_id"] = stable_correlation_id
    return data


def _preset_public_data(preset: Any) -> dict[str, Any]:
    """Project a ``BrollPreset`` row to its public studio-picker shape."""
    return {
        "id": preset.id,
        "name": preset.name,
        "description": preset.description or "",
        "mode": preset.mode or _MODE_T2V,
        "prompt_template": preset.prompt_template or "",
        "thumbnail_url": preset.thumbnail_url or "",
        "workflow_id": preset.workflow_id or "",
        "default_params": dict(preset.default_params or {}),
    }


@router.get(
    "/broll/presets",
    response_model=BrollPresetsResponse,
    summary="List available AI B-roll motion presets",
    deprecated=True,
)
@router.get(
    "/generation/broll/presets",
    response_model=BrollPresetsResponse,
    summary="List available AI B-roll motion presets",
)
def list_broll_presets(request: Request):
    """Return the caller's available motion presets (global/public + their own).

    Owner-scoped via :meth:`BrollPresetRepository.list_available` — another user's
    PRIVATE preset is never returned. Curated global presets lead the list.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    from app.models.db.repositories import BrollPresetRepository

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        presets = BrollPresetRepository(session).list_available(user.id)
        data = [_preset_public_data(p) for p in presets]
    return utils.get_response(200, data)


@router.post(
    "/broll/generate",
    response_model=BrollGenerationResponse,
    summary="Generate an AI B-roll clip (async studio generation)",
    deprecated=True,
)
@router.post(
    "/generation/broll/generate",
    response_model=BrollGenerationResponse,
    summary="Generate an AI B-roll clip (async studio generation)",
)
def generate_broll(request: Request, body: BrollGenerateRequest):
    """Start one async AI B-roll generation; returns the generation id to poll.

    Order: auth → per-user rate limit → provider-configured (402 format_locked) → prompt
    moderation (400) → i2v image ownership (403) → atomic ``Job`` create + credit
    debit (402 on insufficient) → enqueue on the ``generation`` queue → return the
    initial state. The debit is committed before enqueue so a generation can
    never run for free; an enqueue failure refunds it.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    idempotency_key = read_idempotency_key(request, request_id)
    request_hash = (
        hash_request_payload(
            {"operation": "broll_generate", "body": body.model_dump(mode="json")}
        )
        if idempotency_key
        else ""
    )

    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: prompt is required",
        )

    mode = (body.mode or _MODE_T2V).strip().lower() or _MODE_T2V
    if mode not in _VALID_MODES:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: mode must be one of {sorted(_VALID_MODES)}",
        )
    image_key = (body.image_key or "").strip()
    if mode == _MODE_I2V and not image_key:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: i2v generation requires image_key",
        )

    _moderate_prompt(prompt, request_id)
    require_approved_workflow((body.workflow_id or "").strip(), request_id)
    _require_enabled_provider(request_id)

    ai_credits = _broll_ai_video_credits()
    width, height = _aspect_dimensions(body.aspect)

    # One committed transaction: verify ownership, create the job, and debit.
    # Any failure rolls back — no orphan job, no partial debit, nothing enqueued.
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        from app.core.capabilities import require_generation_access

        idempotency_row = None
        if idempotency_key is not None:
            idempotency_row, replay = reserve_idempotency_key(
                session,
                str(user.id),
                idempotency_key,
                request_hash,
                request_id,
            )
            if replay is not None:
                return utils.get_response(200, replay)
        # Standard credits are not touched (0); the pilot gate still applies.
        require_generation_access(request, session, user.id, "broll", 0, request_id)
        enforce_rate_limit(
            request,
            f"broll_gen:{user.id}",
            limit=_broll_gen_rate_limit(),
            window_s=_broll_gen_rate_window_s(),
        )
        if mode == _MODE_I2V:
            # BOLA: the i2v reference must be an upload the caller owns.
            _verify_image_ownership(session, user.id, image_key, request_id)

        # Owner-approved spend protection: consume one per-user + global UTC-day
        # capacity slot (429 "at capacity today" when exhausted; fail-closed 503
        # when Redis cannot confirm). Runs AFTER the idempotency replay check so
        # a transport retry never double-counts, and BEFORE the job/debit so a
        # capped request charges nothing.
        from app.domains.broll.spend_caps import (
            enforce_ai_video_daily_caps,
            release_ai_video_slot,
        )

        enforce_ai_video_daily_caps(str(user.id), request_id)

        params: dict[str, Any] = {
            "_correlation_id": request_id,
            "prompt": prompt,
            "mode": mode,
            "image_key": image_key or None,
            "width": width,
            "height": height,
            "duration_s": _DEFAULT_CLIP_SECONDS,
            "seed": body.seed,
            "workflow_id": (body.workflow_id or "").strip() or None,
            # No standard credit is charged; the AI-video credits reserved here
            # are returned by the failure path (premium_credits.refund_job_once).
            "credits_cost": 0,
            "ai_video_credits": ai_credits,
            "provider_usd_estimate": _clip_provider_usd(),
            "workspace_id": None,
        }
        job = JobRepository(session).create(
            user_id=user.id, kind=_BROLL_GEN_KIND, params=params
        )
        from app.services.billing import premium_credits

        try:
            premium_credits.debit(
                session,
                str(user.id),
                premium_credits.KIND_AI_VIDEO,
                ai_credits,
                f"{premium_credits.DEBIT_REASON}:{job.id}",
                job.id,
            )
        except premium_credits.InsufficientPremiumCredits as exc:
            # No provider spend can happen — hand the day's capacity slot back.
            release_ai_video_slot(str(user.id))
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=(
                    f"{request_id}: AI video clips use AI-video credits: this needs "
                    f"{exc.needed}, you have {exc.available}."
                ),
                data={"code": "ai_video_credits_required", "needed": exc.needed, "available": exc.available},
            )
        gid = job.id
        snapshot = _generation_snapshot(job, request_id)
        if idempotency_row is not None:
            idempotency_row.response_data = snapshot
            session.flush()

    # Debit committed — safe to enqueue. An enqueue failure refunds + fails.
    try:
        from app.workers.tasks import generate_broll_clip_task

        async_result = generate_broll_clip_task.apply_async(
            args=[{"job_id": gid, "request_id": request_id}],
            headers={"correlation_id": request_id},
        )
        with get_session() as session:
            from app.models.db.repositories import JobRepository as _JR

            _JR(session).set_celery_task_id(gid, async_result.id)
    except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a paid job
        logger.error(
            f"broll_gen enqueue failed for job {gid}, request_id={request_id}: {exc}"
        )
        _reconcile_failed_generation(gid, request_id)
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to enqueue generation",
        )

    return utils.get_response(200, snapshot)


def _reconcile_failed_generation(job_id: str, request_id: str) -> None:
    """Mark a generation failed and refund its debit after an enqueue failure."""
    try:
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).mark_failed(job_id, "enqueue", "failed to enqueue")
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.error(f"broll_gen: mark_failed on enqueue failure failed: {exc}")
    try:
        from app.domains.broll.service import refund_broll_generation

        refund_broll_generation(job_id)
    except Exception as exc:  # noqa: BLE001 - best-effort refund
        logger.error(
            f"broll_gen: refund on enqueue failure failed for {job_id}, "
            f"request_id={request_id}: {exc}"
        )


@router.get(
    "/broll/generations",
    response_model=BrollGenerationsResponse,
    summary="List the caller's recent AI B-roll generations",
    deprecated=True,
)
@router.get(
    "/generation/broll/generations",
    response_model=BrollGenerationsResponse,
    summary="List the caller's recent AI B-roll generations",
)
def list_broll_generations(request: Request, limit: int = 30):
    """Return the caller's recent studio generations, newest first.

    Owner- and kind-scoped (``broll_gen`` jobs only). Used to surface completed
    AI clips for reuse — e.g. the reel B-roll picker attaches a finished clip's
    ``broll_key`` as an intro/outro without a copy-paste round-trip.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    from app.models.db.repositories import JobRepository

    bounded = max(1, min(100, int(limit)))
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        jobs = JobRepository(session).list_for_user_by_kind(
            user.id, _BROLL_GEN_KIND, limit=bounded
        )
        data = [_generation_snapshot(job) for job in jobs]
    return utils.get_response(200, data)


@router.get(
    "/broll/generations/{generation_id}",
    response_model=BrollGenerationResponse,
    summary="Poll an AI B-roll generation",
    deprecated=True,
)
@router.get(
    "/generation/broll/generations/{generation_id}",
    response_model=BrollGenerationResponse,
    summary="Poll an AI B-roll generation",
)
def get_broll_generation(
    request: Request,
    generation_id: str = Path(..., description="Generation (job) id"),
):
    """Return one generation's state/progress (and ``broll_key`` once complete).

    Owner-scoped: a generation is a ``Job(kind='broll_gen')``, so an unknown,
    foreign, or non-``broll_gen`` id returns ``404`` with no existence leak.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = JobRepository(session).get(generation_id)
        if job is None or job.user_id != user.id or job.kind != _BROLL_GEN_KIND:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: generation not found",
            )
        snapshot = _generation_snapshot(job)
    return utils.get_response(200, snapshot)
