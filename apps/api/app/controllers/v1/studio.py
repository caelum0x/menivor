"""ReelForge Studio v1 API controller (Phase 3).

Adds two on-demand studio endpoints under ``/api/v1`` that complement the core
job lifecycle in :mod:`app.controllers.v1.jobs`:

* ``POST /jobs/{job_id}/publish`` — re-publish a *completed* job's rendered
  output to social platforms after the fact (auth + ownership; ``409`` when the
  job is not yet done). Delegates to
  :func:`app.services.publish.publish_job_output`.
* ``POST /avatars`` — create a USER photo→avatar preset from an uploaded image
  (``AvatarPreset`` row, ``provider='heygen'``, ``is_active=true``).

``GET /avatars`` deliberately lives in :mod:`app.controllers.v1.jobs` and is
**not** duplicated here.

Design notes
------------
* Reuses the persistence guard + auth helpers from ``jobs.py`` (import-safe: a
  missing DB layer degrades to a clean ``503`` rather than an import crash).
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.launch import require_publishing_enabled

# Reuse the guarded persistence import + auth helpers from jobs.py (which owns
# the canonical guard block) so this module stays DRY and import-safe. When the
# DB layer is absent these are ``None`` and ``_require_db`` raises a 503.
from app.controllers.v1.jobs import (
    AvatarPreset,
    Job,
    _require_db,
    _resolve_user,
    get_session,
)
from app.models.const import REELFORGE_STAGE_COMPLETE, TASK_STATE_COMPLETE
from app.models.exception import HttpException
from app.models.schema import (
    CreateAvatarRequest,
    CreateAvatarResponse,
    PublishRequest,
    PublishResponse,
)
from app.services.billing.pro_access import require_pro_action
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_HEYGEN_PROVIDER: str = "heygen"

# ``AvatarPreset.config['kind']`` marker for a creator photo→avatar preset. The
# stored ``provider_avatar_id`` is HeyGen's ``talking_photo_id`` and the render
# path drives it with ``character={'type':'talking_photo', ...}`` (§ custom-avatar).
_TALKING_PHOTO_KIND: str = "talking_photo"

# Timeout (seconds) for streaming the caller's uploaded image out of R2 before
# handing it to the provider. Bounded so a slow/stuck object store cannot hang
# the request indefinitely.
_IMAGE_DOWNLOAD_TIMEOUT_S: int = 60

# Stage name used by ``app.services.publish`` when it appends the ``JobEvent``
# audit rows for a publish (mirrors ``publish._PUBLISH_STAGE``). A completed
# event for this stage marks a job's output as already published and is the
# idempotency signal for :func:`publish_job`.
_PUBLISH_STAGE: str = "publish"

# Per-user + per-job publish rate limit (fixed window). Bounds abusive repeat
# publishing against the operator's upload-post.com account (each publish spends
# the operator's credentials, not the caller's credits). Both config-overridable.
_DEFAULT_PUBLISH_RATE_LIMIT: int = 5
_DEFAULT_PUBLISH_RATE_WINDOW_S: int = 3600


def _publish_rate_limit() -> int:
    """Max publishes per window per user+job (config ``reelforge_publish_rate_limit``)."""
    return int(
        config.app.get("reelforge_publish_rate_limit", _DEFAULT_PUBLISH_RATE_LIMIT)
    )


def _publish_rate_window_s() -> int:
    """Publish rate-limit window in seconds (config ``reelforge_publish_rate_window_s``)."""
    return int(
        config.app.get(
            "reelforge_publish_rate_window_s", _DEFAULT_PUBLISH_RATE_WINDOW_S
        )
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _try_heygen_talking_photo(image_key: str) -> str:
    """Retained legacy probe (kept as a stable monkeypatch target).

    Superseded by the provider-driven flow in :func:`create_avatar`
    (:func:`_download_image_to_temp` + :func:`_create_talking_photo`), which
    creates a *real* HeyGen talking-photo from the caller's owned image. This
    thin probe is kept so existing callers/tests that patch it keep resolving;
    it best-effort asks the client for a talking-photo capability and returns the
    resulting id (or an empty string when none is available).
    """
    try:
        from app.services.avatar.heygen import HeyGenClient

        client = HeyGenClient()
        for method_name in ("create_talking_photo", "upload_talking_photo", "upload_image"):
            method = getattr(client, method_name, None)
            if callable(method):
                result = method(image_key)
                return str(result or "").strip()
    except Exception as exc:  # noqa: BLE001 - optional path; degrade to fallback
        logger.warning(f"heygen talking-photo creation unavailable: {exc}")
    return ""


def _preset_public_data(preset: Any) -> dict:
    """Serialise an ``AvatarPreset`` row to the public envelope."""
    config = getattr(preset, "config", None) or {}
    return {
        "id": preset.id,
        "provider": preset.provider,
        "provider_avatar_id": preset.provider_avatar_id,
        "display_name": preset.display_name,
        "voice_name": preset.voice_name,
        "thumbnail_url": preset.thumbnail_url,
        "is_active": preset.is_active,
        "kind": str(config.get("kind", "") or ""),
        "source": "preset",
    }


def _verify_image_ownership(
    session: Any, user_id: str, image_key: str, request_id: str
) -> None:
    """Enforce that ``image_key`` is an upload owned by the caller (BOLA guard).

    Uploads are registered as caller-scoped :class:`Asset` rows (``r2_key`` +
    ``user_id``); an ``image_key`` that does not match one the caller owns is a
    ``403`` so a creator can never turn another creator's uploaded photo (a
    guessed/observed R2 key) into their own avatar — and that foreign object is
    never downloaded or sent to HeyGen.

    Fails **closed** with a ``503`` when the :class:`Asset` model is unavailable
    (the ownership check cannot run), mirroring ``brand._verify_logo_ownership``.
    """
    try:
        from app.models.db.models import Asset
    except Exception as exc:  # noqa: BLE001 - DB layer optional at compile time
        logger.error(
            f"asset registry unavailable, cannot verify image ownership, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: upload ownership cannot be verified",
        )

    owned = (
        session.query(Asset)
        .filter(Asset.r2_key == image_key, Asset.user_id == user_id)
        .first()
    )
    if owned is None:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: image_key does not belong to the caller",
        )


def _require_heygen_provider(request_id: str) -> Any:
    """Resolve the enabled HeyGen provider or fail clean (402 ``format_locked``).

    Turning a photo into a talking-photo avatar requires a configured HeyGen
    account (an ``api_key``). When the provider registry is unavailable or the
    provider is not enabled we fail fast (503 / 402 ``format_locked``) rather than silently
    persisting a non-provider id — the created avatar must be usable in a job.
    """
    try:
        from app.services.avatar.base import get_avatar_provider

        provider = get_avatar_provider(_HEYGEN_PROVIDER)
    except Exception as exc:  # noqa: BLE001 - registry/import failure -> 503
        logger.error(
            f"avatar provider unavailable, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: avatar provider is not available",
        )

    if not provider.is_enabled():
        from app.core.launch.formats import raise_format_locked

        raise_format_locked(
            request_id, "avatar_reel", "HeyGen avatar provider is not configured"
        )
    return provider


def _download_image_to_temp(image_key: str, request_id: str) -> str:
    """Stream the caller's owned R2 image to a local temp file; return its path.

    Uses a short-lived presigned GET URL (no dependency on public-bucket access)
    streamed to disk. ``import requests`` is guarded so a missing HTTP dependency
    degrades to a clean ``503`` instead of an import crash. The caller is
    responsible for removing the returned temp file.
    """
    import os
    import tempfile

    try:
        import requests
    except Exception as exc:  # noqa: BLE001 - guard optional HTTP dependency
        logger.error(
            f"requests unavailable for image download, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: image download dependency is unavailable",
        )

    from app.services.storage.r2 import get_r2_client

    try:
        url = get_r2_client().presign_get(image_key)
    except Exception as exc:  # noqa: BLE001 - presign/config failure -> 502
        logger.error(
            f"failed to presign image {image_key!r}, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to prepare uploaded image for processing",
        )

    ext = os.path.splitext(image_key)[1].lower() or ".jpg"
    fd, local_path = tempfile.mkstemp(prefix="heygen_photo_", suffix=ext)
    try:
        with os.fdopen(fd, "wb") as fh:
            with requests.get(
                url, stream=True, timeout=_IMAGE_DOWNLOAD_TIMEOUT_S
            ) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
    except Exception as exc:  # noqa: BLE001 - network/disk failure -> 502
        try:
            os.remove(local_path)
        except OSError:
            pass
        logger.error(
            f"failed to download image {image_key!r}, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to download uploaded image",
        )
    return local_path


def _create_talking_photo(provider: Any, image_path: str, request_id: str) -> str:
    """Create a HeyGen talking-photo from ``image_path`` and return its id.

    Delegates to the provider's ``create_talking_photo`` (upload asset -> create
    talking-photo). The provider returns ``None`` on any external failure (its
    Protocol contract never raises), which we surface as a ``502`` so the caller
    is not left with a broken, unusable preset.
    """
    try:
        talking_photo_id = provider.create_talking_photo(image_path)
    except Exception as exc:  # noqa: BLE001 - defensive: provider should not raise
        logger.error(
            f"heygen create_talking_photo raised, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to create talking-photo avatar",
        )

    talking_photo_id = str(talking_photo_id or "").strip()
    if not talking_photo_id:
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: avatar provider returned no talking_photo_id",
        )
    return talking_photo_id


def _safe_thumbnail_url(image_key: str, request_id: str) -> str:
    """Best-effort permanent public URL for the source image (never fatal)."""
    try:
        from app.services.storage.r2 import get_r2_client

        return get_r2_client().public_url(image_key)
    except Exception as exc:  # noqa: BLE001 - thumbnail is best-effort
        logger.warning(
            f"failed to derive avatar thumbnail, request_id: {request_id}: {exc}"
        )
        return ""


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post(
    "/jobs/{job_id}/publish",
    response_model=PublishResponse,
    summary="Publish a completed job's output",
)
def publish_job(
    request: Request,
    body: PublishRequest,
    job_id: str = Path(..., description="Job ID"),
):
    """Re-publish a completed job's rendered output to social platforms (§ Phase 3).

    Order: auth -> ownership (404 on unknown/foreign job) -> completeness check
    (409 when the job is not done) -> :func:`publish.publish_job_output`.
    """
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    _require_db(request_id)

    platforms = [str(p).strip() for p in (getattr(body, "platforms", None) or []) if str(p).strip()]
    if not platforms:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: at least one platform is required",
        )
    youtube_privacy_status = getattr(body, "youtube_privacy_status", None)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        require_pro_action(str(user.id), request_id, action="studio publish")
        # Per-user + per-job publish rate limit BEFORE any provider work so a
        # burst of repeat publishes is capped (each publish hits the creator's
        # connected platform accounts and their API quotas).
        # Fail-open if Redis is down (see ratelimit.enforce_rate_limit).
        enforce_rate_limit(
            request,
            f"publish:{user.id}:{job_id}",
            limit=_publish_rate_limit(),
            window_s=_publish_rate_window_s(),
        )
        job = session.get(Job, job_id)
        if job is None or job.user_id != user.id:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        if job.state != TASK_STATE_COMPLETE:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: job is not complete; cannot publish",
            )
        user_id = user.id
        # Idempotency guard: once a job's output has been published,
        # re-publishing would create duplicate social posts and duplicate
        # operator billing. ``publish_job_output`` appends a completed
        # ``publish`` JobEvent; reject as a conflict when one already exists.
        from app.models.db.models import JobEvent

        already_published = (
            session.query(JobEvent)
            .filter(
                JobEvent.job_id == job_id,
                JobEvent.stage == _PUBLISH_STAGE,
                JobEvent.status == REELFORGE_STAGE_COMPLETE,
            )
            .first()
        )
        if already_published is not None:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: job output has already been published",
            )

    # Publish through the caller's OWN connected accounts (native OAuth
    # connectors + the pre-publish content gate) — never the operator's shared
    # Upload-Post account.
    try:
        from app.domains.publishing.native_service import (
            NativePublishError,
            PublishResult,
            publish_scheduled_reel_native,
            track_processing_publish,
        )
    except Exception as exc:  # noqa: BLE001 - publishing layer optional at compile time
        logger.error(f"native publish service unavailable, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: publish service is not available",
        )

    try:
        results = publish_scheduled_reel_native(
            str(user_id),
            job_id,
            platforms,
            youtube_privacy_status=youtube_privacy_status or "private",
        )
    except NativePublishError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc}",
        ) from exc
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - external publish failure -> 502
        logger.error(f"native publish failed for job {job_id}, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to publish job output",
        )

    for entry in results.get("results") or []:
        if isinstance(entry, dict) and entry.get("status") == "processing":
            track_processing_publish(
                str(user_id),
                job_id,
                PublishResult(
                    platform=str(entry.get("platform") or ""),
                    status="processing",
                    external_id=str(entry.get("external_id") or ""),
                    url=str(entry.get("url") or ""),
                ),
            )
    results = {**results, "request_id": request_id}

    return utils.get_response(200, results)


@router.post(
    "/avatars",
    response_model=CreateAvatarResponse,
    summary="Create a photo→avatar preset",
)
def create_avatar(request: Request, body: CreateAvatarRequest):
    """Create a USER photo→avatar preset by minting a HeyGen talking-photo.

    Turns the caller's uploaded selfie (``image_key``) into a HeyGen
    *talking-photo* avatar that later lip-syncs a reel's narration:

    1. **Auth + ownership (BOLA).** ``image_key`` MUST be an :class:`Asset` owned
       by the caller (``403`` otherwise) — verified BEFORE any external work so a
       foreign creator's image is never downloaded or sent to HeyGen.
    2. **Provider gate.** HeyGen must be configured/enabled (``503`` otherwise).
    3. **Create.** The owned image is streamed out of R2 and handed to the
       provider's ``create_talking_photo`` to obtain a ``talking_photo_id``.
    4. **Persist.** An owner-scoped :class:`AvatarPreset` is stored with
       ``provider='heygen'``, ``provider_avatar_id=<talking_photo_id>``,
       ``config={'kind':'talking_photo','source_image_key':<image_key>}`` and
       ``is_active=true`` so it appears in ``GET /api/v1/avatars`` for use in jobs.

    Returns ``{id, provider_avatar_id, display_name, ...}``.
    """
    import os

    request_id = base.get_task_id(request)
    _require_db(request_id)

    image_key = str(getattr(body, "image_key", "") or "").strip()
    if not image_key:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: image_key is required",
        )
    display_name = str(getattr(body, "display_name", "") or "").strip()
    voice_name = str(getattr(body, "voice_name", "") or "").strip()

    # 1) Auth + ownership BEFORE any external work: a caller may only turn their
    #    OWN uploaded image into an avatar. A foreign/guessed key is a 403 and is
    #    never presigned, downloaded, or forwarded to HeyGen.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _verify_image_ownership(session, user.id, image_key, request_id)
        user_id = str(user.id)

    # 2) HeyGen must be configured to mint a talking_photo_id.
    provider = _require_heygen_provider(request_id)

    # 3) Download the owned image and create the talking-photo avatar. The temp
    #    file is always cleaned up (success or failure).
    image_path = _download_image_to_temp(image_key, request_id)
    try:
        talking_photo_id = _create_talking_photo(provider, image_path, request_id)
    finally:
        try:
            os.remove(image_path)
        except OSError:
            pass

    thumbnail_url = _safe_thumbnail_url(image_key, request_id)

    # 4) Persist the owner-scoped preset.
    try:
        with get_session() as session:
            preset = AvatarPreset(
                user_id=user_id,
                provider=_HEYGEN_PROVIDER,
                provider_avatar_id=talking_photo_id,
                display_name=display_name,
                voice_name=voice_name,
                thumbnail_url=thumbnail_url,
                config={
                    "kind": _TALKING_PHOTO_KIND,
                    "source_image_key": image_key,
                },
                is_active=True,
            )
            session.add(preset)
            session.flush()
            data = _preset_public_data(preset)
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"create_avatar failed, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to create avatar preset",
        )

    return utils.get_response(200, data)
