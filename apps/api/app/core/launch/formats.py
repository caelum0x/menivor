"""Reel format availability + request-time ``format_locked`` gating.

One source of truth for "which reel formats can this deployment produce right
now?", shared by ``GET /api/v1/launch/status`` (``available_formats`` /
``locked_formats``) and the job-create boundary. A format whose provider key is
missing is rejected up front with ``402`` + ``code=format_locked`` instead of
failing mid-pipeline after a credit debit.

Free formats (no paid key): captions over your own video (BYOV), faceless reels
narrated by a free edge-tts voice, and typed scripts. Premium formats unlock as
their provider key is configured.

Names/booleans only — never a secret value.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Mapping

from app.models.exception import HttpException

FORMAT_LOCKED_CODE = "format_locked"
FORMAT_LOCKED_MESSAGE = "This format is not available yet"
FORMAT_LOCKED_STATUS = 402

# Free edge-tts (Microsoft neural) voices used when a premium voice is
# requested but ElevenLabs is not configured. Keyed by language prefix.
_FREE_VOICES: dict[str, str] = {
    "en": "en-US-AriaNeural-Female",
    "tr": "tr-TR-EmelNeural-Female",
    "es": "es-ES-ElviraNeural-Female",
    "de": "de-DE-KatjaNeural-Female",
    "fr": "fr-FR-DeniseNeural-Female",
    "pt": "pt-BR-FranciscaNeural-Female",
}
DEFAULT_FREE_VOICE = _FREE_VOICES["en"]

# id -> (label, capability it needs or "" for free, env NAMES that unlock it)
_FORMATS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("captions_only_byov", "Captions over your own video", "", ()),
    ("faceless_free_voice", "Faceless narrated reel with a free voice", "free_tts", ()),
    ("typed_script", "Your own typed script", "", ()),
    ("generated_script", "AI-written script", "script_llm",
     ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "REELFORGE_LLM_MODEL")),
    ("premium_voice", "Premium and cloned voices", "premium_voice",
     ("ELEVENLABS_API_KEY",)),
    ("avatar_reel", "AI avatar reel", "avatar",
     ("HEYGEN_API_KEY",)),
    ("ai_broll", "AI video clips", "ai_broll",
     ("BROLL_GEN_PROVIDER", "COMFYUI_API_KEY")),
    # Dub any uploaded video: free edge-tts voices + local whisper need only the
    # pyvideotrans container image; ElevenLabs voices also need their key.
    ("dub_video_free_voice", "Dub your video with a free voice", "dub_engine",
     ("PYVIDEOTRANS_IMAGE",)),
    ("dub_video_premium_voice", "Dub your video with premium voices", "dub_premium",
     ("PYVIDEOTRANS_IMAGE", "ELEVENLABS_API_KEY")),
)

# Customer-facing (they reach /launch/status and 402 errors): no vendor, env
# or internal names. Operators get the env NAMES from ``unlock_env`` (staff
# view of /launch/status) and the preflight checklist.
_LOCK_REASONS: dict[str, str] = {
    "free_tts": "the free voice engine is not available on this server",
    "script_llm": "AI script writing is not switched on",
    "premium_voice": "premium voices are not switched on",
    "avatar": "AI avatars are not switched on",
    "ai_broll": "AI video clips are not switched on",
    "dub_engine": "video dubbing is not switched on",
    "dub_premium": "dubbing with premium voices is not switched on",
}


def free_voice_for(language: str = "") -> str:
    """A free edge-tts voice for ``language`` (falls back to US English)."""
    prefix = str(language or "").strip().lower()[:2]
    return _FREE_VOICES.get(prefix, DEFAULT_FREE_VOICE)


def _present(env: Mapping[str, str], *names: str) -> bool:
    return any(str(env.get(name, "") or "").strip() for name in names)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# Runtime (config-backed) provider checks — what the pipeline will actually use.
# --------------------------------------------------------------------------- #
def elevenlabs_configured() -> bool:
    from app.config import config

    return bool(str(config.elevenlabs.get("api_key", "") or "").strip())


def avatar_provider_enabled(provider_id: str = "heygen") -> bool:
    """True when the requested talking-head provider can render."""
    provider_id = str(provider_id or "heygen").strip() or "heygen"
    if provider_id == "heygen":
        from app.config import config

        return bool(str(config.heygen.get("api_key", "") or "").strip())
    try:
        from app.services.avatar import get_avatar_provider

        return bool(get_avatar_provider(provider_id).is_enabled())
    except Exception:  # noqa: BLE001 - unresolvable provider => locked
        return False


def broll_configured() -> bool:
    provider_id = (os.getenv("BROLL_GEN_PROVIDER") or "").strip().lower() or "comfyui"
    if provider_id == "none":
        return False
    try:
        from app.domains.broll import get_broll_provider

        return bool(get_broll_provider().is_enabled())
    except Exception:  # noqa: BLE001 - unresolvable provider => locked
        return False


def script_llm_configured() -> bool:
    """True when the script LLM the app is configured to call has its key."""
    try:
        from app.config import config
        from app.models.llm_provider import get_llm_provider
    except Exception:  # noqa: BLE001 - status must never fail
        return False
    provider_id = str(config.app.get("llm_provider", "") or "").strip().lower()
    if provider_id == "ollama":
        return True
    if provider_id == "litellm":
        model = str(config.app.get("litellm_model_name", "") or "").strip().lower()
        prefix = model.split("/", 1)[0] if "/" in model else ""
        if prefix == "anthropic":
            return bool(str(config.anthropic.get("api_key", "") or "").strip()) or _present(
                os.environ, "ANTHROPIC_API_KEY"
            )
        if prefix == "ollama":
            return True
        return bool(prefix) and _present(os.environ, f"{prefix.upper()}_API_KEY")
    spec = get_llm_provider(provider_id)
    if spec is None:
        return False
    if not spec.requires_api_key:
        return True
    return bool(str(config.app.get(spec.config_key("api_key"), "") or "").strip())


def _dub_engine_configured(env: Mapping[str, str] | None = None) -> bool:
    try:
        from app.domains.dub.catalog import sidecar_configured

        return sidecar_configured(env)
    except Exception:  # noqa: BLE001 - status must never fail
        return False


def _paid_avatar_enabled(provider_id: str) -> bool:
    """Configured AND licensed for paid output (MO1: LatentSync waits for MO12b)."""
    from app.domains.routing.license_class import is_model_sellable

    return is_model_sellable(provider_id) and avatar_provider_enabled(provider_id)


def _runtime_capabilities() -> dict[str, bool]:
    premium = elevenlabs_configured()
    dub = _dub_engine_configured()
    return {
        "free_tts": _has_module("edge_tts"),
        "script_llm": script_llm_configured(),
        "premium_voice": premium,
        "avatar": _paid_avatar_enabled("heygen") or _paid_avatar_enabled("latentsync"),
        "ai_broll": broll_configured(),
        "dub_engine": dub,
        "dub_premium": dub and premium,
    }


def _env_capabilities(env: Mapping[str, str]) -> dict[str, bool]:
    """Names-only view for an explicit env mapping (tests, CLI)."""
    from app.core.launch_preflight import script_llm_met

    provider = str(env.get("BROLL_GEN_PROVIDER", "") or "").strip().lower() or "comfyui"
    broll = (provider == "pixelle") or (
        provider == "comfyui" and _present(env, "COMFYUI_API_KEY")
    )
    dub = _dub_engine_configured(env)
    return {
        "free_tts": _has_module("edge_tts"),
        "script_llm": script_llm_met(env),
        "premium_voice": _present(env, "ELEVENLABS_API_KEY"),
        "avatar": _present(env, "HEYGEN_API_KEY"),
        "ai_broll": broll,
        "dub_engine": dub,
        "dub_premium": dub and _present(env, "ELEVENLABS_API_KEY"),
    }


def format_catalog(env: Mapping[str, str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """``{"available_formats": [...], "locked_formats": [...]}`` (names only).

    ``env=None`` reports what the running app will actually do (config-backed);
    an explicit mapping gives a deterministic names-only answer.
    """
    caps = _runtime_capabilities() if env is None else _env_capabilities(env)
    available: list[dict[str, Any]] = []
    locked: list[dict[str, Any]] = []
    for format_id, label, needs, unlock_env in _FORMATS:
        if not needs or caps.get(needs, False):
            available.append({"id": format_id, "label": label})
        else:
            locked.append({
                "id": format_id,
                "label": label,
                "code": FORMAT_LOCKED_CODE,
                "reason": _LOCK_REASONS[needs],
                "unlock_env": list(unlock_env),
            })
    return {"available_formats": available, "locked_formats": locked}


_CAPTIONS_ONLY = "captions_only"


def _text(params: Any, name: str) -> str:
    return str(getattr(params, name, "") or "").strip()


def needs_tts(params: Any) -> bool:
    """Whether the pipeline's TTS stage will synthesize speech for ``params``.

    Mirrors ``reelforge.stage_tts``: an uploaded narration (``voiceover_key``)
    never synthesizes; a captions-only reel over the creator's own footage uses
    that footage's audio; everything else (avatar layouts, the faceless
    captions-only preset) narrates with a TTS voice.
    """
    if _text(params, "voiceover_key"):
        return False
    if _text(params, "layout") != _CAPTIONS_ONLY:
        return True
    return not _text(params, "screen_recording_key") and bool(_text(params, "voice_name"))


def params_lock(params: Any, *, needs_script_llm: bool,
                capabilities: Mapping[str, bool] | None = None) -> tuple[str, str] | None:
    """``(format_id, reason)`` when this deployment cannot produce ``params``, else ``None``.

    Checked before any credit is debited, both when a job is created and when
    an old job is retried (a job created while a paid key was set must not be
    charged and then fail after the key is removed). ``capabilities`` overrides
    the runtime checks (tests).
    """
    caps = capabilities
    if _text(params, "layout") != _CAPTIONS_ONLY:
        provider_id = _text(params, "avatar_provider") or "heygen"
        ok = caps.get("avatar", False) if caps is not None else _paid_avatar_enabled(provider_id)
        if not ok:
            return "avatar_reel", f"{_LOCK_REASONS['avatar']}; use the captions_only layout"
    if needs_script_llm:
        ok = caps.get("script_llm", False) if caps is not None else script_llm_configured()
        if not ok:
            return "generated_script", f"{_LOCK_REASONS['script_llm']}; type your own script"
    if needs_tts(params):
        voice = _text(params, "voice_name")
        premium = caps.get("premium_voice", False) if caps is not None else elevenlabs_configured()
        if not (voice.startswith("elevenlabs:") and premium):
            free = caps.get("free_tts", False) if caps is not None else _has_module("edge_tts")
            if not free:
                return "faceless_free_voice", _LOCK_REASONS["free_tts"]
    return None


def enforce_params_available(request_id: str, params: Any, *, needs_script_llm: bool) -> None:
    """Raise the ``402 format_locked`` error for :func:`params_lock` hits."""
    locked = params_lock(params, needs_script_llm=needs_script_llm)
    if locked is not None:
        raise_format_locked(request_id, *locked)


def reuse_persisted_script(params: Any, script: str) -> Any:
    """A retry narrates the script the job already wrote instead of asking the LLM again.

    Only applies when the job had no typed script and is not a dub; returns
    ``params`` unchanged otherwise (or when it is not a dataclass).
    """
    import dataclasses

    text = str(script or "").strip()
    if not text or _text(params, "video_script") or _text(params, "translate_source_script"):
        return params
    if not dataclasses.is_dataclass(params) or "video_script" not in {f.name for f in dataclasses.fields(params)}:
        return params
    return dataclasses.replace(params, video_script=text)


def raise_format_locked(request_id: str, format_id: str, reason: str) -> None:
    """Reject a request for a format this deployment cannot produce (402)."""
    raise HttpException(
        task_id=request_id,
        status_code=FORMAT_LOCKED_STATUS,
        message=f"{request_id}: {FORMAT_LOCKED_MESSAGE} ({reason})",
        data={"code": FORMAT_LOCKED_CODE, "format": format_id, "reason": reason},
    )


__all__ = [
    "DEFAULT_FREE_VOICE",
    "FORMAT_LOCKED_CODE",
    "FORMAT_LOCKED_MESSAGE",
    "FORMAT_LOCKED_STATUS",
    "avatar_provider_enabled",
    "broll_configured",
    "elevenlabs_configured",
    "enforce_params_available",
    "format_catalog",
    "free_voice_for",
    "needs_tts",
    "params_lock",
    "raise_format_locked",
    "reuse_persisted_script",
    "script_llm_configured",
]
