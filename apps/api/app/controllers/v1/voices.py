"""ReelForge Brand Voice v1 API controller (Phase 11 — voice cloning).

Adds three creator-scoped endpoints under ``/api/v1`` that turn an uploaded
voice sample into a private, reusable "brand voice" via ElevenLabs Instant Voice
Clone (:mod:`app.services.tts.voice_clone`):

* ``POST /voices/clone`` — clone a voice from a previously uploaded sample.
  CONSENT is mandatory: the request MUST attest ``consent is True`` (else 400)
  that the caller owns/authorizes the sampled voice. Persists a ``UserVoice``
  row and returns the narrator selector ``"elevenlabs:<provider_voice_id>"``.
* ``POST /voices/verification-phrase`` — a fresh phrase (and signed token) the
  caller reads aloud; the recording is sent with the clone request (M7.2).
* ``GET /voices/mine`` — list the caller's cloned voices (ownership-scoped).
* ``DELETE /voices/mine/{voice_id}`` — delete a cloned voice the caller owns
  (404 for a missing/foreign id); also removes it from ElevenLabs.

The uploaded sample arrives via the EXISTING ``POST /api/v1/uploads/presign``
flow (audio content-type); the returned R2 ``key`` is passed here as
``sample_key``. The cloned ``voice_id`` is then selectable as a reel narrator —
the ``"elevenlabs:<id>"`` format is already handled by
``app/services/voice.py::tts()`` (verified: its ElevenLabs branch splits on the
``"elevenlabs:"`` prefix and uses the trailing provider voice id).

Verification (M7.2, :mod:`app.domains.compliance.voice_verification`)
-------------------------------------------------------------------------
* The voice name and description may not name a public figure or a character
  (400 ``voice_label_denied``), checked before any storage or provider call.
* With ``REELFORGE_VOICE_CLONE_VERIFICATION=required`` (default) the request
  also carries ``verification_token`` (from ``/voices/verification-phrase``)
  and ``verification_key`` (the caller's uploaded recording of the phrase). The
  recording must say the phrase and be the same speaker as the sample, or the
  clone is refused (400 with a machine-readable ``code``) and nothing is sent
  to the provider or charged.

Design notes
------------
* Reuses the guarded persistence import + auth helpers from ``jobs.py`` (a
  missing DB layer degrades to a clean 503 rather than an import crash), and the
  MPT response envelope (``utils.get_response``) + typed ``HttpException``.
* ``requests`` and the ``voice_clone`` service are imported defensively so this
  module stays ``py_compile`` / import safe in stripped-down environments.
* Ownership of ``sample_key`` is enforced via the same BOLA guard used by
  ``POST /avatars``: the key must map to an ``Asset`` row owned by the caller,
  so a guessed/observed foreign R2 key cannot seed another user's clone.
* No secrets are hardcoded — the ElevenLabs key is read inside ``voice_clone``
  from ``config.elevenlabs.api_key`` (header ``xi-api-key``).
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from typing import Optional

from fastapi import Path, Request
from loguru import logger
from pydantic import Field

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the guarded persistence import + auth helpers from jobs.py (which owns
# the canonical guard block) so this module stays DRY and import-safe. When the
# DB layer is absent these are ``None`` and ``_require_db`` raises a 503.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.domains.compliance import voice_verification
from app.models.exception import HttpException
from app.models.schema import (
    CloneVoiceRequest,
    MyVoicesResponse,
    VoiceCloneResponse,
)
from app.utils import utils

# ``requests`` is a first-party dependency, but guard the import so this module
# still imports / ``py_compile``s in environments where it is unavailable (the
# sample download degrades to a clean 503 at request time).
try:  # pragma: no cover - requests is normally installed
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# Guarded DB-layer + service imports (authored by sibling agents; may be absent
# at compile time). The exception classes are imported unconditionally-safe with
# local fallbacks so the ``except`` clauses below never reference a missing name.
try:
    from app.models.db.models import Asset
    from app.models.db.repositories import UserVoiceRepository

    _VOICES_DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    Asset = None  # type: ignore[assignment,misc]
    UserVoiceRepository = None  # type: ignore[assignment,misc]
    _VOICES_DB_IMPORT_ERROR = exc

try:
    from app.services.tts import voice_clone
    from app.services.tts.voice_clone import (
        VoiceCloneAuthError,
        VoiceCloneError,
        VoiceCloneQuotaError,
        VoiceCloneValidationError,
    )
except Exception as exc:  # pragma: no cover - service optional at compile time
    voice_clone = None  # type: ignore[assignment]
    _VOICE_CLONE_IMPORT_ERROR: Exception | None = exc

    class VoiceCloneError(RuntimeError):  # type: ignore[no-redef]
        """Fallback base error when the voice_clone service is unavailable."""

    class VoiceCloneAuthError(VoiceCloneError):  # type: ignore[no-redef]
        pass

    class VoiceCloneQuotaError(VoiceCloneError):  # type: ignore[no-redef]
        pass

    class VoiceCloneValidationError(VoiceCloneError):  # type: ignore[no-redef]
        pass
else:  # pragma: no cover - trivial
    _VOICE_CLONE_IMPORT_ERROR = None


router = new_router()

# Narrator-selector prefix. A cloned voice is addressed as
# ``"elevenlabs:<provider_voice_id>"`` — the format ``voice.py::tts()`` handles.
_ELEVENLABS_PREFIX: str = "elevenlabs:"
_DEFAULT_PROVIDER: str = "elevenlabs"
_READY_STATUS: str = "ready"

# (connect, read) timeout for streaming the sample out of R2.
_DOWNLOAD_TIMEOUT_S: tuple[int, int] = (15, 120)
# Default suffix when the sample_key carries no usable extension.
_DEFAULT_SAMPLE_SUFFIX: str = ".mp3"


class VerifiedCloneVoiceRequest(CloneVoiceRequest):
    """``CloneVoiceRequest`` plus the live-phrase verification fields (M7.2).

    Optional in the schema so a missing field gets a clear 400 with a ``code``
    (``voice_verification_required``) instead of a generic 422.
    """

    verification_token: Optional[str] = Field(
        default=None, max_length=256,
        description="Token from POST /voices/verification-phrase.",
    )
    verification_key: Optional[str] = Field(
        default=None, max_length=512,
        description="R2 key of the caller's uploaded recording of the phrase.",
    )


def _verification_http_error(
    exc: "voice_verification.VoiceVerificationError", request_id: str
) -> HttpException:
    return HttpException(
        task_id=request_id,
        status_code=exc.status_code,
        message=f"{request_id}: {exc.message}",
        data={"code": exc.code},
    )


def _remove_quietly(path: str | None) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError as exc:  # pragma: no cover - best-effort cleanup
        logger.warning(f"failed to remove temp voice file {path}: {exc}")


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_voice_clone(request_id: str) -> None:
    """Raise 503 when the voice_clone service could not be imported."""
    if voice_clone is None:
        logger.error(
            f"voice_clone service unavailable, request_id: {request_id}, "
            f"error: {_VOICE_CLONE_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: voice cloning service is not available",
        )


def _require_asset_model(request_id: str) -> None:
    """Raise 503 when the ``Asset`` model could not be imported.

    Guards the ``sample_key`` ownership (BOLA) check: if ``Asset`` is ``None``
    the check cannot run, so we MUST fail closed with a 503 rather than skip it
    and let a caller clone from an arbitrary/foreign R2 key.
    """
    if Asset is None:
        logger.error(
            f"Asset model unavailable, request_id: {request_id}, "
            f"error: {_VOICES_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _voice_public_data(voice: Any) -> dict:
    """Serialise a ``UserVoice`` row to the public envelope.

    ``voice_id`` is the narrator selector (``elevenlabs:<provider_voice_id>``),
    distinct from the internal row ``id``.
    """
    created_at = getattr(voice, "created_at", None)
    return {
        "id": voice.id,
        "voice_id": f"{_ELEVENLABS_PREFIX}{voice.provider_voice_id}",
        "name": voice.name,
        "status": voice.status,
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


def _download_sample(sample_key: str, request_id: str) -> str:
    """Presign + stream the caller's uploaded voice sample to a local temp file.

    Returns the temp path (caller is responsible for deleting it). Raises a typed
    ``HttpException`` (503 when ``requests``/R2 are unavailable, 502 on a storage
    failure) rather than leaking a raw exception.
    """
    if requests is None:  # pragma: no cover - requests is normally installed
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: HTTP client is not available for sample download",
        )

    try:
        from app.services.storage.r2 import get_r2_client

        url = get_r2_client().presign_get(sample_key)
    except Exception as exc:  # noqa: BLE001 - storage/config failure -> 502
        logger.error(
            f"failed to presign voice sample {sample_key!r}, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: object storage is unavailable",
        )

    ext = os.path.splitext(sample_key)[1] or _DEFAULT_SAMPLE_SUFFIX
    fd, local_path = tempfile.mkstemp(prefix="voice_sample_", suffix=ext)
    try:
        # ``os.fdopen`` takes ownership of ``fd`` immediately, so its ``with``
        # closes the descriptor on ANY failure below (incl. a ``requests.get``
        # network error) — otherwise the raw fd would leak on the error path.
        with os.fdopen(fd, "wb") as fh:
            with requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
    except Exception as exc:  # noqa: BLE001 - download failure -> 502; clean up temp
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
        logger.error(
            f"failed to download voice sample {sample_key!r}, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to download the voice sample",
        )
    logger.info(f"[{request_id}] downloaded voice sample to {local_path}")
    return local_path


def _map_clone_error(exc: Exception, request_id: str) -> HttpException:
    """Map a ``voice_clone`` failure onto a typed ``HttpException``."""
    if isinstance(exc, VoiceCloneValidationError):
        return HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid voice sample: {exc}",
        )
    if isinstance(exc, VoiceCloneQuotaError):
        return HttpException(
            task_id=request_id,
            status_code=429,
            message=f"{request_id}: voice cloning quota/rate limit reached",
        )
    if isinstance(exc, VoiceCloneAuthError):
        # Provider-side auth (our shared key) — not the caller's fault -> 503.
        logger.error(f"voice clone auth failure, request_id: {request_id}: {exc}")
        return HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: voice cloning is not configured",
        )
    logger.error(f"voice clone failed, request_id: {request_id}: {exc}")
    return HttpException(
        task_id=request_id,
        status_code=502,
        message=f"{request_id}: voice cloning failed",
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post(
    "/voices/clone",
    response_model=VoiceCloneResponse,
    summary="Clone a brand voice from an uploaded sample",
)
def clone_voice_endpoint(request: Request, body: VerifiedCloneVoiceRequest):
    """Create a private ElevenLabs Instant Voice Clone from an uploaded sample.

    Order: auth -> CONSENT gate (400 unless ``consent is True``) -> label
    denylist (400) -> verification fields present (400, when required) ->
    ownership (403 when ``sample_key`` or ``verification_key`` is not the
    caller's) -> premium voice credits held (402 otherwise; nothing debited) ->
    download -> live-phrase and same-speaker check (400) -> clone -> persist a
    ``UserVoice`` row -> return ``{id, voice_id, name, status, verification}``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_asset_model(request_id)
    _require_voice_clone(request_id)

    # CONSENT is mandatory and checked BEFORE any provider/storage work.
    if body.consent is not True:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: consent is required to clone a voice",
        )

    name = str(body.name or "").strip()
    sample_key = str(body.sample_key or "").strip()
    description = str(body.description or "").strip()
    if not name:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: a voice name is required",
        )
    if not sample_key:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: sample_key is required",
        )

    try:
        voice_verification.check_labels(name, description)
    except voice_verification.VoiceVerificationError as exc:
        raise _verification_http_error(exc, request_id)

    verification_required = voice_verification.mode() == voice_verification.MODE_REQUIRED
    verification_token = str(body.verification_token or "").strip()
    verification_key = str(body.verification_key or "").strip()
    if verification_required and not (verification_token and verification_key):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=(
                f"{request_id}: record yourself reading the verification phrase "
                "(POST /voices/verification-phrase) and send it with the sample"
            ),
            data={"code": "voice_verification_required"},
        )

    # Resolve caller + enforce that the sample belongs to them (BOLA guard),
    # mirroring POST /avatars. Capture only the id so the DB session is released
    # before the (slow) external clone call.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = user.id
        owned_asset = (
            session.query(Asset)
            .filter(Asset.r2_key == sample_key, Asset.user_id == user_id)
            .first()
        )
        if owned_asset is None:
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=f"{request_id}: sample_key does not belong to the caller",
            )
        if verification_required:
            owned_recording = (
                session.query(Asset)
                .filter(Asset.r2_key == verification_key, Asset.user_id == user_id)
                .first()
            )
            if owned_recording is None:
                raise HttpException(
                    task_id=request_id,
                    status_code=403,
                    message=f"{request_id}: verification_key does not belong to the caller",
                )
        # A clone is an ElevenLabs voice: only premium voice credit holders
        # (who pay per reel that uses it) may create one. Nothing is debited.
        from app.services.billing import premium_credits

        if premium_credits.balance(session, str(user_id), premium_credits.KIND_PREMIUM_VOICE) <= 0:
            raise HttpException(
                task_id=request_id,
                status_code=402,
                message=(
                    f"{request_id}: cloned voices are premium voices; add premium voice "
                    "credits to create one"
                ),
                data={"code": "premium_voice_credits_required", "needed": 1, "available": 0},
            )

    sample_path = _download_sample(sample_key, request_id)
    recording_path: str | None = None
    verification: dict | None = None
    try:
        if verification_required:
            recording_path = _download_sample(verification_key, request_id)
            try:
                verification = voice_verification.verify(
                    str(user_id), verification_token, sample_path, recording_path
                ).as_dict()
            except voice_verification.VoiceVerificationError as exc:
                logger.info(f"[{request_id}] voice clone verification refused: {exc.code}")
                raise _verification_http_error(exc, request_id)
            logger.info(f"[{request_id}] voice clone verified: {verification}")
        result = voice_clone.clone_voice(name, [sample_path], description=description)
    except HttpException:
        raise
    except VoiceCloneError as exc:
        raise _map_clone_error(exc, request_id)
    except Exception as exc:  # noqa: BLE001 - any other clone failure -> 502
        raise _map_clone_error(exc, request_id)
    finally:
        _remove_quietly(sample_path)
        _remove_quietly(recording_path)

    provider_voice_id = str((result or {}).get("voice_id") or "").strip()
    if not provider_voice_id:
        logger.error(
            f"voice clone returned no voice_id, request_id: {request_id}: {result!r}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: voice cloning returned no voice id",
        )

    try:
        with get_session() as session:
            voice = UserVoiceRepository(session).create(
                user_id=user_id,
                name=name,
                provider=_DEFAULT_PROVIDER,
                provider_voice_id=provider_voice_id,
                sample_key=sample_key,
                consent=True,
                status=_READY_STATUS,
            )
            data = {
                "id": voice.id,
                "voice_id": f"{_ELEVENLABS_PREFIX}{provider_voice_id}",
                "name": voice.name,
                "status": voice.status,
                "verification": verification,
            }
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to persist cloned voice, request_id: {request_id}: {exc}")
        # Compensating delete: the provider voice was created (step 1) but the DB
        # row failed to persist (step 2). Without a row it is unreachable via the
        # DELETE endpoint and would consume quota forever, so best-effort remove it.
        try:
            voice_clone.delete_voice(provider_voice_id)
        except Exception as cleanup_exc:  # noqa: BLE001 - best-effort compensation
            logger.warning(
                f"failed to delete orphaned provider voice {provider_voice_id} "
                f"after persist failure, request_id: {request_id}: {cleanup_exc}"
            )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to save the cloned voice",
        )

    return utils.get_response(200, data)


@router.post(
    "/voices/verification-phrase",
    summary="Get a phrase to read aloud before cloning a voice",
)
def voice_verification_phrase(request: Request):
    """A fresh phrase and signed token for the caller (M7.2).

    The caller records themselves reading ``phrase``, uploads the recording
    with ``POST /uploads/presign`` and sends its key as ``verification_key``
    with ``token`` as ``verification_token`` to ``POST /voices/clone`` before
    ``expires_at``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = str(user.id)
    try:
        challenge = voice_verification.issue_phrase(user_id)
    except voice_verification.VoiceVerificationError as exc:
        raise _verification_http_error(exc, request_id)
    return utils.get_response(
        200,
        {
            "token": challenge.token,
            "phrase": challenge.phrase,
            "expires_at": challenge.expires_at,
            "required": voice_verification.mode() == voice_verification.MODE_REQUIRED,
        },
    )


@router.get(
    "/voices/mine",
    response_model=MyVoicesResponse,
    summary="List the caller's cloned voices",
)
def list_my_voices(request: Request):
    """Return the caller's cloned voices, newest first (ownership-scoped)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = UserVoiceRepository(session).list_for_user(user.id)
        data = [_voice_public_data(v) for v in rows]

    return utils.get_response(200, data)


@router.delete(
    "/voices/mine/{voice_id}",
    summary="Delete one of the caller's cloned voices",
)
def delete_my_voice(request: Request, voice_id: str = Path(..., description="Voice row ID")):
    """Delete a cloned voice the caller owns (404 for missing/foreign id).

    Order: auth -> ownership (404 when the id is unknown or belongs to another
    user) -> best-effort provider delete (:func:`voice_clone.delete_voice`) ->
    remove the ``UserVoice`` row. The provider delete is best-effort so a
    provider-side error never strands the local row.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)

    # Ownership check first: a missing/foreign id must 404 without side effects.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = user.id
        voice = UserVoiceRepository(session).get_owned(voice_id, user_id)
        if voice is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: voice not found",
            )
        provider_voice_id = str(voice.provider_voice_id or "").strip()

    # Best-effort provider delete (idempotent; 404 upstream is treated as done).
    if provider_voice_id and voice_clone is not None:
        try:
            voice_clone.delete_voice(provider_voice_id)
        except Exception as exc:  # noqa: BLE001 - never strand the local row
            logger.warning(
                f"failed to delete provider voice {provider_voice_id}, "
                f"request_id: {request_id}: {exc}"
            )

    try:
        with get_session() as session:
            deleted = UserVoiceRepository(session).delete(voice_id, user_id)
    except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
        logger.error(f"failed to delete voice row, request_id: {request_id}: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to delete the voice",
        )

    if not deleted:  # Lost a race with a concurrent delete — surface as 404.
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: voice not found",
        )

    return utils.get_response(200, {"id": voice_id, "deleted": True})
