"""Canonical ReelForge reel/job HTTP domain (INTEGRATION_CONTRACT.md §5).

Routes served under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`.
Every response uses the MPT envelope ``utils.get_response(status, data, message)``
and every error is raised as :class:`HttpException` so the shared exception
handler renders it consistently.

Design notes
------------
* **Per-user auth via ``x-api-key``.** ReelForge is multi-tenant, so instead of
  the single global-key ``base.verify_token`` gate we resolve the caller to a
  ``User`` row by SHA-256 of the ``x-api-key`` header (``User.api_key_hash``).
* **Import-safe.** The persistence / workers layers pull in SQLAlchemy + Celery
  and are authored by sibling agents; they are imported inside a guarded block
  (mirroring ``storage/r2.py``'s boto3 guard) so merely importing this module
  never crashes app startup. A clear ``503`` is returned when a layer is absent.
* **Never crash the pipeline.** External I/O (R2 presign, provider listing,
  pipeline enqueue) is wrapped; failures become typed HTTP errors, not 500 leaks.
"""

from __future__ import annotations

import dataclasses
import re
import uuid
from typing import Any

from fastapi import Path, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.auth import (
    get_or_create_clerk_user,
    resolve_clerk_principal,
    resolve_principal,
)
from app.core.idempotency import (
    IDEMPOTENCY_HEADER,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    hash_request_payload,
    read_idempotency_key,
    reserve_idempotency_key,
)
from app.models.const import (
    TASK_STATE_COMPLETE,
    TASK_STATE_FAILED,
    TASK_STATE_PROCESSING,
)
from app.models.exception import HttpException
from app.models.schema import (
    AvatarListResponse,
    BatchResponse,
    BrollSuggestRequest,
    BrollSuggestResponse,
    DubRequest,
    DubResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
    MeResponse,
    RerunRequest,
    VoiceListResponse,
)
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

from .policy import (
    DEFAULT_JOB_KIND as _DEFAULT_JOB_KIND,
    JOB_DEBIT_REASON as _JOB_DEBIT_REASON,
    JOB_REFUND_REASON as _JOB_REFUND_REASON,
    broll_rate_limit as _broll_rate_limit,
    broll_rate_window_s as _broll_rate_window_s,
    is_retryable_kind,
    charge_on_keep_enabled as _charge_on_keep_enabled,
    job_cost as _job_cost,
    job_credits as _job_credits,
    jobs_rate_limit as _jobs_rate_limit,
    jobs_rate_window_s as _jobs_rate_window_s,
    resolve_variants as _resolve_variants,
)
from .refunds import (
    CANCELLABLE_KINDS as _CANCELLABLE_KINDS,
    cancel_job as _cancel_job,
    is_cancelled as _is_cancelled,
)

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import (authored by sibling agents; may be absent
# at compile time). Keeps this module import-safe — a missing layer degrades to
# a 503 at request time instead of an ImportError at startup.
# --------------------------------------------------------------------------- #
try:
    from sqlalchemy import or_, select
    from sqlalchemy.exc import NotSupportedError

    from app.models.db.base import get_session
    from app.models.db.models import AvatarPreset, CreditLedger, Job, User
    from app.models.db.repositories import (
        CreditRepository,
        JobRepository,
    )
    from app.services import workspaces as ws_service

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    or_ = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]
    NotSupportedError = None  # type: ignore[assignment,misc]
    get_session = None  # type: ignore[assignment]
    AvatarPreset = CreditLedger = Job = User = None  # type: ignore[assignment]
    CreditRepository = JobRepository = None  # type: ignore[assignment]
    ws_service = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


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


def _hidden(job: Any, user: Any) -> bool:
    """True when ``job`` must 404 for ``user`` (missing, foreign, or deleted)."""
    return (
        job is None
        or job.user_id != user.id
        or getattr(job, "deleted_at", None) is not None
    )


def _resolve_user(request: Request, session: Any, request_id: str):
    """Compatibility alias for the shared principal resolver."""
    return resolve_principal(request, session, request_id)


def _resolve_user_via_clerk(request: Request, session: Any, request_id: str):
    """Compatibility alias for Clerk principal resolution."""
    return resolve_clerk_principal(request, session, request_id)


def _get_or_create_clerk_user(session: Any, claims: dict, request_id: str):
    """Compatibility alias for Clerk first-seen provisioning."""
    return get_or_create_clerk_user(session, claims, request_id)


def _import_reelforge(request_id: str):
    """Lazily import the ReelForge stage/DTO module (503 when absent)."""
    try:
        from app.services import reelforge

        return reelforge
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 503
        logger.error(f"reelforge module unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: pipeline module is not available",
        )


def _import_pipeline(request_id: str):
    """Lazily import the Celery pipeline module (503 when absent)."""
    try:
        from app.workers import pipeline

        return pipeline
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 503
        logger.error(f"pipeline module unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: task orchestration is not available",
        )


def _import_translate(request_id: str):
    """Lazily import the script-translation module (503 when absent).

    Guarded like the other service imports so a missing / broken translate
    module (it pulls in the LLM dispatch layer) degrades to a clean 503 at
    request time instead of an ImportError at startup.
    """
    try:
        from app.services import translate

        return translate
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 503
        logger.error(f"translate module unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: translation module is not available",
        )


def _import_broll(request_id: str):
    """Lazily import the AI B-roll service module (503 when absent).

    Guarded like the other service imports so a missing / broken B-roll module
    (it reaches the stock-footage + LLM + R2 layers) degrades to a clean 503 at
    request time instead of an ImportError at startup.
    """
    try:
        from app.services import broll

        return broll
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 503
        logger.error(f"broll module unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: b-roll module is not available",
        )


def _extract_params_dict(body: JobCreateRequest) -> dict:
    """Normalise ``body.params`` (Pydantic model or dict) into a plain dict."""
    raw: Any = getattr(body, "params", None)
    if raw is None:
        return {}
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif not isinstance(raw, dict) and hasattr(raw, "__dict__"):
        raw = dict(raw.__dict__)
    return dict(raw) if isinstance(raw, dict) else {}


def _resolve_tos_disclosure(body: JobCreateRequest) -> bool:
    """Resolve the per-job ToS / AI-disclosure flag (§S4, NEXT_PHASES 5d).

    Read from a top-level ``tos_disclosure`` field or nested under ``params``;
    coerced to a bool so it is safe to persist and read downstream at publish.
    """
    raw: Any = getattr(body, "tos_disclosure", None)
    if raw is None:
        raw = _extract_params_dict(body).get("tos_disclosure")
    return bool(raw)


def _normalize_voice_id(voice_id: Any) -> str:
    """Normalise a raw voice id to the canonical ``elevenlabs:<id>`` form.

    Idempotent: an already-prefixed value is returned unchanged so callers can
    pass either a bare provider voice id or a full ``voice_name``.
    """
    value = str(voice_id).strip()
    return value if value.startswith("elevenlabs:") else f"elevenlabs:{value}"


def _stored_params_dict(params: Any, body: JobCreateRequest) -> dict:
    """Build the JSON ``Job.params`` payload persisted for a job.

    Starts from the validated ``ReelForgeParams`` fields and threads through the
    ``tos_disclosure`` flag plus the Phase-6 creator-studio extras
    (``music_id`` / ``webhook_url`` / ``webhook_secret``). Those extras are NOT
    ``ReelForgeParams`` fields — they are persisted alongside the DTO fields so
    the compose (music) and notification (webhook) stages can read them from the
    stored ``Job.params`` without widening the strict render DTO here. Only
    set-non-empty values are written so a job's persisted params stay clean.
    """
    stored = dict(params.__dict__)
    stored["tos_disclosure"] = _resolve_tos_disclosure(body)

    source_kind = getattr(body, "source_kind", None)
    source_id = str(getattr(body, "source_id", None) or "").strip()
    source_label = str(getattr(body, "source_label", None) or "").strip()
    if source_kind == "trend" and source_id:
        stored["source_context"] = {
            "kind": "trend",
            "id": source_id[:128],
            **({"label": source_label[:200]} if source_label else {}),
        }

    music_id = getattr(body, "music_id", None)
    if music_id:
        stored["music_id"] = str(music_id)
    webhook_url = getattr(body, "webhook_url", None)
    if webhook_url:
        stored["webhook_url"] = str(webhook_url)
    webhook_secret = getattr(body, "webhook_secret", None)
    if webhook_secret:
        stored["webhook_secret"] = str(webhook_secret)
    return stored


def _stamp_diffusion_forecast(
    session: Any,
    stored_params: dict,
    body: JobCreateRequest,
    user_id: str,
    request_id: str,
) -> dict:
    """Bind a caller-owned forecast and its exact trend observation to a job.

    Loose ``source_context`` remains backwards compatible for trend-only jobs.
    A supplied ``forecast_id`` is different: every value is resolved from the
    database and the owner check deliberately returns the same 404 for missing
    and foreign ids, preventing cross-account enumeration.
    """
    forecast_id = str(getattr(body, "forecast_id", None) or "").strip()
    if not forecast_id:
        return stored_params

    from app.models.db.trends import DiffusionForecastRecord, TrendObservation

    forecast = session.get(DiffusionForecastRecord, forecast_id)
    if forecast is None or str(forecast.user_id) != str(user_id):
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: diffusion forecast not found",
        )
    observation = session.get(TrendObservation, forecast.trend_observation_id)
    if observation is None:
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message=f"{request_id}: diffusion forecast source is unavailable",
        )
    result = forecast.result if isinstance(forecast.result, dict) else {}
    expected_reach = result.get("expected_reach")
    return {
        **stored_params,
        "source_context": {
            "kind": "trend",
            "id": str(observation.trend_id),
            "label": str(observation.label or observation.trend_id),
            "observation_id": str(observation.id),
            "forecast_id": str(forecast.id),
            "content_type": str(forecast.content_type),
            "expected_reach": int(expected_reach or 0),
        },
    }


def _stamp_canon_on_params(
    session: Any, stored_params: dict, body: JobCreateRequest, user_id: str, request_id: str
) -> dict:
    """Return ``stored_params`` with the caller's bound canon lock threaded in.

    Additive + optional: reads ``canon_id`` from the request (top-level, allowed
    by ``extra='allow'``, or inside ``params``); when it resolves to a canon the
    caller owns, stamps ``params['canon']`` with that canon's ACTIVE locked
    version via ``binding.stamp_job_params``. Any absence/error is a no-op so an
    unbound request behaves exactly as before and a canon lookup can never fail
    job creation.
    """
    try:
        canon_id = getattr(body, "canon_id", None)
        if not canon_id and isinstance(getattr(body, "params", None), dict):
            canon_id = body.params.get("canon_id")
        canon_id = (str(canon_id).strip() if canon_id else "")
        if not canon_id:
            return stored_params

        from app.domains.canon.binding import stamp_job_params
        from app.domains.canon.repository import CanonRepository

        canon = CanonRepository(session).get_owned(canon_id, user_id)
        if canon is None:
            return stored_params
        return stamp_job_params(
            stored_params,
            canon_id=canon.id,
            canon_hash=canon.current_canon_hash,
            canon_version=canon.current_version,
        )
    except Exception as exc:  # noqa: BLE001 - provenance is best-effort, never fatal
        logger.warning(f"canon stamp skipped, request_id: {request_id}: {exc}")
        return stored_params


def _build_params(body: JobCreateRequest, reelforge, request_id: str):
    """Construct a validated ``ReelForgeParams`` from the request body.

    Applies the optional top-level ``avatar_id`` / ``voice_id`` overrides and
    filters unknown keys so an over-eager client payload cannot crash the DTO.
    """
    params_dict = _extract_params_dict(body)

    avatar_id = getattr(body, "avatar_id", None)
    if avatar_id:
        params_dict["avatar_id"] = avatar_id
    voice_id = getattr(body, "voice_id", None)
    if voice_id:
        params_dict["voice_name"] = _normalize_voice_id(voice_id)
    # Creator-studio tweak (Phase 6): a top-level ``caption_style`` overrides the
    # one nested in ``params`` (it is a real ``ReelForgeParams`` field, so it
    # flows through the strict DTO below unchanged).
    caption_style = getattr(body, "caption_style", None)
    if caption_style:
        params_dict["caption_style"] = str(caption_style)

    # AI background music (Phase: AI-BGM): a top-level ``music_prompt`` /
    # ``bgm_provider`` overrides any nested in ``params``. Both are real
    # ``ReelForgeParams`` fields, so once folded in they flow through the strict
    # DTO below unchanged and reach the compose stage (best-effort BGM). Folded
    # only when the client actually sent the field (``not None``) so an omitted
    # field never clobbers a value nested in ``params``.
    music_prompt = getattr(body, "music_prompt", None)
    if music_prompt is not None:
        params_dict["music_prompt"] = str(music_prompt)
    bgm_provider = getattr(body, "bgm_provider", None)
    if bgm_provider is not None:
        params_dict["bgm_provider"] = str(bgm_provider)
    # Curated background-music track: a top-level ``music_id`` (the value the
    # mobile MusicPicker sends for a picked catalog track) overrides any nested in
    # ``params``. It is a real ``ReelForgeParams`` field, so folding it in here is
    # what makes the picked track take effect on the FIRST render — the running
    # pipeline is seeded from this dataclass (not the persisted Job.params), so
    # without this fold a top-level ``music_id`` only applied on a retry. Folded
    # only when actually sent (truthy) so an omitted field never clobbers a value
    # nested under ``params``.
    music_id = getattr(body, "music_id", None)
    if music_id:
        params_dict["music_id"] = str(music_id)

    # AI B-roll cutaways: top-level ``broll_intro_key`` / ``broll_outro_key``
    # override any nested in ``params``. Both are real ``ReelForgeParams`` fields,
    # so once folded in they flow through the strict DTO below unchanged and reach
    # the compose stage (best-effort splice of a muted intro/outro). A
    # client-supplied key is ownership-checked at consumption time inside the
    # compose stage (``_assert_owned_r2_key`` BOLA guard), so it cannot reference
    # another creator's per-job artifact. Folded only when actually sent
    # (``not None``) so an omitted field never clobbers a value nested in ``params``.
    broll_intro_key = getattr(body, "broll_intro_key", None)
    if broll_intro_key is not None:
        params_dict["broll_intro_key"] = str(broll_intro_key)
    broll_outro_key = getattr(body, "broll_outro_key", None)
    if broll_outro_key is not None:
        params_dict["broll_outro_key"] = str(broll_outro_key)

    # Bring Your Own Voiceover (BYOV): a top-level ``voiceover_key`` (the R2 key of
    # the creator's own uploaded narration audio) overrides any nested in
    # ``params``. It is a real ``ReelForgeParams`` field, so once folded in it flows
    # through the strict DTO below and reaches ``stage_tts`` — which, when it is
    # set, skips TTS / voice-clone entirely and instead uses the uploaded audio as
    # the reel's narration (faster-whisper WORD timings drive the §8 captions and
    # the same audio drives the avatar lip-sync + duration). No credit change. The
    # key is ownership-checked at consumption time by ``_assert_owned_r2_key``
    # inside the tts stage, so a caller cannot reference another creator's artifact.
    # Folded only when actually sent (``not None``) so an omitted field never
    # clobbers a value nested in ``params``.
    voiceover_key = getattr(body, "voiceover_key", None)
    if voiceover_key is not None:
        params_dict["voiceover_key"] = str(voiceover_key)

    # Auto-tighten (Submagic-style "Remove Silences" pre-step): a top-level
    # ``auto_tighten`` flag turns on the pure-FFmpeg dead-air pre-cut of the
    # screen recording. It is a real ``ReelForgeParams`` field, so once folded in
    # it flows through the strict DTO below unchanged and reaches the compose
    # stage (best-effort, degrade-safe pre-step). Enabling is truthy-only so an
    # omitted/false top-level flag never clobbers an ``auto_tighten`` a client
    # nested under ``params``. Persisted in ``Job.params`` via the DTO (no
    # migration).
    if getattr(body, "auto_tighten", False):
        params_dict["auto_tighten"] = True

    # Editing-polish suite (auto_zoom / camera_motion / remove_bg): top-level
    # opt-in, default-off pre-compose passes. Each is a real ``ReelForgeParams``
    # field, so once folded in it flows through the strict DTO below unchanged and
    # is persisted in ``Job.params`` (no migration), reaching the compose stage as
    # a best-effort, degrade-safe pre-step. The two boolean flags are truthy-only
    # so an omitted/false top-level flag never clobbers a value nested under
    # ``params``; ``camera_motion`` is folded only when actually sent (``not
    # None``) for the same reason (its enum is validated on the request model).
    if getattr(body, "auto_zoom", False):
        params_dict["auto_zoom"] = True
    camera_motion = getattr(body, "camera_motion", None)
    if camera_motion is not None:
        params_dict["camera_motion"] = str(camera_motion)
    if getattr(body, "remove_bg", False):
        params_dict["remove_bg"] = True
    # Higgsfield-class Effects Mix: a top-level ``effects`` list + ``vfx_intensity``
    # override any nested in ``params``. Both are real ``ReelForgeParams`` fields
    # (validated on the request model against the reviewed VFX catalog), so once
    # folded in they flow through the strict DTO below and reach the compose-stage
    # VFX render. Folded only when actually sent (``not None``) so an omitted field
    # never clobbers a value nested under ``params``.
    effects = getattr(body, "effects", None)
    if effects is not None:
        params_dict["effects"] = list(effects)
    vfx_intensity = getattr(body, "vfx_intensity", None)
    if vfx_intensity is not None:
        params_dict["vfx_intensity"] = int(vfx_intensity)

    allowed = {f.name for f in dataclasses.fields(reelforge.ReelForgeParams)}
    filtered = {k: v for k, v in params_dict.items() if k in allowed}
    if isinstance(filtered.get("platforms"), list):
        filtered["platforms"] = tuple(filtered["platforms"])
    # ``effects`` is a tuple on the frozen dataclass (JSON round-trips it as a
    # list); normalise so the immutable contract holds, mirroring ``platforms``.
    if isinstance(filtered.get("effects"), list):
        filtered["effects"] = tuple(filtered["effects"])

    try:
        return reelforge.ReelForgeParams(**filtered)
    except (TypeError, ValueError) as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid job params: {exc}",
        )


# Composition layouts the compose stage can actually render. ``ReelForgeParams``
# stores ``layout`` as a plain ``str`` (no ``Literal``), and ``RerunOverrides``
# only length-bounds it, so without an explicit allowlist an unknown value would
# pass every schema/DTO check and fail only deep in the compose stage — after the
# credit debit is committed and the pipeline enqueued, burning a credit with no
# refund path. This is the known-good fallback if the compose module can't be
# imported at request time (import-safe, mirroring the guarded DB import).
_FALLBACK_LAYOUTS: frozenset[str] = frozenset(
    {"pip", "hook_intro", "split", "captions_only"}
)

# The avatar-less layout: burns captions over the uploaded screen recording with
# no HeyGen avatar, so it can be produced with only the core backend (FFmpeg +
# local captioning) and requires no paid avatar/voice provider.
_CAPTIONS_ONLY_LAYOUT: str = "captions_only"


def _allowed_layouts() -> frozenset[str]:
    """Return the layout ids the compose stage accepts (single source of truth).

    Reuses ``compose_ffmpeg.supported_layouts()`` (avatar overlays + the avatar-less
    ``captions_only`` path) so a layout added to the compose service is
    automatically accepted here and the two never drift; degrades to
    :data:`_FALLBACK_LAYOUTS` when that module cannot be imported.
    """
    try:
        from app.services.compose.compose_ffmpeg import supported_layouts

        return supported_layouts() or _FALLBACK_LAYOUTS
    except Exception as exc:  # noqa: BLE001 - import-safe: degrade to the known set
        logger.debug(f"compose layout catalog unavailable, using fallback: {exc}")
        return _FALLBACK_LAYOUTS


def _validate_layout(params: Any, request_id: str) -> None:
    """Fail-fast (400) when ``params.layout`` is not one the compose stage supports.

    Runs at the controller boundary *before* the credit debit / enqueue, so an
    invalid layout is rejected with a clean 400 instead of consuming a credit on
    an unrefundable compose failure inside the worker.
    """
    layout = getattr(params, "layout", "") or ""
    allowed = _allowed_layouts()
    if layout not in allowed:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: unsupported layout {layout!r} "
                f"(allowed: {', '.join(sorted(allowed))})"
            ),
        )


def _validate_hook_style(params: Any, request_id: str):
    """Canonicalize ``params.hook_style`` or fail fast (400) on an unknown angle."""
    from app.domains.experiments.hook_styles import HookStyleError, normalize_hook_style

    try:
        style = normalize_hook_style(getattr(params, "hook_style", ""))
    except HookStyleError as exc:
        raise HttpException(
            task_id=request_id, status_code=400, message=f"{request_id}: {exc}"
        )
    if style == getattr(params, "hook_style", ""):
        return params
    return dataclasses.replace(params, hook_style=style)


def _variant_hook_styles(params: Any, variants: int) -> list[str]:
    """One distinct opening-hook angle per variant of a generated-script batch.

    Only a batch whose script is GENERATED gets angles: a manual or translated
    script already fixes the hook (its first line). The requested
    ``hook_style`` (if any) leads; the rest follow the fixed rotation, so the N
    variants of one run can never share an opener. ``[]`` => no rotation.
    """
    from app.domains.experiments.hook_styles import rotate_hook_styles

    if variants < 2:
        return []
    if str(getattr(params, "video_script", "") or "").strip():
        return []
    if str(getattr(params, "translate_source_script", "") or "").strip():
        return []
    family = _style_hook_family(params)
    if family:
        from app.domains.experiments.hook_styles import rotate_family

        return rotate_family(variants, family)
    return rotate_hook_styles(variants, getattr(params, "hook_style", ""))


def _style_hook_family(params: Any) -> tuple[str, ...]:
    """The style's hook family (its own opener formats), ``()`` for no style."""
    from app.domains.styles.catalog import get_style

    style = get_style(str(getattr(params, "style", "") or ""))
    return style.hook_family if style else ()


def _apply_style(params: Any, request_id: str):
    """Fold a one-click style's defaults into ``params`` (400 on unknown style).

    The style is the creator's one choice, so it sets the layout, caption style
    and companion loop. The hook angle is filled only when none was sent (a
    link run labels each variant with the meme/POV hook it already wrote).
    """
    from app.domains.styles.catalog import UnknownStyleError, require_style, style_overrides

    source_url = str(getattr(params, "source_url", "") or "").strip()
    if source_url and (
        len(source_url) > 2048 or not source_url.lower().startswith(("http://", "https://"))
    ):
        params = dataclasses.replace(params, source_url="")
    try:
        style = require_style(getattr(params, "style", ""))
    except UnknownStyleError as exc:
        raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: {exc}")
    if style is None:
        return params
    overrides = style_overrides(style, hook_style=str(getattr(params, "hook_style", "") or ""))
    if not style.needs_presenter:
        overrides["avatar_id"] = ""
    return dataclasses.replace(params, **overrides)


def _register_hook_run(
    user_id: str, job_ids: list[str], styles: list[str], failed: list[str], request_id: str
) -> None:
    """Register a hook-styled batch as an experiment + open its winner loop.

    Best-effort: the reels are already paid for and rendering, so a registration
    problem is logged and never fails the create request.
    """
    if not styles or len(job_ids) - len(failed) < 2:
        return
    try:
        from app.domains.experiments.registration import RunVariant, register_run_and_open_loop

        register_run_and_open_loop(
            user_id=str(user_id),
            variants=[RunVariant(job_id=j, hook_style=s) for j, s in zip(job_ids, styles)],
        )
    except Exception as exc:  # noqa: BLE001 - never fail a paid, enqueued batch
        logger.warning(f"{request_id}: could not register hook run as an experiment: {exc}")


def _needs_script_llm(params: Any) -> bool:
    """Whether the pipeline's script stage will call the LLM for these params.

    Mirrors ``reelforge.stage_script``: a typed script never needs it, dubbing
    (``translate_source_script``) does, and an avatar-less captions-only reel
    over the creator's own video/voiceover derives captions from its audio.
    A faceless captions-only reel (TTS voice, no upload) narrates a generated
    script, so it needs the LLM unless a script was typed.
    """
    if str(getattr(params, "translate_source_script", "") or "").strip():
        return True
    if str(getattr(params, "video_script", "") or "").strip():
        return False
    if getattr(params, "layout", "") != _CAPTIONS_ONLY_LAYOUT:
        return True
    faceless = (
        not str(getattr(params, "voiceover_key", "") or "")
        and not str(getattr(params, "screen_recording_key", "") or "")
        and bool(str(getattr(params, "voice_name", "") or "").strip())
    )
    return faceless


def _validate_enabled_feature_secrets(params: Any, request_id: str) -> None:
    """Reject formats this deployment cannot produce with 402 ``format_locked``.

    Runs before the credit debit / enqueue (job create, rerun and retry) so a
    locked format never fails mid-pipeline. The avatar-less ``captions_only``
    layout skips the avatar stage entirely, so it is exempt from the
    avatar-provider requirement — that is what lets a reel be produced with only
    the core backend. A premium (``elevenlabs:``) voice is NOT locked: without
    an ElevenLabs key the TTS stage narrates with a free edge-tts voice instead,
    which is itself required whenever speech is synthesized. The rules live in
    :func:`app.core.launch.formats.params_lock`.
    """
    from app.core.launch.formats import enforce_params_available

    enforce_params_available(request_id, params, needs_script_llm=_needs_script_llm(params))


def _can_access_clean_result(user_id: str, request_id: str) -> bool:
    """Fail-closed entitlement check for clean result URL presentation.

    Preview/poster artifacts remain available to every owner. The full clean
    MP4 is only presigned when :mod:`app.services.user_entitlements` finds a
    paid source: a live web plan (Dodo or Creem), a credit pack, or RevenueCat
    Pro (short-cached, so status polling does not hit billing on every poll).
    """

    try:
        from app.services.user_entitlements import can_access_clean_result

        allowed = can_access_clean_result(str(user_id))
    except Exception as exc:  # noqa: BLE001 - every uncertainty fails closed
        logger.info(
            f"clean result withheld for user {user_id}, request_id: "
            f"{request_id}: {type(exc).__name__}"
        )
        return False
    if not allowed:
        logger.info(f"clean result withheld for user {user_id}, request_id: {request_id}")
    return allowed


def _presign_job_artifacts(
    job: Any,
    data: dict[str, Any],
    request_id: str,
    *,
    include_result: bool = True,
) -> None:
    """Add durable artifact keys and browser-safe presigned URLs to ``data``.

    Each artifact is independent and best-effort: one missing object or R2
    signing failure must not make the whole status/library response fail. The
    keys remain useful for authenticated server-side handoffs while every
    client uses the corresponding ``*_url`` field for presentation.
    """
    artifact_fields: tuple[tuple[str, str], ...] = (
        ("poster_key", "poster_url"),
        ("preview_key", "preview_url"),
        ("cover_key", "cover_url"),
    )
    artifacts = [
        (key_field, url_field, str(getattr(job, key_field, "") or "").strip())
        for key_field, url_field in artifact_fields
    ]
    result_key = str(getattr(job, "result_key", "") or "").strip()
    if not result_key and not any(key for _, _, key in artifacts):
        return

    # MN5 (added by MN8): a video soft-blocked after a content report serves no
    # media until staff restore it; the owner sees why.
    from app.domains.compliance.takedown import BLOCKED_MESSAGE, is_blocked

    if is_blocked(str(job.id)):
        data["media_blocked"] = True
        data["media_blocked_message"] = BLOCKED_MESSAGE
        return

    try:
        from app.platform.storage.r2 import get_r2_client

        r2 = get_r2_client()
    except Exception as exc:  # noqa: BLE001 - status reads degrade without R2
        logger.warning(
            f"failed to initialise artifact presigning for job {job.id}, "
            f"request_id: {request_id}: {exc}"
        )
        # Durable keys are still safe and useful even when signing is down.
        for key_field, _, key in artifacts:
            if key:
                data[key_field] = key
        return

    if include_result and result_key:
        try:
            data["result_url"] = r2.presign_result_get(result_key)
        except Exception as exc:  # noqa: BLE001 - individual URL is best-effort
            logger.warning(
                f"failed to presign result for job {job.id}, "
                f"request_id: {request_id}: {exc}"
            )

    for key_field, url_field, key in artifacts:
        if not key:
            continue
        data[key_field] = key
        try:
            data[url_field] = r2.presign_result_get(key)
        except Exception as exc:  # noqa: BLE001 - individual URL is best-effort
            logger.warning(
                f"failed to presign {key_field} for job {job.id}, "
                f"request_id: {request_id}: {exc}"
            )


_MAX_SHARE_HASHTAGS = 8
_MAX_SOURCE_URL = 2048
_HASHTAG_TOKEN = re.compile(r"^[\w]{1,100}$")


def _opening_hook(script: str, params: dict) -> str:
    """First non-empty script line, else the subject. Same rule as the public hook."""
    hook = next((line.strip() for line in str(script or "").splitlines() if line.strip()), "")
    if not hook:
        hook = str(params.get("video_subject") or "").strip()
    return hook


def _share_source_url(params: dict) -> str:
    """http(s) page the reel was written from, or "" when it is missing or unsafe."""
    text = str(params.get("source_url") or "").strip()
    if not text or len(text) > _MAX_SOURCE_URL:
        return ""
    if not text.lower().startswith(("http://", "https://")):
        return ""
    if any(ch.isspace() for ch in text):
        return ""
    return text


def _share_hashtags(params: dict) -> list[str]:
    """Hashtags already stored on the job. Nothing is generated here."""
    raw: list[object] = []
    social = params.get("social_metadata")
    if isinstance(social, dict) and isinstance(social.get("hashtags"), list):
        raw.extend(social["hashtags"])
    top = params.get("hashtags")
    if isinstance(top, list):
        raw.extend(top)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        token = str(item or "").strip().lstrip("#")
        if not token or _HASHTAG_TOKEN.fullmatch(token) is None:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(f"#{token}")
        if len(out) >= _MAX_SHARE_HASHTAGS:
            break
    return out


def _attach_share_fields(data: dict, params: dict) -> None:
    source = _share_source_url(params)
    if source:
        data["source_url"] = source
    tags = _share_hashtags(params)
    if tags:
        data["hashtags"] = tags


def _job_status(job: Any) -> str:
    """Human status: processing | complete | failed | cancelled."""
    if _is_cancelled(job):
        return "cancelled"
    if job.state == TASK_STATE_COMPLETE:
        return "complete"
    if job.state == TASK_STATE_FAILED:
        return "failed"
    return "processing"


def _job_public_data(
    job: Any,
    request_id: str,
    *,
    include_result: bool = False,
) -> dict:
    """Serialise a ``Job`` row to the public ``JobData`` envelope.

    Adds signed presentation URLs for every persisted media artifact and a small
    set of stable product metadata. Presign failures are logged and omitted
    rather than failing the read.
    """
    params = getattr(job, "params", {})
    params = params if isinstance(params, dict) else {}
    # M3.1 charge on keep: an unpaid variant shows its preview, not its clean MP4.
    from app.domains.reels.keep import is_pending as _keep_pending, keep_view as _keep_view

    if _keep_pending(params):
        include_result = False
    correlation_id = str(params.get("_correlation_id") or request_id)
    # The persisted WolfCut clip descriptor rides inside the ``stages`` JSON map
    # under a private key (no schema migration); strip it from the public map so
    # it is never mistaken for a real stage, and surface it as ``generated_clip``
    # below once a signed result URL is available.
    stages = dict(job.stages or {})
    result_media = stages.pop("_result_media", None)
    # The pre-publish content quality + safety gate verdict also rides inside the
    # ``stages`` JSON under a private key (no schema migration); strip it from the
    # public stage map and surface it as ``content_gate`` so a client can show why
    # a reel was held for review or flagged before publishing.
    content_gate = stages.pop("_content_gate", None)
    # Private winner-loop state (settings, rounds, spend) rides here too.
    stages.pop("_winner_loop", None)
    archived_at = getattr(job, "archived_at", None)
    data: dict[str, Any] = {
        "job_id": job.id,
        "kind": str(getattr(job, "kind", "") or "avatar_reel"),
        "state": job.state,
        "status": _job_status(job),
        "cancelled": _is_cancelled(job),
        "progress": job.progress,
        "stages": stages,
        "correlation_id": correlation_id,
        # A cancelled reel may be resumed via retry (charged again, like any
        # retry); clients label the action "Resume" when ``cancelled`` is true.
        "retry_eligible": (
            job.state == TASK_STATE_FAILED
            and is_retryable_kind(str(getattr(job, "kind", "") or ""))
        ),
        "cancel_eligible": (
            job.state == TASK_STATE_PROCESSING
            and str(getattr(job, "kind", "") or _DEFAULT_JOB_KIND) in _CANCELLABLE_KINDS
        ),
        "title": str(getattr(job, "title", "") or ""),
        "archived": archived_at is not None,
        "archived_at": archived_at.isoformat() if archived_at is not None else None,
    }
    created_at = getattr(job, "created_at", None)
    if created_at is not None:
        data["created_at"] = created_at.isoformat()
    if job.failed_stage:
        data["failed_stage"] = job.failed_stage
    if job.error:
        data["error"] = job.error

    data["language"] = str(params.get("language") or "auto")

    script = str(getattr(job, "script", "") or "")
    data["source_footage_ready"] = bool(
        str(params.get("screen_recording_key") or "").strip()
    )
    data["brief_ready"] = bool(
        script
        or str(params.get("video_script") or "").strip()
        or str(params.get("video_subject") or "").strip()
    )
    hook = _opening_hook(script, params)
    if hook:
        data["hook"] = hook
    _attach_share_fields(data, params)

    if isinstance(content_gate, dict) and content_gate:
        data["content_gate"] = content_gate

    keep_block = _keep_view(params)
    if keep_block is not None:
        data["keep"] = keep_block

    _presign_job_artifacts(
        job,
        data,
        request_id,
        include_result=include_result,
    )

    # Generate->edit seam (EDITING-SUITE-PLAN §4 / Phase 1): once the reel is
    # complete and the caller is entitled to the clean result URL, surface the
    # WolfCut ``GeneratedClip`` descriptor so the desktop shell opens the reel
    # straight in the editor. The persisted base carries exact
    # width/height/frame-rate/codecs + job-side caption timing; an older job with
    # no persisted base falls back to its aspect resolution. ``src`` is the
    # freshly-signed result URL, so it is only attached when one was produced.
    if (
        include_result
        and job.state == TASK_STATE_COMPLETE
        and str(data.get("result_url") or "").strip()
    ):
        try:
            src = str(data["result_url"])
            if isinstance(result_media, dict) and result_media:
                data["generated_clip"] = {**result_media, "src": src}
            else:
                from app.services.generated_clip import fallback_descriptor

                hook = str(data.get("hook") or "").strip()
                data["generated_clip"] = fallback_descriptor(
                    name=hook or "ReelForge video",
                    src=src,
                    aspect=params.get("aspect"),
                )
        except Exception as exc:  # noqa: BLE001 - descriptor is best-effort
            logger.warning(
                f"failed to build generated_clip for job {job.id}, "
                f"request_id: {request_id}: {exc}"
            )
    return data


def _batch_job_data(
    job: Any,
    request_id: str,
    *,
    include_result: bool = False,
) -> dict:
    """Serialise a ``Job`` row to the compact batch-review shape.

    Only the fields a batch-review UI needs: ``{job_id, state, progress}`` plus
    the opening hook, source link, and any stored hashtags, and, when the
    render has finished (``result_key`` present), a presigned
    signed result, poster, preview, and cover media when available. Presigning is
    best-effort — a failure is logged and the URL is omitted rather than failing
    the whole batch read.
    """
    params = getattr(job, "params", {})
    params = params if isinstance(params, dict) else {}
    data: dict[str, Any] = {
        "job_id": job.id,
        "state": job.state,
        "status": _job_status(job),
        "cancelled": _is_cancelled(job),
        "progress": job.progress,
        "correlation_id": str(params.get("_correlation_id") or request_id),
        "title": str(getattr(job, "title", "") or ""),
    }
    hook = _opening_hook(getattr(job, "script", ""), params)
    if hook:
        data["hook"] = hook
    _attach_share_fields(data, params)
    _presign_job_artifacts(
        job,
        data,
        request_id,
        include_result=include_result,
    )
    return data


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
# Upload endpoints are independently owned and mounted by ``app.domains.media``.


def _refund_debit(
    user_id: str,
    cost: int,
    workspace_id: str | None,
    reason: str,
    job_id: str | None = None,
) -> None:
    """Refund one job's debit to whichever pool it was charged against.

    When ``workspace_id`` is set the credit was drawn from the workspace SHARED
    pool, so the refund is issued via ``workspace_grant`` (keeping the pool
    balance consistent); otherwise it is granted back to the user's personal
    balance. Runs on its own committed session (the caller isolates it) so a
    DB error here cannot roll back an already-committed FAILED transition.
    """
    # The refund row is tagged with ``job_id`` so the once-only refund helpers
    # (``app.domains.reels.refunds``) can see this debit was already returned.
    if int(cost or 0) <= 0:
        return  # an unpaid charge-on-keep variant was never debited
    with get_session() as session:
        if workspace_id is not None:
            CreditRepository(session).workspace_grant(
                workspace_id, cost, reason, actor_user_id=user_id, job_id=job_id
            )
        else:
            CreditRepository(session).grant(user_id, cost, reason, job_id=job_id)


def _refund_and_fail_job(
    job_id: str,
    user_id: str,
    cost: int,
    stage: str,
    error: str,
    request_id: str,
    workspace_id: str | None = None,
) -> None:
    """Mark a job failed and refund its debit after an enqueue failure.

    Shared by the single- and batch-variant enqueue paths: the debit was already
    committed, so a job that will never run must be marked failed and reconciled
    with a refund. The refund is best-effort (logged, never re-raised) so one
    reconciliation failure cannot mask the original enqueue error.

    ``mark_failed`` and the refund run in *separate* committed transactions: a
    DB-level error inside the refund deactivates its own session (and would make
    the enclosing context manager raise on commit), so isolating it means a
    failed refund can never roll back the already-committed ``mark_failed`` nor
    surface as an unexpected exception through the shared session.

    When ``workspace_id`` is set the credit is refunded to that workspace's
    SHARED pool (``workspace_grant``); otherwise to the user's personal balance
    (``grant``) — mirroring exactly the pool the original debit was charged to.
    """
    logger.error(
        f"start_pipeline failed for job {job_id}, request_id: {request_id}: {error}"
    )
    # Commit the FAILED transition first, on its own session, so nothing that
    # follows can undo it.
    with get_session() as session:
        JobRepository(session).mark_failed(job_id, stage, error)
    # Best-effort refund in an isolated transaction: any DB error here poisons
    # only this session (rolled back + closed by get_session) and is logged but
    # never re-raised, so it cannot corrupt other work or abort the caller.
    try:
        _refund_debit(user_id, cost, workspace_id, _JOB_REFUND_REASON, job_id=job_id)
    except Exception as refund_exc:  # noqa: BLE001 - best-effort refund
        logger.error(
            f"failed to refund credits for job {job_id}, "
            f"request_id: {request_id}: {refund_exc}"
        )
    # Premium voice / AI-video credits of a job that never ran go back too
    # (idempotent, never raises).
    from app.domains.reels.premium import refund_job as _refund_premium

    _refund_premium(job_id)


def _require_presenter_gate(
    session: Any, user_id: str, params: Any, variants: int, request_id: str
) -> None:
    """Pro presenter gate and monthly cap for any funding path (402 ``sku_locked``)."""
    from app.domains.reels.policy import require_presenter_allowed
    from app.domains.reels.pricing import PricingError

    try:
        require_presenter_allowed(session, str(user_id), params, variants)
    except PricingError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.detail}",
            data=exc.as_dict(),
        ) from exc


def _plan_premium(session: Any, user_id: str, params: Any, variants: int, request_id: str):
    """Premium voice / AI-video admission (see :mod:`app.domains.reels.premium`).

    Standard credits never pay for ElevenLabs or avatar providers: an unfunded
    premium voice becomes the free voice; an unfunded presenter reel is a 402.
    """
    from app.domains.reels.policy import require_presenter_allowed
    from app.domains.reels.premium import PremiumCreditsRequired, plan_job
    from app.domains.reels.pricing import PricingError

    try:
        # M3.1 / MD8: presenter reels are Pro and Agency only, with a monthly cap.
        require_presenter_allowed(session, str(user_id), params, variants)
        return plan_job(session, str(user_id), params, variants)
    except PricingError as exc:
        # MG3: an unpriced or locked SKU is refused before any job or debit.
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.detail}",
            data=exc.as_dict(),
        ) from exc
    except PremiumCreditsRequired as exc:
        raise HttpException(
            task_id=request_id,
            status_code=402,
            message=f"{request_id}: {exc}",
            data={
                "code": "ai_video_credits_required",
                "needed": exc.needed,
                "available": exc.available,
            },
        ) from exc


def _debit_premium(session: Any, user_id: str, job_id: str, plan: Any, request_id: str) -> None:
    from app.domains.reels.premium import PremiumCreditsRequired, debit_job

    try:
        debit_job(session, str(user_id), job_id, plan)
    except PremiumCreditsRequired as exc:
        raise HttpException(
            task_id=request_id,
            status_code=402,
            message=f"{request_id}: {exc}",
            data={
                "code": "ai_video_credits_required",
                "needed": exc.needed,
                "available": exc.available,
            },
        ) from exc


def _planned_params(stored: dict, params: Any, plan: Any, *, copied: bool) -> dict:
    """``stored`` with the premium decision applied (new dict, never mutated).

    The voice and AI-music fields the premium plan may have downgraded are
    written back, so every later reader of ``Job.params`` (reaper retry, the
    stage guards) sees what was actually paid for. A ``copied`` job (re-run,
    dub) is a new standard-credit job: the source's wallet hold marker never
    carries over, or the copy would read as wallet-funded.
    """
    from app.domains.reels.wallet_bridge import WALLET_MARKER_KEY

    base = {k: v for k, v in stored.items() if not (copied and k == WALLET_MARKER_KEY)}
    return {
        **base,
        "voice_name": getattr(params, "voice_name", ""),
        "music_prompt": getattr(params, "music_prompt", ""),
        "bgm_provider": getattr(params, "bgm_provider", ""),
        **plan.marker,
    }


def _reconcile_failed_enqueue(
    job_id: str,
    user_id: str,
    cost: int,
    error: str,
    request_id: str,
    workspace_id: str | None = None,
) -> None:
    """Refund + fail a job whose enqueue could not be completed, never raising.

    Wraps ``_refund_and_fail_job`` so a reconciliation error for a single
    variant (e.g. a transient DB error while marking it failed) cannot abort the
    batch enqueue loop and strand the remaining variants debited-but-unenqueued.
    ``workspace_id`` (when set) routes the refund to the workspace SHARED pool.
    """
    try:
        # A wallet-funded job (its params carry the reservation marker) never
        # debited a credit, so it must be marked failed and have its RESERVATION
        # RELEASED rather than a (non-existent) credit refunded.
        wallet_params: dict | None = None
        try:
            from app.domains.reels.wallet_bridge import read_marker

            with get_session() as _session:
                _job = JobRepository(_session).get(job_id)
                _params = dict(_job.params) if _job and _job.params else None
            wallet_params = _params if read_marker(_params) else None
        except Exception:  # noqa: BLE001 - detection failure falls back to credit path
            wallet_params = None

        if wallet_params is not None:
            from app.domains.reels.wallet_bridge import safe_release_job

            with get_session() as _session:
                JobRepository(_session).mark_failed(job_id, "enqueue", error)
            safe_release_job(user_id, job_id, wallet_params)
        else:
            _refund_and_fail_job(
                job_id, user_id, cost, "enqueue", error, request_id, workspace_id
            )
    except Exception as exc:  # noqa: BLE001 - reconciliation must never abort the loop
        logger.error(
            f"failed to reconcile enqueue failure for job {job_id}, "
            f"request_id: {request_id}: {exc}"
        )


def _resolve_workspace_pool(
    body: JobCreateRequest, session: Any, user: Any, request_id: str
) -> str | None:
    """Resolve the workspace whose SHARED pool this job should debit, or ``None``.

    Returns ``None`` (the classic per-user path) when ``body.workspace_id`` is
    unset/blank. When it is set the caller MUST be a member of that workspace —
    membership is the authorization gate for spending the shared pool — so:

    * a missing workspaces service degrades to a clean ``503``;
    * a non-member (or an unknown workspace id, which has no membership) is
      rejected with ``403`` and no existence leak.

    On success the validated workspace id is returned so the debit / refund paths
    can target the shared pool instead of the user's personal balance.
    """
    raw = getattr(body, "workspace_id", None)
    workspace_id = str(raw).strip() if raw is not None else ""
    if not workspace_id:
        return None

    if ws_service is None:
        logger.error(
            f"workspaces service unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: workspaces service is not available",
        )

    if ws_service.get_membership(session, workspace_id, user.id) is None:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: not a member of this workspace",
        )
    return workspace_id


_IDEMPOTENCY_HEADER = IDEMPOTENCY_HEADER
_MAX_IDEMPOTENCY_KEY_LENGTH = MAX_IDEMPOTENCY_KEY_LENGTH


def _get_idempotency_key(request: Request, request_id: str) -> str | None:
    """Compatibility wrapper for shared command idempotency."""
    return read_idempotency_key(request, request_id)


def _idempotency_request_hash(body: JobCreateRequest) -> str:
    """Compatibility wrapper for deterministic request hashing."""
    return hash_request_payload(body)


def _reserve_job_idempotency_key(
    session: Any,
    user_id: str,
    key: str,
    request_hash: str,
    request_id: str,
) -> tuple[Any, dict[str, Any] | None]:
    """Return a fresh reservation or the saved response for a same-key replay.

    The nested transaction leaves the outer money-path transaction usable when
    another API replica wins the unique-key insert race.
    """
    return reserve_idempotency_key(session, user_id, key, request_hash, request_id)


@router.post("/jobs/quote", summary="Price a job before rendering")
def quote_job(request: Request, body: JobCreateRequest):
    """Price one create request before any job, debit or render exists (MG3).

    Takes the same body as ``POST /jobs`` and answers what it would cost per
    variant and in total, split into standard, premium voice and AI-video
    credits, next to the caller's balances. A premium voice or music the
    balance cannot cover is shown as downgraded to its free alternative, the
    same way create would run it. An unpriced SKU answers 402 ``sku_unpriced``.
    """
    from app.domains.reels import pricing
    from app.domains.reels.premium import uses_elevenlabs_music, wants_premium_voice
    from app.services.billing import premium_credits as pc

    request_id = base.get_task_id(request)
    _require_db(request_id)
    reelforge = _import_reelforge(request_id)
    variants = _resolve_variants(body)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        params = _apply_style(_build_params(body, reelforge, request_id), request_id)
        _validate_layout(params, request_id)
        want_voice = wants_premium_voice(params)
        want_music = uses_elevenlabs_music(params)
        try:
            from app.domains.reels.policy import require_presenter_allowed

            require_presenter_allowed(session, str(user.id), params, variants)
            quote = pricing.credit_cost(params, premium_voice=want_voice, premium_music=want_music)
        except pricing.PricingError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=exc.status_code,
                message=f"{request_id}: {exc.detail}",
                data=exc.as_dict(),
            ) from exc
        balances = {
            pricing.KIND_STANDARD: int(CreditRepository(session).balance(str(user.id))),
            pricing.KIND_PREMIUM_VOICE: pc.balance(session, str(user.id), pc.KIND_PREMIUM_VOICE),
            pricing.KIND_AI_VIDEO: pc.balance(session, str(user.id), pc.KIND_AI_VIDEO),
        }
    data = quote.as_dict(variants)
    total = data["total"]
    keep_later = _charge_on_keep_enabled() and variants > 1
    data["charge_on_keep"] = keep_later
    # Standard credits taken at create; with charge on keep, variants 2-3 are
    # debited only when kept (premium credits are always taken at create).
    data["due_now"] = {
        **total,
        pricing.KIND_STANDARD: quote.standard_credits * (1 if keep_later else variants),
    }
    data["balances"] = balances
    data["affordable"] = (
        balances[pricing.KIND_STANDARD] >= data["due_now"][pricing.KIND_STANDARD]
        and balances[pricing.KIND_AI_VIDEO] >= total[pricing.KIND_AI_VIDEO]
    )
    data["premium_downgraded"] = balances[pricing.KIND_PREMIUM_VOICE] < total[pricing.KIND_PREMIUM_VOICE]
    return utils.get_response(200, data)


class PresetQuoteRequest(BaseModel):
    """Body of ``POST /jobs/quote/preset`` (MH1)."""

    preset_sku: str = Field(..., max_length=64)
    tier: str = Field("draft", max_length=16)
    seconds: int = Field(5, ge=1, le=60)
    resolution: str | None = Field(None, max_length=16)
    variants: int = Field(1, ge=1, le=3)


@router.post("/jobs/quote/preset", summary="Price an AI-video preset before rendering")
def quote_preset(request: Request, body: PresetQuoteRequest):
    """Price an AI-video preset (capability + tier) before any render (MH1).

    The tier resolver picks the licensed, priced model (draft: cheapest;
    final: the default strong model under the cap). The price is in AI-video
    credits only; standard credits never pay a model. An unpriced preset,
    tier or resolution, or no admissible model, answers 402 ``sku_unpriced``.
    """
    from app.domains.reels import pricing
    from app.services.billing import premium_credits as pc

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        held = pc.balance(session, str(user.id), pc.KIND_AI_VIDEO)
    try:
        quote, route = pricing.preset_credit_cost(
            body.preset_sku, body.tier, body.seconds, body.resolution
        )
    except pricing.PricingError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.detail}",
            data=exc.as_dict(),
        ) from exc
    data = quote.as_dict(body.variants)
    data["route"] = route.as_dict()
    data["balances"] = {pricing.KIND_AI_VIDEO: held}
    data["affordable"] = held >= data["total"][pricing.KIND_AI_VIDEO]
    return utils.get_response(200, data)


@router.post("/jobs", response_model=JobResponse, summary="Create a job")
def create_job(request: Request, body: JobCreateRequest):
    """Create + enqueue one or more ReelForge avatar jobs (§5.2, batch §4).

    Order: auth -> rate limit (once) -> feature-secret validation (400) -> persist
    ``N`` Job rows AND atomically debit ``N × cost`` credits in ONE committed
    transaction (402 on insufficient for the *full* batch, enqueuing none) -> only
    then start each Celery pipeline -> return status. The debit is committed
    *before* any pipeline work is enqueued so a job can never run for free; if an
    enqueue subsequently fails that job's debit is reconciled with a refund.

    ``body.variants`` (1..3) drives the fan-out. With ``variants == 1`` the
    response is the classic single-job envelope ``{job_id, state, progress}``
    (no ``batch_id`` — a lone job belongs to no batch); with ``variants > 1`` it
    additionally carries ``job_ids`` (all created jobs, ``job_id`` being the
    first) and a shared ``batch_id`` (a single uuid hex set on every created Job
    row) so a client can poll each variant *and* review them together via
    ``GET /batches/{batch_id}``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    reelforge = _import_reelforge(request_id)
    pipeline = _import_pipeline(request_id)
    cost = _job_cost()
    variants = _resolve_variants(body)
    idempotency_key = _get_idempotency_key(request, request_id)
    request_hash = _idempotency_request_hash(body) if idempotency_key else ""

    # The workspace whose SHARED pool this batch debits, or ``None`` for the
    # classic per-user path. Bound outside the transaction so the post-commit
    # enqueue-reconcile loop can route refunds to the right pool.
    workspace_id: str | None = None
    response_data: dict[str, Any]

    # Single locked transaction: create the N jobs and check-and-debit credits
    # atomically. Both ``CreditRepository.debit`` and ``workspace_debit`` take a
    # row lock and raise on an insufficient balance, so per-variant debits
    # accumulate against one balance and the check cannot race. Any failure here
    # rolls the whole unit back — no orphan jobs, no partial debit, nothing
    # enqueued.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        # Reserve/replay idempotency before consuming a pilot rate/spend budget:
        # a transport retry of an already accepted request must always return
        # its original job rather than becoming a spurious 402/429.
        from app.core.capabilities import pilot_debit_reason, require_generation_access

        idempotency_row = None
        if idempotency_key is not None:
            idempotency_row, replay_data = _reserve_job_idempotency_key(
                session,
                user.id,
                idempotency_key,
                request_hash,
                request_id,
            )
            if replay_data is not None:
                return utils.get_response(200, replay_data)
        # This remains before every debit and every pipeline dispatch.
        require_generation_access(
            request, session, user.id, "reel", cost * variants, request_id
        )
        # Per-user rate limit BEFORE the credit check (once per request, not per
        # variant) so a runaway client is rejected with a clean 429 before any
        # job row is created or credits are debited. Fail-open if Redis is down.
        enforce_rate_limit(
            request,
            f"jobs:{user.id}",
            limit=_jobs_rate_limit(),
            window_s=_jobs_rate_window_s(),
        )
        # Resolve the credit pool up front: a workspace job requires membership
        # (403 for a non-member) and debits the SHARED pool; otherwise the
        # personal balance is used exactly as before.
        workspace_id = _resolve_workspace_pool(body, session, user, request_id)
        if workspace_id is not None:
            from app.core.capabilities import pilot_enabled

            if pilot_enabled():
                # The pilot allocation is per-user and is intentionally not
                # bypassable through a workspace's shared balance.
                raise HttpException(
                    task_id=request_id,
                    status_code=403,
                    message=f"{request_id}: workspace-funded generation is disabled during the internal pilot",
                )
        # ADDITIVE WALLET PATH (PROVIDER_MARKETPLACE_PLAN.md §4.1): a request that
        # carries a signed generation quote + ``generation_profile_id`` funds the
        # job from the USD wallet (reserve now, settle/release at the terminal
        # transition) instead of the fixed credit ledger. Classic requests (no
        # quote) are entirely unaffected. Validate the quote BEFORE any job row is
        # created so a tampered/expired quote can never orphan a job.
        from app.domains.reels.wallet_bridge import (
            WalletBridgeError,
            extract_wallet_intent,
            reserve_for_job,
            validate_intent,
        )

        wallet_intent = extract_wallet_intent(body)
        if wallet_intent is not None:
            try:
                validate_intent(session, wallet_intent, request_id)
            except WalletBridgeError as exc:
                raise HttpException(
                    task_id=request_id,
                    status_code=exc.status_code,
                    message=f"{request_id}: {exc.message}",
                )

        params = _build_params(body, reelforge, request_id)
        # Requested platforms become an owner-scoped auto-publish after render
        # (native OAuth connectors + content gate), not an in-pipeline cross-post.
        params, autopublish_platforms = _split_autopublish(
            params, str(user.id), request_id
        )
        params = _apply_style(params, request_id)
        _validate_layout(params, request_id)
        params = _validate_hook_style(params, request_id)
        _validate_enabled_feature_secrets(params, request_id)
        # Premium voice / AI presenter are separate SKUs (never standard credits).
        # A wallet-funded job pays its own USD quote instead.
        premium_plan = None
        if wallet_intent is None:
            premium_plan = _plan_premium(session, user.id, params, variants, request_id)
            params = premium_plan.params
        else:
            # H3: the USD wallet pays the provider, but presenter reels stay
            # Pro and Agency only, under the same monthly cap (M3.1, MD8).
            _require_presenter_gate(session, user.id, params, variants, request_id)
        # M3.1: standard credits by style and length (MG3 table, MD8).
        cost = _job_credits(params)
        stored_params = {
            **_stored_params_dict(params, body),
            "_correlation_id": request_id,
            **(premium_plan.marker if premium_plan is not None else {}),
        }
        if autopublish_platforms:
            stored_params["_autopublish_platforms"] = autopublish_platforms
        stored_params = _stamp_diffusion_forecast(
            session, stored_params, body, user.id, request_id
        )
        # Canon provenance (optional, additive): when the request binds a canon
        # the caller owns, stamp its active locked version into params['canon']
        # beside params['character'] so the produced asset is verifiable/
        # regeneratable. A missing/unowned canon is a silent no-op — canon is
        # never fabricated and this must never destabilize job creation.
        stored_params = _stamp_canon_on_params(
            session, stored_params, body, user.id, request_id
        )
        try:
            from app.services.cost_guard import CostCapExceeded, enforce_cost_cap

            enforce_cost_cap(params)
        except CostCapExceeded as exc:
            logger.warning(
                f"cost guard rejected job create, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=422,
                message=f"{request_id}: {exc}",
            )
        user_id = user.id

        # One shared batch id links the N fanned-out jobs so they can be reviewed
        # together (Phase-10). Only minted for a real batch (``variants > 1``); a
        # single job stays batch-less (NULL) to preserve the classic behavior.
        batch_id: str | None = uuid.uuid4().hex if variants > 1 else None

        # A generated-script batch gives every variant its own opening-hook
        # angle (1 body / N hooks), persisted per job and seeded per pipeline.
        hook_styles = _variant_hook_styles(params, variants)
        job_ids: list[str] = []
        job_params: dict[str, Any] = {}
        for index in range(variants):
            style = hook_styles[index] if hook_styles else None
            job = JobRepository(session).create(
                user_id=user_id,
                kind=_DEFAULT_JOB_KIND,
                params=stored_params if style is None else {**stored_params, "hook_style": style},
                batch_id=batch_id,
            )
            job_ids.append(job.id)
            job_params[job.id] = params if style is None else dataclasses.replace(params, hook_style=style)

        # Debit one job's cost per created job (each tied to its job_id). If the
        # chosen pool is insufficient for the FULL batch, the failing debit raises
        # and the whole transaction rolls back — a 402 with no jobs and no
        # enqueue. A workspace job debits the SHARED pool; otherwise the personal
        # balance (unchanged classic path).
        # M3.1 charge on keep: variant 1 is paid now, variants 2-3 render
        # unpaid and are debited only when kept (POST /jobs/{id}/keep). An
        # auto-publish batch posts every variant, so it is paid in full now.
        from app.domains.reels.keep import pending_marker as _keep_marker

        keep_later = (
            _charge_on_keep_enabled()
            and wallet_intent is None
            and variants > 1
            and not autopublish_platforms
        )
        unpaid: set[str] = set()
        try:
            for index, jid in enumerate(job_ids):
                if wallet_intent is None and keep_later and index > 0:
                    job_row = JobRepository(session).get(jid)
                    job_row.params = {**(job_row.params or {}), **_keep_marker(cost, workspace_id)}
                    session.flush()
                    unpaid.add(jid)
                elif wallet_intent is not None:
                    # Wallet path: reserve the quoted max cost and stamp the
                    # reservation marker onto this job's params so the worker's
                    # terminal hook can settle (success) or release (failure).
                    marker = reserve_for_job(
                        session,
                        user_id=user_id,
                        intent=wallet_intent,
                        job_id=jid,
                        request_id=request_id,
                    )
                    job_row = JobRepository(session).get(jid)
                    job_row.params = {**(job_row.params or {}), **marker}
                    session.flush()
                elif workspace_id is not None:
                    CreditRepository(session).workspace_debit(
                        workspace_id, cost, jid, _JOB_DEBIT_REASON
                    )
                else:
                    debit_reason = pilot_debit_reason("reel", _JOB_DEBIT_REASON)
                    CreditRepository(session).debit(user_id, cost, jid, debit_reason)
                if premium_plan is not None:
                    _debit_premium(session, user_id, jid, premium_plan, request_id)
        except WalletBridgeError as exc:
            # Insufficient wallet balance (402) or a rejected quote — the whole
            # transaction rolls back, so no job runs and no hold leaks.
            raise HttpException(
                task_id=request_id,
                status_code=exc.status_code,
                message=f"{request_id}: {exc.message}",
            )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=f"{request_id}: insufficient credits: {exc}",
            )
        first_job = JobRepository(session).get(job_ids[0])
        state, progress = first_job.state, first_job.progress
        if variants == 1:
            response_data = {
                "job_id": job_ids[0],
                "state": state,
                "progress": progress,
                "correlation_id": request_id,
            }
        else:
            response_data = {
                "job_ids": job_ids,
                "job_id": job_ids[0],
                "batch_id": batch_id,
                "state": state,
                "progress": progress,
                "correlation_id": request_id,
            }
            if hook_styles:
                response_data["hook_styles"] = list(hook_styles)
            if unpaid:
                response_data["keep_required"] = [jid for jid in job_ids if jid in unpaid]
                response_data["keep_credits"] = cost
        if idempotency_row is not None:
            idempotency_row.response_data = response_data
            session.flush()

    # Debits are committed; only now is it safe to enqueue the pipelines. Each
    # variant is enqueued independently so one broker hiccup cannot lose the
    # others — a failed enqueue is reconciled with a per-job refund.
    enqueue_failures: list[str] = []
    for jid in job_ids:
        try:
            celery_task_id = pipeline.start_pipeline(jid, job_params.get(jid, params))
        except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a job
            _reconcile_failed_enqueue(
                jid, user_id, 0 if jid in unpaid else cost, str(exc), request_id, workspace_id
            )
            enqueue_failures.append(jid)
            continue
        # Persisting the Celery task id is part of enqueue: a DB error here must
        # be reconciled (refund + fail) exactly like a broker failure, otherwise
        # it would escape the loop and strand every remaining variant
        # debited-but-unenqueued.
        try:
            with get_session() as session:
                JobRepository(session).set_celery_task_id(jid, celery_task_id)
        except Exception as exc:  # noqa: BLE001 - task-id persist failure must not orphan a job
            _reconcile_failed_enqueue(
                jid, user_id, 0 if jid in unpaid else cost, str(exc), request_id, workspace_id
            )
            enqueue_failures.append(jid)
            continue

    if workspace_id is None and wallet_intent is None:
        _nudge_low_credits(user_id, cost * (variants - len(unpaid)))

    # A hook-styled batch is a 1-body/N-hooks experiment: persist it and open
    # the insights remake-winner loop so the run is tracked automatically.
    _register_hook_run(user_id, job_ids, hook_styles, enqueue_failures, request_id)

    # Single-variant behavior is preserved exactly: an enqueue failure surfaces
    # as a 502 (the job is already marked failed + refunded above).
    if variants == 1:
        if enqueue_failures:
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to enqueue job",
            )
        return utils.get_response(200, response_data)

    # Batch: report every created job plus the shared batch_id (for joint review
    # via GET /batches/{batch_id}); failed-to-enqueue variants are already marked
    # FAILED + refunded, so the client sees their real state on poll.
    return utils.get_response(200, response_data)


@router.get("/jobs", response_model=JobListResponse, summary="List jobs")
def list_jobs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    view: str = "active",
    kind: str | None = None,
    include_archived: bool = False,
):
    """List the authenticated caller's jobs (newest first), scoped by user.

    Pagination via ``limit`` (1-100) / ``offset``. Never leaks other users' jobs:
    ``JobRepository.list_for_user`` filters on the resolved user's id and never
    returns soft-deleted reels. ``view`` selects ``active`` (default, not
    archived), ``archived`` or ``all``; ``kind`` optionally narrows to one job kind.
    ``include_archived=true`` is shorthand for ``view=all`` (client-side filtering).
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    normalized_view = (view or "active").strip().lower()
    if include_archived and normalized_view == "active":
        normalized_view = "all"
    archived_filter = {"active": False, "archived": True, "all": None}.get(normalized_view, "?")
    if archived_filter == "?":
        raise HttpException(
            task_id=request_id,
            status_code=422,
            message=f"{request_id}: view must be one of active, archived, all",
        )
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        include_result = _can_access_clean_result(str(user.id), request_id)
        rows = JobRepository(session).list_for_user(
            user.id,
            limit=limit,
            offset=offset,
            archived=archived_filter,
            kind=(kind or "").strip() or None,
        )
        jobs_data = [
            _job_public_data(job, request_id, include_result=include_result)
            for job in rows
        ]
    return utils.get_response(200, {"jobs": jobs_data})


@router.get("/jobs/{job_id}", response_model=JobResponse, summary="Get job status")
def get_job(request: Request, job_id: str = Path(..., description="Job ID")):
    """Return job status; 404 (and no existence leak) for unknown/foreign jobs."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = JobRepository(session).get(job_id)
        if _hidden(job, user):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        data = _job_public_data(
            job,
            request_id,
            include_result=_can_access_clean_result(str(user.id), request_id),
        )
        # Honest queue position + measured ETA while the reel is unfinished
        # (``None`` fields are omitted rather than guessed).
        from .queue_eta import queue_status

        queue = queue_status(session, job)
        if queue is not None:
            data["queue"] = queue
    return utils.get_response(200, data)


class JobUpdateRequest(BaseModel):
    """``PATCH /jobs/{id}`` — rename and/or archive a reel."""

    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


@router.patch("/jobs/{job_id}", response_model=JobResponse, summary="Rename / archive a job")
def update_job(
    request: Request,
    body: JobUpdateRequest,
    job_id: str = Path(..., description="Job ID"),
):
    """Rename a reel (``title``; blank clears it) and/or (un)archive it."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    if body.title is None and body.archived is None:
        raise HttpException(
            task_id=request_id,
            status_code=422,
            message=f"{request_id}: provide title and/or archived",
        )
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = JobRepository(session)
        job = repo.get(job_id)
        if _hidden(job, user):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        job = repo.update_library_fields(job_id, title=body.title, archived=body.archived)
        data = _job_public_data(
            job,
            request_id,
            include_result=_can_access_clean_result(str(user.id), request_id),
        )
    return utils.get_response(200, data)


def _delete_job_artifacts(job_keys: list[str], job_id: str, request_id: str) -> int:
    """Best-effort R2 cleanup for a deleted reel's private artifacts."""
    keys = [k for k in job_keys if k]
    if not keys:
        return 0
    try:
        from app.platform.storage.r2 import get_r2_client

        r2 = get_r2_client()
    except Exception as exc:  # noqa: BLE001 - storage cleanup is best-effort
        logger.warning(f"artifact cleanup skipped for job {job_id}, request_id: {request_id}: {exc}")
        return 0
    removed = 0
    for key in keys:
        try:
            if r2.delete_object(key):
                removed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"failed to delete {key!r} for job {job_id}: {exc}")
    return removed


@router.delete("/jobs/{job_id}", summary="Delete a job")
def delete_job(request: Request, job_id: str = Path(..., description="Job ID")):
    """Soft-delete a finished reel and remove its stored media (best-effort).

    A reel that is still rendering must be cancelled first (409) so its credits
    are refunded through the cancel path rather than silently kept.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = JobRepository(session)
        job = repo.get(job_id)
        if _hidden(job, user):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        if job.state == TASK_STATE_PROCESSING:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: job is still processing; cancel it first",
            )
        keys = [
            str(getattr(job, field, "") or "").strip()
            for field in ("result_key", "poster_key", "preview_key", "cover_key")
        ]
        repo.soft_delete(job_id)
    removed = _delete_job_artifacts(keys, job_id, request_id)
    return utils.get_response(
        200, {"job_id": job_id, "deleted": True, "artifacts_removed": removed}
    )


@router.post("/jobs/{job_id}/cancel", summary="Cancel a processing job")
def cancel_reel_job(request: Request, job_id: str = Path(..., description="Job ID")):
    """Stop a processing reel and refund it.

    Credit-funded reels get their debit back (to the personal or workspace pool
    it came from) exactly once; wallet-funded reels have their hold released.
    409 when the job already finished or its kind cannot be cancelled.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = str(user.id)
    result = _cancel_job(job_id, user_id, request_id)
    return utils.get_response(200, result)


@router.post("/jobs/{job_id}/keep", summary="Keep a variant (charge on keep)")
def keep_job(request: Request, job_id: str = Path(..., description="Job ID")):
    """Keep one finished variant: debit its credits once, unlock its clean MP4.

    With charge on keep on (M3.1), variants 2-3 of a create render unpaid.
    Keeping one debits its standard credits exactly once; calling again, or
    keeping a variant paid at create, debits nothing. 404 for an unknown or
    foreign job, 409 before the render is complete, 402 when the balance is
    short (nothing is debited).
    """
    from app.domains.reels import keep as keep_mod

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            result = keep_mod.keep_job(session, job_id=job_id, user_id=str(user.id))
        except LookupError:
            raise HttpException(
                task_id=request_id, status_code=404, message=f"{request_id}: job not found"
            )
        except keep_mod.KeepNotReady as exc:
            raise HttpException(
                task_id=request_id, status_code=409, message=f"{request_id}: {exc}"
            )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=f"{request_id}: insufficient credits: {exc}",
                data={"code": "credits_required"},
            )
        job = JobRepository(session).get(job_id)
        result["job"] = _job_public_data(
            job,
            request_id,
            include_result=_can_access_clean_result(str(user.id), request_id),
        )
    return utils.get_response(200, result)


@router.get(
    "/batches/{batch_id}",
    response_model=BatchResponse,
    summary="Review a batch of variant jobs",
)
def get_batch(request: Request, batch_id: str = Path(..., description="Batch ID")):
    """Return every variant job of a batch, scoped to the authenticated caller.

    Links the N jobs a single ``POST /jobs {variants:N}`` request fanned out
    (they share one ``batch_id``) so a user can review them together. Strictly
    owner-scoped via ``JobRepository.list_by_batch`` (filters on both
    ``batch_id`` and the resolved user id), so a foreign batch is invisible.
    Returns 404 — with no existence leak — when the batch is unknown, empty, or
    owned by someone else.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = JobRepository(session).list_by_batch(batch_id, user.id)
        if not rows:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: batch not found",
            )
        include_result = _can_access_clean_result(str(user.id), request_id)
        jobs_data = [
            _batch_job_data(job, request_id, include_result=include_result)
            for job in rows
        ]
    return utils.get_response(200, {"batch_id": batch_id, "jobs": jobs_data})


def _locked_job_for_retry(session: Any, job_id: str):
    """SELECT ... FOR UPDATE the job so concurrent retries are serialized.

    Degrades to a plain get on backends without row locks (e.g. SQLite in
    tests) — the compare-and-set on ``state`` still guards correctness there
    within a single connection.
    """
    if select is None:  # pragma: no cover - guarded import already 503'd
        return session.get(Job, job_id)
    try:
        stmt = select(Job).where(Job.id == job_id).with_for_update()
        return session.execute(stmt).scalars().first()
    except NotSupportedError:
        if session.get_bind().dialect.name != "sqlite":
            raise
        # SQLite (tests): no row locks — degrade to an unlocked read.
        return session.get(Job, job_id)


def _job_funding_workspace(session: Any, job_id: str) -> str | None:
    """Recover the workspace pool that funded a job's original debit, or ``None``.

    A workspace job's create-time debit wrote a ``CreditLedger`` row tagged with
    both ``job_id`` and a non-NULL ``workspace_id`` (the SHARED pool). The ``Job``
    row carries no ``workspace_id`` column, so the ledger is the only durable
    record of which pool funded it. Returns that ``workspace_id`` so a retry can
    debit / refund the SAME pool instead of the caller's personal balance;
    ``None`` (the classic per-user path) when no such row exists.
    """
    stmt = (
        select(CreditLedger.workspace_id)
        .where(
            CreditLedger.job_id == job_id,
            CreditLedger.workspace_id.isnot(None),
        )
        .order_by(CreditLedger.id.asc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


@router.post(
    "/jobs/{job_id}/retry", response_model=JobResponse, summary="Retry a failed job"
)
def retry_job(request: Request, job_id: str = Path(..., description="Job ID")):
    """Re-enqueue a failed job from its ``failed_stage`` (§5.2, §6.3).

    Concurrency-safe: the job row is locked and a FAILED->PROCESSING
    compare-and-set is committed before any enqueue, so two concurrent retries
    cannot both win — the loser gets a 409. Retries are charged the same credit
    cost as a fresh job (refunded if the re-enqueue fails).

    A retry bills the SAME pool that funded the original job: a job created
    against a workspace SHARED pool is re-charged (and, on enqueue failure,
    refunded) to that pool, recovered from the credit ledger; a plain job stays
    on the caller's personal balance.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)

    # Editor exports share the canonical job poll/retry contract, but are
    # zero-credit FFmpeg work and must return to the render queue rather than
    # entering the avatar-reel DAG.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        candidate = JobRepository(session).get(job_id)
        if _hidden(candidate, user):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        if candidate.kind == "editor_export":
            user_id = str(user.id)
        elif candidate.kind != _DEFAULT_JOB_KIND:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: this job kind does not support in-place retry",
            )
        else:
            user_id = ""
    if user_id:
        return _retry_editor_export_job(job_id, user_id, request_id)

    reelforge = _import_reelforge(request_id)
    pipeline = _import_pipeline(request_id)
    cost = _job_cost()

    # The workspace pool that funded the original job, or ``None`` for the classic
    # per-user path. Bound outside the transaction so the post-commit enqueue
    # reconcile can route refunds to the right pool.
    workspace_id: str | None = None

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        from app.core.capabilities import pilot_debit_reason, require_generation_access

        require_generation_access(request, session, user.id, "reel", cost, request_id)
        job = _locked_job_for_retry(session, job_id)
        if _hidden(job, user):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        # Compare-and-set: only a job still in FAILED may be retried. A job that
        # is already PROCESSING (a racing retry won, or it never failed) yields
        # a 409 instead of a duplicate enqueue.
        if job.state != TASK_STATE_FAILED:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: job is not in a retryable (failed) state",
            )
        failed_stage = job.failed_stage
        params = _build_params_from_stored(job.params, reelforge, request_id)
        _validate_layout(params, request_id)
        # Re-check format availability before the retry debit: a job created while
        # a paid key was set must be refused (402 format_locked), not charged and
        # failed again. A retry reuses the script the job already wrote.
        from app.core.launch.formats import reuse_persisted_script

        params = reuse_persisted_script(params, getattr(job, "script", ""))
        _validate_enabled_feature_secrets(params, request_id)
        premium_plan = _plan_premium(session, user.id, params, 1, request_id)
        params = premium_plan.params
        cost = _job_credits(params)
        job.params = _planned_params(
            {
                **(dict(job.params) if isinstance(job.params, dict) else {}),
                "_correlation_id": request_id,
            },
            params,
            premium_plan,
            copied=False,
        )
        user_id = user.id
        # Recover the pool that funded the ORIGINAL debit: a workspace job's
        # create-time debit is recorded only in the ledger (the Job row has no
        # workspace_id column), so a retry must debit the SAME pool instead of
        # always charging the caller's personal balance.
        workspace_id = _job_funding_workspace(session, job_id)
        from app.domains.reels.keep import KEEP_KEY as _KEEP_KEY, mark_kept as _mark_kept

        if workspace_id is None:
            # An unpaid charge-on-keep variant has no debit yet: its marker
            # names the pool the create would have used.
            workspace_id = ((job.params or {}).get(_KEEP_KEY) or {}).get("workspace_id") or None
        # Charge the retry atomically in the same locked transaction (402 if the
        # pool/balance is insufficient) — retries are not free. A workspace job
        # re-debits the SHARED pool; otherwise the personal balance.
        try:
            if workspace_id is not None:
                CreditRepository(session).workspace_debit(
                    workspace_id, cost, job_id, _JOB_DEBIT_REASON
                )
            else:
                CreditRepository(session).debit(
                    user_id, cost, job_id, pilot_debit_reason("reel", _JOB_DEBIT_REASON)
                )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=f"{request_id}: insufficient credits: {exc}",
            )
        _debit_premium(session, user_id, job_id, premium_plan, request_id)
        # A paid retry of an unpaid variant is a keep: its clean MP4 is paid for.
        job.params = _mark_kept(job.params)
        # Win the race: flip to PROCESSING and reset the failure markers so the
        # retried run starts clean. Committing this before enqueue means the
        # loser observes PROCESSING and is rejected above.
        job.state = TASK_STATE_PROCESSING
        job.error = ""
        job.failed_stage = ""
        job.progress = 0
        state, progress = job.state, job.progress

    try:
        celery_task_id = pipeline.retry_pipeline(job_id, params, failed_stage)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"retry enqueue failed for job {job_id}, request_id: {request_id}: {exc}"
        )
        # Reconcile in TWO isolated transactions (via _refund_and_fail_job): the
        # FAILED transition is committed on its own session first, then the refund
        # runs on a separate session. A DB error inside the refund can therefore
        # never roll back the committed mark_failed nor leak the retry credit —
        # the single-session mark_failed+grant pattern here previously could.
        _refund_and_fail_job(
            job_id,
            user_id,
            cost,
            failed_stage or "enqueue",
            str(exc),
            request_id,
            workspace_id,
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to re-enqueue job",
        )

    # Persisting the Celery task id is part of enqueue: a commit failure here must
    # be reconciled (refund + fail) exactly like a broker failure, otherwise it
    # would surface as an unhandled 500 for an operation that actually succeeded
    # and the job would be stuck PROCESSING with no persisted celery_task_id.
    try:
        with get_session() as session:
            JobRepository(session).set_celery_task_id(job_id, celery_task_id)
    except Exception as exc:  # noqa: BLE001 - task-id persist failure must not orphan a job
        _reconcile_failed_enqueue(
            job_id, user_id, cost, str(exc), request_id, workspace_id
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to re-enqueue job",
        )

    return utils.get_response(
        200,
        {
            "job_id": job_id,
            "state": state,
            "progress": progress,
            "correlation_id": request_id,
        },
    )


def _retry_editor_export_job(job_id: str, user_id: str, request_id: str):
    """Compare-and-set and dispatch one failed editor export without a debit."""
    with get_session() as session:
        job = _locked_job_for_retry(session, job_id)
        if job is None or str(job.user_id) != user_id:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        if job.state != TASK_STATE_FAILED:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: job is not in a retryable (failed) state",
            )
        job.state = TASK_STATE_PROCESSING
        job.error = ""
        job.failed_stage = ""
        job.progress = 0
        job.stages = {**(job.stages or {}), "export": "queued"}
        session.flush()

    try:
        from app.workers.tasks import export_editor_cut_task

        task = export_editor_cut_task.apply_async(
            args=[{"job_id": job_id, "request_id": request_id}],
            headers={"correlation_id": request_id},
        )
        with get_session() as session:
            JobRepository(session).set_celery_task_id(job_id, task.id)
    except Exception as exc:  # noqa: BLE001 - keep terminal state authoritative
        from app.domains.editor.service import mark_enqueue_failure

        mark_enqueue_failure(job_id, str(exc))
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: editor export could not be re-queued",
        ) from exc
    return utils.get_response(
        200,
        {
            "job_id": job_id,
            "state": TASK_STATE_PROCESSING,
            "progress": 0,
            "correlation_id": request_id,
        },
    )


def _nudge_low_credits(user_id: str, spent: int) -> None:
    """Emit a one-time ``low_credits`` nudge when this debit crossed the threshold.

    Fires only on the crossing (balance before the debit above the threshold,
    after it at/below), so repeated jobs at a low balance do not spam. Never
    raises.
    """
    try:
        from app.services import notifications

        with get_session() as session:
            balance = CreditRepository(session).balance(user_id)
        threshold = notifications.DEFAULT_LOW_CREDITS_THRESHOLD
        if balance <= threshold < balance + int(spent):
            notifications.notify_low_credits(user_id, balance, threshold)
    except Exception as exc:  # noqa: BLE001 - a nudge must never fail job creation
        logger.warning(f"low-credits nudge failed for {user_id}: {exc}")


def _split_autopublish(params: Any, user_id: str, request_id: str):
    """Strip ``platforms`` off the render params and validate them for auto-publish.

    Returns ``(params_without_platforms, platforms)``. When platforms were
    requested the publishing launch gate must be open and the caller must have a
    usable native connection for every one of them (checked now so the request
    fails fast instead of rendering a reel that can never be posted).
    """
    platforms = [str(p).strip().lower() for p in (params.platforms or ()) if str(p).strip()]
    stripped = dataclasses.replace(params, platforms=())
    if not platforms:
        return stripped, []
    from app.core.launch.policy import require_publishing_enabled
    from app.domains.publishing.native_service import (
        NativePublishError,
        require_native_connections,
    )

    require_publishing_enabled(request_id)
    try:
        require_native_connections(user_id, platforms)
    except NativePublishError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc}",
        ) from exc
    return stripped, list(dict.fromkeys(platforms))


def _build_params_from_stored(stored: Any, reelforge, request_id: str):
    """Rebuild ``ReelForgeParams`` from the persisted ``Job.params`` JSON."""
    data = dict(stored) if isinstance(stored, dict) else {}
    allowed = {f.name for f in dataclasses.fields(reelforge.ReelForgeParams)}
    filtered = {k: v for k, v in data.items() if k in allowed}
    # Re-runs / retries / dubs never cross-post from inside the render pipeline
    # (that path used the operator's shared Upload-Post account). Publishing is
    # done afterwards through the owner's native connections.
    filtered["platforms"] = ()
    if isinstance(filtered.get("effects"), list):
        filtered["effects"] = tuple(filtered["effects"])
    try:
        return reelforge.ReelForgeParams(**filtered)
    except (TypeError, ValueError) as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: stored job params are invalid: {exc}",
        )


# --------------------------------------------------------------------------- #
# Re-run with tweaks (Phase 6)
# --------------------------------------------------------------------------- #
# Overrides accepted by ``POST /jobs/{job_id}/rerun`` mapped to the persisted
# ``Job.params`` key they write. ``voice_id`` and the caption/layout/language/
# music tweaks are handled explicitly in :func:`_apply_rerun_overrides` because
# ``voice_id`` needs ``elevenlabs:`` normalisation.
_RERUN_OVERRIDE_KEYS: tuple[str, ...] = (
    "avatar_id",
    "layout",
    "caption_style",
    "music_id",
    "language",
)


def _apply_rerun_overrides(stored: dict, body: RerunRequest) -> dict:
    """Return a NEW params dict = source ``stored`` params + applied overrides.

    Immutable by construction (the source dict is copied, never mutated). Only
    the override fields a client actually set are applied; ``voice_id`` is
    normalised to the ``elevenlabs:<id>`` ``voice_name`` form used elsewhere.
    Unknown/None override fields are ignored so a sparse body is a clean
    re-render of the source job.
    """
    merged = dict(stored) if isinstance(stored, dict) else {}
    overrides = getattr(body, "overrides", None)
    if overrides is None:
        return merged

    if hasattr(overrides, "model_dump"):
        ov = overrides.model_dump(exclude_none=True)
    elif isinstance(overrides, dict):
        ov = {k: v for k, v in overrides.items() if v is not None}
    else:
        ov = {
            k: v
            for k, v in dict(getattr(overrides, "__dict__", {})).items()
            if v is not None
        }

    voice_id = ov.get("voice_id")
    if voice_id:
        merged["voice_name"] = _normalize_voice_id(voice_id)
    for key in _RERUN_OVERRIDE_KEYS:
        value = ov.get(key)
        if value:
            merged[key] = str(value)
    hook_style = ov.get("hook_style")
    if hook_style:
        merged["hook_style"] = str(hook_style)
    return merged


def _rerun_hook_conflict(stored: dict, body: RerunRequest) -> bool:
    """A hook-angle variation was asked of a reel whose script the creator wrote.

    Generation honours ``hook_style`` only when it writes the script, so such a
    re-run would be a duplicate of the source; the caller refuses it (409).
    """
    overrides = getattr(body, "overrides", None)
    if overrides is None or not getattr(overrides, "hook_style", None):
        return False
    params = stored if isinstance(stored, dict) else {}
    return bool(str(params.get("video_script") or "").strip()
                or str(params.get("translate_source_script") or "").strip())


@router.post(
    "/jobs/{job_id}/rerun",
    response_model=JobResponse,
    summary="Re-run a job with tweaks",
)
def rerun_job(
    request: Request,
    body: RerunRequest,
    job_id: str = Path(..., description="Source job ID"),
):
    """Clone a job's params, apply tweaks, and enqueue it as a brand-new job (Phase 6).

    Order mirrors :func:`create_job`: auth -> rate limit -> ownership (404 on
    unknown/foreign source, no existence leak) -> clone source ``Job.params`` +
    apply overrides -> persist a NEW Job row AND debit 1 credit in ONE committed
    transaction (402 on insufficient balance, nothing enqueued) -> only then
    enqueue the pipeline. A failed enqueue reconciles the new job with a refund
    (identical invariant to create). Returns ``{job_id}`` of the new job.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    reelforge = _import_reelforge(request_id)
    pipeline = _import_pipeline(request_id)
    cost = _job_cost()

    # One committed transaction: resolve the source, build the new job's params,
    # create the new Job row and debit its cost atomically. Any failure rolls the
    # whole unit back — no orphan job, no debit, nothing enqueued.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        from app.core.capabilities import pilot_debit_reason, require_generation_access

        require_generation_access(request, session, user.id, "reel", cost, request_id)
        # Re-runs spend credits and pipeline time exactly like a fresh create, so
        # they share the per-user job-creation rate limit (fail-open if Redis is
        # down). Applied once, before the source lookup / credit check.
        enforce_rate_limit(
            request,
            f"jobs:{user.id}",
            limit=_jobs_rate_limit(),
            window_s=_jobs_rate_window_s(),
        )
        source = JobRepository(session).get(job_id)
        if _hidden(source, user):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )

        if _rerun_hook_conflict(source.params, body):
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: this reel uses your own script, so a new hook "
                        "would not change it; pick a reel Menivor wrote",
            )
        stored_params = {
            **_apply_rerun_overrides(source.params, body),
            "_correlation_id": request_id,
        }
        params = _build_params_from_stored(stored_params, reelforge, request_id)
        _validate_layout(params, request_id)
        _validate_enabled_feature_secrets(params, request_id)
        premium_plan = _plan_premium(session, user.id, params, 1, request_id)
        params = premium_plan.params
        cost = _job_credits(params)
        stored_params = _planned_params(stored_params, params, premium_plan, copied=True)
        user_id = user.id

        new_job = JobRepository(session).create(
            user_id=user_id, kind=_DEFAULT_JOB_KIND, params=stored_params
        )
        new_job_id = new_job.id
        # Debit the re-run's cost in the same transaction (402 if insufficient) —
        # a re-run is never free.
        try:
            CreditRepository(session).debit(
                user_id, cost, new_job_id, pilot_debit_reason("reel", _JOB_DEBIT_REASON)
            )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=f"{request_id}: insufficient credits: {exc}",
            )
        _debit_premium(session, user_id, new_job_id, premium_plan, request_id)
        state, progress = new_job.state, new_job.progress

    # Debit committed; only now enqueue. A broker/task-id-persist failure is
    # reconciled with a refund + FAILED transition (the job is already created).
    try:
        celery_task_id = pipeline.start_pipeline(new_job_id, params)
    except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a job
        _reconcile_failed_enqueue(new_job_id, user_id, cost, str(exc), request_id)
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to enqueue re-run job",
        )
    try:
        with get_session() as session:
            JobRepository(session).set_celery_task_id(new_job_id, celery_task_id)
    except Exception as exc:  # noqa: BLE001 - task-id persist failure must not orphan a job
        _reconcile_failed_enqueue(new_job_id, user_id, cost, str(exc), request_id)
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to enqueue re-run job",
        )

    return utils.get_response(
        200,
        {
            "job_id": new_job_id,
            "state": state,
            "progress": progress,
            "correlation_id": request_id,
        },
    )


# --------------------------------------------------------------------------- #
# Multi-language dubbing (§ dubbing): fan a finished reel out into N target
# languages. Each language translates the source SCRIPT and re-runs the normal
# pipeline, reusing the source's screen recording / avatar / voice / layout /
# caption style. The N jobs share ONE batch_id (existing batch-review UI).
# --------------------------------------------------------------------------- #
# Cap the fan-out so one request can never spawn (or debit) unbounded work. The
# supported set is small (7 languages); this is a hard structural ceiling.
_MAX_DUB_LANGUAGES: int = 12


def _resolve_dub_languages(body: DubRequest, translate, request_id: str) -> list[str]:
    """Validate + normalise the requested target languages (400 on any problem).

    Returns the trimmed language codes in request order (duplicates preserved —
    one credit / job is charged per entry). Raises a clean 400 *before* any
    credit is debited when the list is empty, over the fan-out cap, or contains
    an empty / unsupported code, so a hostile payload can never fan out unbounded
    work nor burn a credit on a language the fonts / TTS cannot render.
    """
    raw: Any = getattr(body, "languages", None)
    if not isinstance(raw, (list, tuple)) or not raw:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: at least one target language is required",
        )
    codes = [str(code).strip() for code in raw]
    if len(codes) > _MAX_DUB_LANGUAGES:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: too many languages "
                f"(max {_MAX_DUB_LANGUAGES}, got {len(codes)})"
            ),
        )
    for code in codes:
        if not code or not translate.is_supported_language(code):
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: unsupported dubbing language {code!r}",
            )
    return codes


def _build_dub_params(source_params: Any, language: str, source_script: str) -> dict:
    """Return a NEW params dict = source params + the dub overrides (immutable).

    Clones the source job's persisted ``Job.params`` (never mutating it) and sets
    only the two dub fields: ``language`` (the target) and
    ``translate_source_script`` (the finished source script the pipeline
    re-translates). Everything else — ``screen_recording_key`` / ``avatar_id`` /
    ``voice_name`` / ``layout`` / ``caption_style`` — is inherited unchanged so
    the dub reuses the source's recording, avatar, voice and look.
    """
    stored = dict(source_params) if isinstance(source_params, dict) else {}
    stored["language"] = language
    stored["translate_source_script"] = source_script
    return stored


@router.post(
    "/jobs/{job_id}/dub",
    response_model=DubResponse,
    summary="Dub a finished reel into N target languages",
)
def dub_job(
    request: Request,
    body: DubRequest,
    job_id: str = Path(..., description="Source job ID"),
):
    """Fan a finished reel out into N language-dubbed jobs under one batch (§ dubbing).

    Order mirrors :func:`create_job` / :func:`rerun_job`: auth -> rate limit ->
    ownership (404 on unknown/foreign source, no existence leak) -> require the
    source has a finalized ``script`` (409 if not available yet) -> validate every
    target language (400 on empty/unknown) -> persist ``N`` new Job rows sharing
    ONE ``batch_id`` AND debit ``N × cost`` credits in ONE committed transaction
    (402 on insufficient balance for the *full* set, enqueuing none) -> only then
    start each Celery pipeline. Each new job clones the source params but sets
    ``language`` to the target and ``translate_source_script`` to the source
    script, reusing the source's screen recording / avatar / voice / layout /
    caption style. A failed enqueue reconciles that job with a refund (identical
    debit-before-enqueue invariant as create). Returns
    ``{batch_id, job_ids, languages}``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    reelforge = _import_reelforge(request_id)
    pipeline = _import_pipeline(request_id)
    translate = _import_translate(request_id)
    cost = _job_cost()

    # One committed transaction: resolve the source, build every dub job's params,
    # create the N Job rows (sharing one batch_id) and debit their combined cost
    # atomically. Any failure rolls the whole unit back — no orphan jobs, no
    # partial debit, nothing enqueued.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        # Dubs spend credits + pipeline time like a fresh create, so they share
        # the per-user job-creation rate limit (fail-open if Redis is down).
        enforce_rate_limit(
            request,
            f"jobs:{user.id}",
            limit=_jobs_rate_limit(),
            window_s=_jobs_rate_window_s(),
        )
        source = JobRepository(session).get(job_id)
        if _hidden(source, user):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        # A dub translates the source's finalized script; it must exist first.
        source_script = (getattr(source, "script", "") or "").strip()
        if not source_script:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=(
                    f"{request_id}: source job has no script yet; "
                    "it must finish (or reach the script stage) before it can be dubbed"
                ),
            )
        languages = _resolve_dub_languages(body, translate, request_id)
        from app.core.capabilities import pilot_debit_reason, require_generation_access

        require_generation_access(
            request, session, user.id, "reel", cost * len(languages), request_id
        )
        source_params = dict(source.params) if isinstance(source.params, dict) else {}
        user_id = user.id

        # One shared batch id links the N dubbed jobs so they can be reviewed
        # together via GET /batches/{batch_id} (Phase-10 batch-review UI).
        batch_id: str = uuid.uuid4().hex

        # Build each dub job + its validated render params up front so an invalid
        # (e.g. unsupported layout inherited from the source) params set is a
        # clean 400 before any credit is debited.
        jobs_and_params: list[tuple[str, Any]] = []
        job_ids: list[str] = []
        for language in languages:
            stored_params = {
                **_build_dub_params(source_params, language, source_script),
                "_correlation_id": request_id,
            }
            params = _build_params_from_stored(stored_params, reelforge, request_id)
            _validate_layout(params, request_id)
            _validate_enabled_feature_secrets(params, request_id)
            # Planned and debited per language, so later languages see the
            # credits the earlier ones already took.
            premium_plan = _plan_premium(session, user_id, params, 1, request_id)
            params = premium_plan.params
            cost = _job_credits(params)
            stored_params = _planned_params(stored_params, params, premium_plan, copied=True)
            new_job = JobRepository(session).create(
                user_id=user_id,
                kind=_DEFAULT_JOB_KIND,
                params=stored_params,
                batch_id=batch_id,
            )
            _debit_premium(session, user_id, new_job.id, premium_plan, request_id)
            job_ids.append(new_job.id)
            jobs_and_params.append((new_job.id, params))

        # Debit one job's cost per dubbed job. If the balance is insufficient for
        # the FULL set, the failing debit raises and the whole transaction rolls
        # back — a 402 with no jobs and no enqueue.
        try:
            for jid in job_ids:
                CreditRepository(session).debit(
                    user_id, cost, jid, pilot_debit_reason("reel", _JOB_DEBIT_REASON)
                )
        except ValueError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=f"{request_id}: insufficient credits: {exc}",
            )

    # Debits are committed; only now is it safe to enqueue. Each dub is enqueued
    # independently so one broker hiccup cannot lose the others — a failed enqueue
    # (or task-id persist) is reconciled with a per-job refund + FAILED transition.
    for jid, params in jobs_and_params:
        try:
            celery_task_id = pipeline.start_pipeline(jid, params)
        except Exception as exc:  # noqa: BLE001 - enqueue failure must not orphan a job
            _reconcile_failed_enqueue(jid, user_id, cost, str(exc), request_id)
            continue
        try:
            with get_session() as session:
                JobRepository(session).set_celery_task_id(jid, celery_task_id)
        except Exception as exc:  # noqa: BLE001 - task-id persist failure must not orphan a job
            _reconcile_failed_enqueue(jid, user_id, cost, str(exc), request_id)
            continue

    return utils.get_response(
        200,
        {
            "batch_id": batch_id,
            "job_ids": job_ids,
            "languages": languages,
            "correlation_id": request_id,
        },
    )


# --------------------------------------------------------------------------- #
# AI B-roll cutaways (§ b-roll): suggest short, relevant stock clips for a job
# so a caller can splice one as a brief muted INTRO/OUTRO around the reel. This
# repurposes MPT's stock-footage path (disabled for the main pipeline) as an
# OPTIONAL creative overlay — it is strictly best-effort and never blocks a job.
# --------------------------------------------------------------------------- #
def _job_broll_context(job: Any) -> tuple[str, str]:
    """Extract the ``(subject, script)`` a B-roll suggestion should search on.

    ``subject`` is the job's ``video_subject`` (from the persisted ``Job.params``)
    and ``script`` is the finalized narration when available (``Job.script``,
    persisted by the script stage) falling back to any manual
    ``params.video_script``. Both are derived from the *job's own* data — never
    from client input — so the caller cannot inject an arbitrary search prompt.
    """
    params = dict(job.params) if isinstance(getattr(job, "params", None), dict) else {}
    subject = str(params.get("video_subject") or "").strip()
    script = (getattr(job, "script", "") or "").strip()
    if not script:
        script = str(params.get("video_script") or "").strip()
    return subject, script


@router.post(
    "/jobs/{job_id}/broll/suggest",
    response_model=BrollSuggestResponse,
    summary="Suggest B-roll cutaway clips for a job",
)
def suggest_broll(
    request: Request,
    body: BrollSuggestRequest,
    job_id: str = Path(..., description="Job ID"),
):
    """Suggest short, relevant stock B-roll clips for a job (best-effort, § b-roll).

    Order: auth -> ownership (404 on unknown/foreign job, no existence leak) ->
    per-user rate limit (this call hits an external stock provider AND the LLM for
    keyword generation, so it is rate-limited independently of job creation) ->
    fetch suggestions via ``broll.suggest_broll`` using the *job's own*
    subject/script (never client input). Each returned clip's ``broll_key`` is
    written under this job's own ``jobs/<job_id>/broll/`` prefix, so it is owned
    by this job. B-roll is best-effort: a provider/LLM failure yields an empty
    ``clips`` list rather than an error — it never fails the job.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    broll = _import_broll(request_id)

    # Resolve auth + ownership + search context inside the session, then close it
    # before the (slow, external) suggestion call so we never hold a DB connection
    # across network + LLM I/O.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = JobRepository(session).get(job_id)
        if _hidden(job, user):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        # Rate limit AFTER ownership so only the owner's own calls draw down their
        # budget. Fail-open if Redis is down (mirrors the job-creation limiter).
        enforce_rate_limit(
            request,
            f"broll:{user.id}",
            limit=_broll_rate_limit(),
            window_s=_broll_rate_window_s(),
        )
        subject, script = _job_broll_context(job)

    source = (body.source or "").strip() or "pexels"
    # ``suggest_broll`` clamps ``amount`` internally; pass the request value when
    # set, else let the service default apply.
    kwargs: dict[str, Any] = {"source": source}
    if body.amount is not None:
        kwargs["amount"] = int(body.amount)

    # Best-effort: the service swallows its own failures and returns an empty list,
    # but guard the call too so a truly unexpected error degrades to "no clips"
    # instead of a 500 — a B-roll failure must never surface as a hard error.
    try:
        clips = broll.suggest_broll(job_id, subject=subject, script=script, **kwargs)
    except Exception as exc:  # noqa: BLE001 - best-effort: never fail on suggestion
        logger.warning(
            f"broll suggestion failed for job {job_id}, request_id: {request_id}: {exc}"
        )
        clips = []

    return utils.get_response(200, {"clips": clips or []})


@router.get("/avatars", response_model=AvatarListResponse, summary="List avatars")
def list_avatars(request: Request):
    """Merge the user's (and global) ``AvatarPreset`` rows with live provider avatars."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        presets = (
            session.query(AvatarPreset)
            .filter(
                AvatarPreset.is_active.is_(True),
                or_(AvatarPreset.user_id == user.id, AvatarPreset.user_id.is_(None)),
            )
            .all()
        )
        result: list[dict] = [
            {
                "id": p.id,
                "provider": p.provider,
                "provider_avatar_id": p.provider_avatar_id,
                "display_name": p.display_name,
                "voice_name": p.voice_name,
                "thumbnail_url": p.thumbnail_url,
                "source": "preset",
            }
            for p in presets
        ]

    provider_ok = True
    try:
        from app.services.avatar.base import get_avatar_provider

        provider = get_avatar_provider("heygen")
        for avatar in provider.list_avatars() or []:
            result.append({**avatar, "source": "provider"})
    except Exception as exc:  # noqa: BLE001 - provider listing is best-effort
        provider_ok = False
        logger.warning(
            f"avatar provider listing failed, request_id: {request_id}: {exc}"
        )

    response = _list_response(result)
    if not provider_ok:
        response["message"] = "avatar_provider_unavailable"
    return response


def _list_response(items: list) -> dict:
    """``{status: 200, data: [...]}`` even when ``items`` is empty.

    ``utils.get_response`` drops falsy ``data``, which fails the list response
    models (``data`` is required) and turns an empty catalog into a 500 that
    carries no CORS headers, so browsers report a network error instead.
    """
    return {"status": 200, "data": list(items or [])}


_VOICES_RESOURCE: str = "voices.yaml"
_VOICE_LANGUAGES: frozenset[str] = frozenset({"tr", "en", "multi"})


def _normalize_curated_voice(raw: Any) -> dict[str, Any] | None:
    """Normalise a raw YAML voice entry to ``{id,name,language,gender,description}``.

    Returns ``None`` for entries missing the required ``id``/``name`` so a
    partially-malformed file degrades gracefully instead of serving junk.
    """
    if not isinstance(raw, dict):
        return None
    voice_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not voice_id or not name:
        return None
    language = str(raw.get("language") or "multi").strip().lower()
    if language not in _VOICE_LANGUAGES:
        language = "multi"
    return {
        "id": voice_id,
        "name": name,
        "language": language,
        "gender": str(raw.get("gender") or "").strip().lower(),
        "description": str(raw.get("description") or "").strip(),
        "provider": "elevenlabs",
    }


def _load_curated_voices(request_id: str) -> list[dict[str, Any]] | None:
    """Load the curated voice catalog from ``resource/voices.yaml``.

    Returns the normalised list, or ``None`` when the file is missing/unreadable/
    empty so the caller can fall back to live provider listing. The voice ids in
    the file are curated defaults and are fully overridable (see the file header).
    """
    try:
        import os

        import yaml
    except Exception as exc:  # noqa: BLE001 - PyYAML absent -> fall back
        logger.warning(f"PyYAML unavailable, request_id: {request_id}: {exc}")
        return None

    path = os.path.join(utils.resource_dir(), _VOICES_RESOURCE)
    if not os.path.isfile(path):
        logger.info(f"curated voices file missing at {path}, request_id: {request_id}")
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001 - malformed YAML -> fall back
        logger.warning(
            f"failed to read curated voices at {path}, request_id: {request_id}: {exc}"
        )
        return None

    raw_voices = doc.get("voices") if isinstance(doc, dict) else None
    if not isinstance(raw_voices, list):
        logger.warning(
            f"curated voices file has no 'voices' list, request_id: {request_id}"
        )
        return None

    voices = [v for v in (_normalize_curated_voice(r) for r in raw_voices) if v]
    return voices or None


@router.get("/voices", response_model=VoiceListResponse, summary="List voices")
def list_voices(request: Request):
    """Return the curated voice catalog (list[dict]).

    Serves ``resource/voices.yaml`` (CTO §4/§5.2) normalised to the shape
    ``{id,name,language,gender,description}``. Falls back to listing voices live
    from the configured ElevenLabs account when the curated file is absent.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        _resolve_user(request, session, request_id)

    curated = _load_curated_voices(request_id)
    if curated:
        return _list_response(curated)

    # Fallback: live provider listing (previous behaviour) when the curated
    # catalog is unavailable. Best-effort — never fails the request.
    voices: list[dict] = []
    try:
        from app.services import voice as voice_service

        api_key = config.elevenlabs.get("api_key", "")
        for item in voice_service.get_elevenlabs_voices(api_key) or []:
            parts = item.split(":")
            if len(parts) >= 3:
                voices.append(
                    {
                        "id": parts[1],
                        "name": ":".join(parts[2:]),
                        "language": "multi",
                        "gender": "",
                        "description": "",
                        "provider": "elevenlabs",
                    }
                )
    except Exception as exc:  # noqa: BLE001 - voice listing is best-effort
        logger.warning(f"voice listing failed, request_id: {request_id}: {exc}")

    return _list_response(voices)


@router.get("/me", response_model=MeResponse, summary="Current user")
def me(request: Request):
    """Return the authenticated user's profile, credit balance and job count."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            credits = CreditRepository(session).balance(user.id)
        except Exception as exc:  # noqa: BLE001 - fall back to denormalized cache
            logger.warning(f"credit balance lookup failed for {user.id}: {exc}")
            credits = int(getattr(user, "credits", 0) or 0)
        jobs_count = session.query(Job).filter(Job.user_id == user.id).count()
        data = {
            "user_id": user.id,
            "email": user.email,
            "credits": credits,
            "jobs_count": jobs_count,
            # The caller's OWN platform-admin flag, so clients can hide admin
            # UI without probing a staff-only endpoint (403 noise). Admin
            # routes still enforce is_staff server-side.
            "is_staff": bool(getattr(user, "is_staff", False)),
        }
    return utils.get_response(200, data)


# One-flow run experiments (``POST /experiments/runs``): a link run starts one
# job per hook and registers the set here; topic runs register in ``create_job``.
from app.domains.experiments.router import router as _experiment_runs_router  # noqa: E402

router.include_router(_experiment_runs_router)
