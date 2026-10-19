"""ElevenLabs Instant Voice Clone client for the ReelForge Brand Voice feature.

A creator uploads a short voice sample (30-60s). This module sends that sample
to ElevenLabs' Instant Voice Clone endpoint (``POST /v1/voices/add``) and returns
the provider voice id. The resulting voice becomes selectable as the reel narrator
via ``voice_name = "elevenlabs:<provider_voice_id>"`` — a format the existing
``app.services.voice.tts()`` ElevenLabs branch already understands.

Design notes:
  * The ElevenLabs account/API key is shared with the existing TTS + Music
    integrations (``config.elevenlabs.api_key``, header ``xi-api-key``), so
    creators never maintain a second key.
  * ``requests`` and ``app.config`` are imported defensively so the module stays
    ``py_compile`` / import safe in stripped-down environments (mirroring
    ``app.services.elevenlabs_music``).
  * All failures raise a typed :class:`VoiceCloneError` (or subclass) with a
    bounded, redacted error body — API keys and account details never reach logs.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Optional

from loguru import logger

# ``requests`` is a first-party dependency, but guard the import so this module
# still imports / ``py_compile``s in environments where it is unavailable.
try:  # pragma: no cover - exercised indirectly via monkeypatching in tests
    import requests  # type: ignore
except Exception:  # pragma: no cover - requests is normally installed
    requests = None  # type: ignore

try:
    from app.config import config  # type: ignore
except Exception:  # pragma: no cover - keep import-safe without full app config
    config = None  # type: ignore


DEFAULT_BASE_URL = "https://api.elevenlabs.io"
ADD_VOICE_PATH = "/v1/voices/add"
VOICE_PATH = "/v1/voices/{voice_id}"

# Retries only help for transient failures (network blips, 5xx). Auth (401/403),
# validation (422) and quota (429) failures are deterministic and never retried.
MAX_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
AUTH_STATUS_CODES = frozenset({401, 403})
VALIDATION_STATUS_CODES = frozenset({400, 422})
QUOTA_STATUS_CODES = frozenset({429})

# Only a handful of common audio types are accepted; anything else is rejected
# before we spend a network round-trip on it.
ALLOWED_SAMPLE_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".aac"}
)
MAX_SAMPLES = 25
MAX_SAMPLE_BYTES = 50 * 1024 * 1024  # ElevenLabs per-file upload ceiling.
MAX_ERROR_BODY_BYTES = 500
DEFAULT_TIMEOUT = (15, 120)


class VoiceCloneError(RuntimeError):
    """Base error for any ElevenLabs Instant Voice Clone failure."""


class VoiceCloneAuthError(VoiceCloneError):
    """The ElevenLabs API key is missing, invalid, or lacks voice-add access."""


class VoiceCloneValidationError(VoiceCloneError):
    """The request or uploaded sample was rejected by ElevenLabs (400/422)."""


class VoiceCloneQuotaError(VoiceCloneError):
    """The account hit its voice/clone quota or was rate limited (429)."""


def _get_api_key() -> str:
    """Read the shared ElevenLabs API key, defensively and without hardcoding.

    Falls back to the ``ELEVENLABS_API_KEY`` environment variable when the app
    config is unavailable or unset, matching ``elevenlabs_music.get_api_key``.
    """
    configured_key = ""
    if config is not None:
        try:
            configured_key = str(config.elevenlabs.get("api_key", "") or "").strip()
        except Exception:  # pragma: no cover - defensive against config shape drift
            configured_key = ""
    return configured_key or os.getenv("ELEVENLABS_API_KEY", "").strip()


def _base_url() -> str:
    """Return the ElevenLabs base URL, defaulting when config is absent/invalid."""
    base = DEFAULT_BASE_URL
    if config is not None:
        try:
            base = str(
                config.elevenlabs.get("base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
            )
        except Exception:  # pragma: no cover - defensive against config shape drift
            base = DEFAULT_BASE_URL
    return base.rstrip("/")


def _request_timeout() -> tuple[int, int]:
    """Clamp the (connect, read) timeout, tolerating misconfiguration."""
    raw = 120
    if config is not None:
        try:
            raw = config.elevenlabs.get("clone_timeout", 120)
        except Exception:  # pragma: no cover - defensive against config shape drift
            raw = 120
    try:
        read_timeout = float(raw)
    except (TypeError, ValueError):
        read_timeout = 120
    if not math.isfinite(read_timeout) or read_timeout <= 0:
        read_timeout = 120
    return 15, max(1, math.ceil(min(read_timeout, 600)))


def _require_requests() -> None:
    if requests is None:  # pragma: no cover - requests is normally installed
        raise VoiceCloneError(
            "the 'requests' package is required for voice cloning but is not installed"
        )


def _safe_response_error(response: "requests.Response") -> str:
    """Read a bounded slice of the third-party error body, redacting newlines.

    Keeps failure logs small and avoids leaking large / multi-line provider
    payloads into task logs.
    """
    try:
        body = response.text or ""
    except Exception:  # pragma: no cover - body access should not raise
        body = ""
    body = body.strip().replace("\n", " ")[:MAX_ERROR_BODY_BYTES]
    reason = getattr(response, "reason", "") or ""
    return body or reason or "request failed"


def _raise_for_status(response: "requests.Response", *, context: str) -> None:
    """Map a non-2xx ElevenLabs response onto a typed error.

    Returns cleanly for success (2xx) and for retryable statuses (the caller
    decides whether to retry); raises a non-retryable typed error otherwise.
    """
    status = response.status_code
    if 200 <= status < 300:
        return
    if status in RETRYABLE_STATUS_CODES:
        # Retryable — let the caller loop; surfaced as VoiceCloneError if exhausted.
        return
    detail = _safe_response_error(response)
    if status in AUTH_STATUS_CODES:
        raise VoiceCloneAuthError(
            f"ElevenLabs rejected the API key while {context} ({status}): {detail}"
        )
    if status in QUOTA_STATUS_CODES:
        raise VoiceCloneQuotaError(
            f"ElevenLabs quota/rate limit hit while {context} ({status}): {detail}"
        )
    if status in VALIDATION_STATUS_CODES:
        raise VoiceCloneValidationError(
            f"ElevenLabs rejected the request while {context} ({status}): {detail}"
        )
    raise VoiceCloneError(
        f"ElevenLabs request failed while {context} ({status}): {detail}"
    )


def _validate_sample_paths(sample_paths: list[str]) -> list[str]:
    """Validate the local voice sample files before uploading.

    Ensures the caller passed at least one existing, non-empty, reasonably sized
    audio file with a recognised extension. Returns the validated real paths.
    """
    if not sample_paths:
        raise VoiceCloneValidationError("at least one voice sample is required")
    if len(sample_paths) > MAX_SAMPLES:
        raise VoiceCloneValidationError(
            f"too many voice samples: {len(sample_paths)} (max {MAX_SAMPLES})"
        )

    validated: list[str] = []
    for raw_path in sample_paths:
        if not raw_path or not isinstance(raw_path, str):
            raise VoiceCloneValidationError("voice sample path is empty")
        real_path = os.path.realpath(raw_path)
        if not os.path.isfile(real_path):
            raise VoiceCloneValidationError(
                f"voice sample does not exist: {os.path.basename(raw_path)}"
            )
        extension = os.path.splitext(real_path)[1].lower()
        if extension not in ALLOWED_SAMPLE_EXTENSIONS:
            raise VoiceCloneValidationError(
                f"unsupported voice sample type: {extension or 'unknown'}"
            )
        size = os.path.getsize(real_path)
        if size <= 0:
            raise VoiceCloneValidationError(
                f"voice sample is empty: {os.path.basename(raw_path)}"
            )
        if size > MAX_SAMPLE_BYTES:
            raise VoiceCloneValidationError(
                f"voice sample is too large: {os.path.basename(raw_path)} "
                f"({size} bytes, max {MAX_SAMPLE_BYTES})"
            )
        validated.append(real_path)
    return validated


def is_enabled() -> bool:
    """Return whether voice cloning is configured (an API key is present)."""
    return bool(_get_api_key())


def clone_voice(
    name: str,
    sample_paths: list[str],
    description: str = "",
    labels: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Create an ElevenLabs Instant Voice Clone from local sample files.

    Args:
        name: Human-readable name for the cloned voice.
        sample_paths: Local paths to the uploaded audio sample(s).
        description: Optional description stored alongside the voice.
        labels: Optional key/value metadata sent to ElevenLabs.

    Returns:
        ``{"voice_id": <provider id>, "name": <name>}``. Callers store the id as
        ``elevenlabs:<voice_id>`` for narration.

    Raises:
        VoiceCloneValidationError: on invalid inputs or a 400/422 response.
        VoiceCloneAuthError: on a missing/rejected API key (401/403).
        VoiceCloneQuotaError: on quota / rate-limit (429).
        VoiceCloneError: on other / exhausted-transient failures.
    """
    _require_requests()

    clean_name = (name or "").strip()
    if not clean_name:
        raise VoiceCloneValidationError("a voice name is required")

    api_key = _get_api_key()
    if not api_key:
        raise VoiceCloneAuthError("ElevenLabs API key is not configured")

    validated_paths = _validate_sample_paths(sample_paths)

    url = f"{_base_url()}{ADD_VOICE_PATH}"
    headers = {"xi-api-key": api_key}
    data: dict[str, str] = {"name": clean_name}
    if description and description.strip():
        data["description"] = description.strip()
    if labels:
        # ElevenLabs expects labels as a JSON-encoded string in the form body.
        data["labels"] = json.dumps(labels)

    timeout = _request_timeout()
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        opened_files: list[Any] = []
        try:
            # ``files`` is a list of tuples so multiple samples share the "files"
            # field, which is what the ElevenLabs multipart API expects.
            files: list[tuple[str, tuple[str, Any]]] = []
            for path in validated_paths:
                handle = open(path, "rb")
                opened_files.append(handle)
                files.append(("files", (os.path.basename(path), handle)))

            logger.info(
                f"cloning voice '{clean_name}' with {len(files)} sample(s), "
                f"attempt {attempt}/{MAX_ATTEMPTS}"
            )
            response = requests.post(
                url,
                headers=headers,
                data=data,
                files=files,
                timeout=timeout,
            )
        except requests.RequestException as exc:  # transient network failure
            last_error = exc
            logger.warning(
                f"voice clone request failed (attempt {attempt}/{MAX_ATTEMPTS}): {exc}"
            )
            continue
        finally:
            for handle in opened_files:
                try:
                    handle.close()
                except Exception:  # pragma: no cover - best-effort cleanup
                    pass

        # Non-retryable statuses raise here; retryable ones fall through to retry.
        _raise_for_status(response, context="cloning voice")
        if response.status_code in RETRYABLE_STATUS_CODES:
            last_error = VoiceCloneError(
                f"ElevenLabs voice clone failed "
                f"({response.status_code}): {_safe_response_error(response)}"
            )
            logger.warning(
                f"voice clone transient failure "
                f"(attempt {attempt}/{MAX_ATTEMPTS}): {last_error}"
            )
            continue

        try:
            payload = response.json()
        except ValueError as exc:
            raise VoiceCloneError(
                "ElevenLabs returned an invalid voice-clone response"
            ) from exc

        if not isinstance(payload, dict):
            raise VoiceCloneError(
                "ElevenLabs returned an unexpected voice-clone response"
            )
        voice_id = str(payload.get("voice_id") or "").strip()
        if not voice_id:
            raise VoiceCloneError(
                "ElevenLabs voice-clone response did not include a voice_id"
            )

        logger.success(f"cloned voice '{clean_name}' -> voice_id={voice_id}")
        return {"voice_id": voice_id, "name": clean_name}

    raise VoiceCloneError(
        f"voice clone failed after {MAX_ATTEMPTS} attempts: {last_error}"
    )


def delete_voice(provider_voice_id: str) -> bool:
    """Delete a previously cloned voice from ElevenLabs.

    Returns True on success. A 404 is treated as already-deleted (idempotent) and
    also returns True. Raises a typed error for auth/other failures.
    """
    _require_requests()

    voice_id = (provider_voice_id or "").strip()
    if not voice_id:
        raise VoiceCloneValidationError("a provider voice id is required")

    api_key = _get_api_key()
    if not api_key:
        raise VoiceCloneAuthError("ElevenLabs API key is not configured")

    url = f"{_base_url()}{VOICE_PATH.format(voice_id=voice_id)}"
    headers = {"xi-api-key": api_key}
    try:
        response = requests.delete(url, headers=headers, timeout=_request_timeout())
    except requests.RequestException as exc:
        raise VoiceCloneError(f"failed to reach ElevenLabs to delete voice: {exc}") from exc

    if response.status_code == 404:
        logger.info(f"voice {voice_id} already absent on ElevenLabs; treating as deleted")
        return True

    _raise_for_status(response, context="deleting voice")
    if response.status_code in RETRYABLE_STATUS_CODES:
        raise VoiceCloneError(
            f"ElevenLabs voice delete failed "
            f"({response.status_code}): {_safe_response_error(response)}"
        )

    logger.success(f"deleted cloned voice {voice_id}")
    return True


def get_shared_or_user_voice(provider_voice_id: str) -> dict[str, Any]:
    """Fetch a voice's details (user-owned or shared) from ElevenLabs.

    Returns the raw voice payload as a dict. Raises a typed error on failure.
    """
    _require_requests()

    voice_id = (provider_voice_id or "").strip()
    if not voice_id:
        raise VoiceCloneValidationError("a provider voice id is required")

    api_key = _get_api_key()
    if not api_key:
        raise VoiceCloneAuthError("ElevenLabs API key is not configured")

    url = f"{_base_url()}{VOICE_PATH.format(voice_id=voice_id)}"
    headers = {"xi-api-key": api_key}
    try:
        response = requests.get(url, headers=headers, timeout=_request_timeout())
    except requests.RequestException as exc:
        raise VoiceCloneError(f"failed to reach ElevenLabs to fetch voice: {exc}") from exc

    _raise_for_status(response, context="fetching voice")
    if response.status_code in RETRYABLE_STATUS_CODES:
        raise VoiceCloneError(
            f"ElevenLabs voice fetch failed "
            f"({response.status_code}): {_safe_response_error(response)}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise VoiceCloneError("ElevenLabs returned an invalid voice response") from exc
    if not isinstance(payload, dict):
        raise VoiceCloneError("ElevenLabs returned an unexpected voice response")
    return payload
