"""Speak Studio API controller — async image + narration audio → talking video.

A creator submits an OWNED reference image + an OWNED narration audio clip and
gets back a *generation* they poll to completion. Because a lipsync render is
tens of seconds of GPU, generation is **async** — one ``Job(kind="speak_lipsync")``
per request on the dedicated ``generation`` queue — so the request returns
immediately instead of risking a gateway timeout (the load-bearing B-roll
pattern; mirrors ``domains/broll/router.py``).

Routes (all under ``/api/v1``):

* ``POST /generation/speak/generate`` — auth → per-user rate limit → moderation
  → OWNERSHIP of BOTH ``image_key`` AND ``audio_key`` → license-class gate
  (paid output must be commercial-safe) → atomic credit debit committed BEFORE
  enqueue → ``Job`` create → enqueue → return the generation id + initial state.
* ``GET /generation/speak/generations/{gid}`` — owner-scoped poll (state/progress
  and, once complete, the rendered ``talking_video_key``).
* ``GET /generation/speak/providers`` — the bounded lipsync selectors + each
  provider's capability + license class.

Credit discipline mirrors the B-roll studio: the debit is committed *before* the
task is enqueued (a generation can never run for free); an enqueue failure
refunds via :func:`app.domains.speak.service.refund_speak_generation`. The
generation IS a ``Job``, so ``result_key`` carries the finished talking-video key
and the existing job download/presign flow serves it.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.auth import resolve_principal
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.base import get_session
from app.models.exception import HttpException
from app.models.schema import (
    SpeakGenerateRequest,
    SpeakGenerationResponse,
    SpeakProvidersResponse,
)
from app.domains.media.service import MediaDomainError, require_owned_asset
from app.domains.speak.licensing import (
    LicenseClassError,
    license_class_for,
    require_commercial_ok,
)
from app.domains.speak.selection import (
    NoLipsyncProviderError,
    choose_lipsync_provider,
)
from app.domains.speak.workflows import (
    approved_provider_keys,
    product_engine_capability,
    require_approved_provider,
)
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

# ``Job.kind`` discriminator for a standalone speak generation.
_SPEAK_GEN_KIND: str = "speak_lipsync"


# Defaults (all config-overridable via the ``[app]`` section). A lipsync render is
# GPU-heavy, so it is priced and rate-limited like the B-roll studio.
_DEFAULT_SPEAK_GEN_RATE_LIMIT: int = 20
_DEFAULT_SPEAK_GEN_RATE_WINDOW_S: int = 3600


def _require_db(_request_id: str) -> None:
    """The canonical product app requires its persistence package at startup."""


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


#: Driving-audio length the AI-video reservation is priced for (seconds).
_RESERVE_SECONDS: float = 60.0


def _speak_provider_usd(provider: str) -> float:
    """Estimated presenter-provider cost of one lipsync render (USD)."""
    from app.telemetry.cost import estimate_avatar_cost

    return float(estimate_avatar_cost(_RESERVE_SECONDS, provider or "default"))


def _speak_ai_video_credits(provider: str) -> int:
    """AI-video credits per lipsync render: 3x the provider cost, in cents.

    A standard reel credit never pays for a presenter provider call.
    """
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    return max(1, ai_video_credits_for_usd(_speak_provider_usd(provider)))


def _speak_gen_rate_limit() -> int:
    return int(
        config.app.get("reelforge_speak_gen_rate_limit", _DEFAULT_SPEAK_GEN_RATE_LIMIT)
    )


def _speak_gen_rate_window_s() -> int:
    return int(
        config.app.get(
            "reelforge_speak_gen_rate_window_s", _DEFAULT_SPEAK_GEN_RATE_WINDOW_S
        )
    )


def _verify_ownership(session: Any, user_id: str, key: str, request_id: str) -> None:
    """BOLA guard: ``key`` must be an upload the caller owns (image or audio)."""
    try:
        require_owned_asset(session, user_id=user_id, key=key)
    except MediaDomainError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc


def _available_providers() -> set[str]:
    """Lipsync provider keys available to route now.

    Honors the routing registry (only providers with configured credentials at
    startup) intersected with the reviewed lipsync allowlist. Falls back to the
    full reviewed allowlist when the registry is empty (fresh deploy / tests) so
    selection stays deterministic and the feature is never dark by default.
    """
    approved = approved_provider_keys()
    try:
        from app.domains.routing.base import registry

        registered = {k for k in registry.keys() if k in approved}
        if registered:
            return registered
    except Exception as exc:  # noqa: BLE001 - registry read is best-effort
        logger.debug(f"speak_gen: registry unavailable, using allowlist: {exc}")
    return set(approved)


def _resolve_provider(requested: str, request_id: str) -> str:
    """Resolve + validate the lipsync provider for this render (paid output).

    A client-supplied provider must be on the reviewed allowlist; an empty
    selector is resolved deterministically. The chosen provider must then pass
    the commercial license gate so a paid talking video can never route to
    research-only weights (§8).
    """
    requested = (requested or "").strip()
    available = _available_providers()
    if requested:
        require_approved_provider(requested, request_id)
        provider = requested.lower()
    else:
        try:
            provider = choose_lipsync_provider(
                {}, {}, commercial=True, available=available
            )
        except NoLipsyncProviderError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=503,
                message=f"{request_id}: no lipsync provider is available",
            ) from exc
    if provider not in available:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: lipsync provider {provider!r} is not available",
        )
    try:
        require_commercial_ok(provider)
    except LicenseClassError as exc:
        # A paid render on non-commercial weights is a hard 400 (never billed).
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: {exc}",
        ) from exc
    return provider


def _generation_snapshot(job: Any, correlation_id: str = "") -> dict[str, Any]:
    """Build the ``SpeakGeneration`` payload from a ``speak_lipsync`` job row."""
    talking_video_key = job.result_key if job.state == TASK_STATE_COMPLETE else ""
    result_url = ""
    if talking_video_key:
        try:
            from app.platform.storage.r2 import get_r2_client

            result_url = get_r2_client().presign_result_get(talking_video_key)
        except Exception as exc:  # noqa: BLE001 - preview is best-effort
            logger.warning(f"speak_gen preview presign failed for {job.id}: {exc}")
    params = job.params if isinstance(job.params, dict) else {}
    stable_correlation_id = str(params.get("_correlation_id") or correlation_id)
    data = {
        "generation_id": job.id,
        "state": job.state,
        "progress": job.progress,
        "talking_video_key": talking_video_key or "",
        "result_url": result_url,
        "provider": str(params.get("provider") or ""),
        "license_class": str(params.get("license_class") or ""),
        "error": job.error or "",
        "retry_eligible": False,
    }
    if stable_correlation_id:
        data["correlation_id"] = stable_correlation_id
    return data


@router.post(
    "/generation/speak/generate",
    response_model=SpeakGenerationResponse,
    summary="Generate a talking video from an image + narration audio (async)",
)
def generate_speak(request: Request, body: SpeakGenerateRequest):
    """Start one async speak (lipsync) generation; returns the generation id.

    Order: auth → per-user rate limit → moderation → OWNERSHIP of BOTH image_key
    and audio_key (403) → license-class gate (400) → atomic ``Job`` create +
    credit debit (402 on insufficient) → enqueue on the ``generation`` queue →
    return the initial state. The debit is committed before enqueue so a
    generation can never run for free; an enqueue failure refunds it.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)

    image_key = (body.image_key or "").strip()
    audio_key = (body.audio_key or "").strip()
    if not image_key:
        raise HttpException(
            task_id=request_id, status_code=400,
            message=f"{request_id}: image_key is required",
        )
    if not audio_key:
        raise HttpException(
            task_id=request_id, status_code=400,
            message=f"{request_id}: audio_key is required",
        )

    # Resolve + license-gate the provider BEFORE any debit (paid output must be
    # commercial-safe; a bad selector never charges the user).
    provider = _resolve_provider((body.provider or ""), request_id)
    license_class = license_class_for(provider)
    ai_credits = _speak_ai_video_credits(provider)

    from app.core.capabilities import require_generation_access
    from app.models.db.repositories import JobRepository
    from app.services.billing import premium_credits

    # One committed transaction: verify ownership of BOTH inputs, create the job,
    # and debit. Any failure rolls back — no orphan job, no partial debit.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        # Speak is a generation capability; it shares the B-roll pilot access
        # budget (the capabilities gate has no separate speak kind).
        require_generation_access(request, session, user.id, "broll", 0, request_id)
        enforce_rate_limit(
            request,
            f"speak_gen:{user.id}",
            limit=_speak_gen_rate_limit(),
            window_s=_speak_gen_rate_window_s(),
        )
        # BOLA: both the reference image AND the driving audio must be uploads the
        # caller owns — validated before any debit/enqueue (§8 ownership boundary).
        _verify_ownership(session, user.id, image_key, request_id)
        _verify_ownership(session, user.id, audio_key, request_id)

        params: dict[str, Any] = {
            "_correlation_id": request_id,
            "image_key": image_key,
            "audio_key": audio_key,
            "provider": provider,
            "license_class": license_class.value if license_class else "",
            # No standard credit is charged; the AI-video credits reserved here
            # are returned by the failure path (premium_credits.refund_job_once).
            "credits_cost": 0,
            "ai_video_credits": ai_credits,
            "provider_usd_estimate": _speak_provider_usd(provider),
            "workspace_id": None,
        }
        job = JobRepository(session).create(
            user_id=user.id, kind=_SPEAK_GEN_KIND, params=params
        )
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
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=(
                    f"{request_id}: AI presenter clips use AI-video credits: this needs "
                    f"{exc.needed}, you have {exc.available}."
                ),
                data={"code": "ai_video_credits_required", "needed": exc.needed, "available": exc.available},
            )
        gid = job.id
        snapshot = _generation_snapshot(job, request_id)

    # Debit committed — safe to enqueue. An enqueue failure refunds + fails.
    try:
        _enqueue_generation(gid, request_id)
    except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a paid job
        logger.error(
            f"speak_gen enqueue failed for job {gid}, request_id={request_id}: {exc}"
        )
        _reconcile_failed_generation(gid, request_id)
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to enqueue generation",
        )

    return utils.get_response(200, snapshot)


def _enqueue_generation(gid: str, request_id: str) -> None:
    """Enqueue the speak generation task and record its celery id."""
    from app.workers.tasks import generate_speak_lipsync_task

    async_result = generate_speak_lipsync_task.apply_async(
        args=[{"job_id": gid, "request_id": request_id}],
        headers={"correlation_id": request_id},
    )
    with get_session() as session:
        from app.models.db.repositories import JobRepository

        JobRepository(session).set_celery_task_id(gid, async_result.id)


def _reconcile_failed_generation(job_id: str, request_id: str) -> None:
    """Mark a generation failed and refund its debit after an enqueue failure."""
    try:
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).mark_failed(job_id, "enqueue", "failed to enqueue")
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.error(f"speak_gen: mark_failed on enqueue failure failed: {exc}")
    try:
        from app.domains.speak.service import refund_speak_generation

        refund_speak_generation(job_id)
    except Exception as exc:  # noqa: BLE001 - best-effort refund
        logger.error(
            f"speak_gen: refund on enqueue failure failed for {job_id}, "
            f"request_id={request_id}: {exc}"
        )


@router.get(
    "/generation/speak/generations/{generation_id}",
    response_model=SpeakGenerationResponse,
    summary="Poll a speak (lipsync) generation",
)
def get_speak_generation(
    request: Request,
    generation_id: str = Path(..., description="Generation (job) id"),
):
    """Return one generation's state/progress (and ``talking_video_key`` once done).

    Owner-scoped: a generation is a ``Job(kind='speak_lipsync')``, so an unknown,
    foreign, or non-``speak_lipsync`` id returns ``404`` with no existence leak.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = JobRepository(session).get(generation_id)
        if job is None or job.user_id != user.id or job.kind != _SPEAK_GEN_KIND:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: generation not found",
            )
        snapshot = _generation_snapshot(job)
    return utils.get_response(200, snapshot)


@router.get(
    "/generation/speak/providers",
    response_model=SpeakProvidersResponse,
    summary="List the bounded lipsync providers + license classes",
)
def list_speak_providers(request: Request):
    """Return the bounded lipsync selectors + capability + per-provider license class.

    Availability is intersected with the routing registry so the UI only offers a
    provider that can actually route now.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    capability = product_engine_capability().get("speak", {})
    available = _available_providers()
    providers = [
        {**p, "available": p.get("provider") in available}
        for p in capability.get("providers", [])
    ]
    data = {
        "modes": capability.get("modes", []),
        "runtime": capability.get("runtime", ""),
        "providers": providers,
    }
    return utils.get_response(200, data)
