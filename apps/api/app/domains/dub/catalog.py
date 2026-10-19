"""Pure option catalog for "dub any uploaded video".

Languages, voices, engines, pricing and the free-tier flag live here so the
router, the worker and the tests share one source of truth. No I/O beyond
reading config/env names; never returns a secret value.

The dub pipeline itself runs inside the pyvideotrans container (GPL-3.0). This
module only describes the *command-line options* we hand to that container; it
imports nothing from pyvideotrans.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

# --------------------------------------------------------------------------- #
# Engines. Indices are pyvideotrans v4.13 CLI provider ids
# (videotrans/tts/_constants.py, videotrans/translator/_constants.py,
# videotrans/recognition/_constants.py). Pinned with the image tag.
# --------------------------------------------------------------------------- #
PYVIDEOTRANS_VERSION = "v4.13"

TTS_EDGE = 0  # EDGE_TTS: free Microsoft neural voices, no key
TTS_ELEVENLABS = 24  # ELEVENLABS_TTS: needs ELEVENLABS_API_KEY

RECOGN_FASTER_WHISPER = 0  # FASTER_WHISPER: local CPU model, no key

TRANSLATE_GOOGLE = 0  # GOOGLE_INDEX: free web endpoint, no key
TRANSLATE_OPENAI_COMPATIBLE = 9  # LOCALLLM_INDEX: any OpenAI-compatible API (our Relay)

SUBTITLE_SOFT = 2  # 0=none, 1=hard, 2=soft, 3=double hard, 4=double soft

VOICE_ENGINE_EDGE = "edge"
VOICE_ENGINE_ELEVENLABS = "elevenlabs"
VOICE_ENGINES = (VOICE_ENGINE_EDGE, VOICE_ENGINE_ELEVENLABS)

WHISPER_MODELS = ("tiny", "base", "small", "medium")
DEFAULT_WHISPER_MODEL = "small"

DUB_JOB_KIND = "dub_video"

# Default prices (config-overridable). Every dub costs standard credits for the
# CPU work. ElevenLabs is a paid per-character API, so a premium-voice dub ALSO
# spends premium voice credits: a standard credit never pays for ElevenLabs.
DEFAULT_FREE_COST = 2
DEFAULT_PREMIUM_VOICE_CREDITS = 6
DEFAULT_MAX_SECONDS = 600  # 10 min per video on a CPU box
DEFAULT_MAX_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True)
class Language:
    code: str  # pyvideotrans language code
    label: str
    edge_voices: tuple[str, ...]  # first entry is the default


# Languages we offer in the UI. Every code exists in pyvideotrans' LANG_CODE and
# every voice is a Microsoft edge-tts neural voice for that locale.
LANGUAGES: tuple[Language, ...] = (
    Language("en", "English", ("en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural", "en-GB-RyanNeural")),
    Language("tr", "Turkish", ("tr-TR-EmelNeural", "tr-TR-AhmetNeural")),
    Language("es", "Spanish", ("es-ES-ElviraNeural", "es-ES-AlvaroNeural", "es-MX-DaliaNeural")),
    Language("pt", "Portuguese", ("pt-BR-FranciscaNeural", "pt-BR-AntonioNeural", "pt-PT-RaquelNeural")),
    Language("fr", "French", ("fr-FR-DeniseNeural", "fr-FR-HenriNeural")),
    Language("de", "German", ("de-DE-KatjaNeural", "de-DE-ConradNeural")),
    Language("it", "Italian", ("it-IT-ElsaNeural", "it-IT-DiegoNeural")),
    Language("nl", "Dutch", ("nl-NL-ColetteNeural", "nl-NL-MaartenNeural")),
    Language("pl", "Polish", ("pl-PL-ZofiaNeural", "pl-PL-MarekNeural")),
    Language("ru", "Russian", ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural")),
    Language("uk", "Ukrainian", ("uk-UA-PolinaNeural", "uk-UA-OstapNeural")),
    Language("ar", "Arabic", ("ar-SA-ZariyahNeural", "ar-SA-HamedNeural")),
    Language("hi", "Hindi", ("hi-IN-SwaraNeural", "hi-IN-MadhurNeural")),
    Language("id", "Indonesian", ("id-ID-GadisNeural", "id-ID-ArdiNeural")),
    Language("vi", "Vietnamese", ("vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural")),
    Language("th", "Thai", ("th-TH-PremwadeeNeural", "th-TH-NiwatNeural")),
    Language("ja", "Japanese", ("ja-JP-NanamiNeural", "ja-JP-KeitaNeural")),
    Language("ko", "Korean", ("ko-KR-SunHiNeural", "ko-KR-InJoonNeural")),
    Language("zh-cn", "Chinese (Simplified)", ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural")),
    Language("zh-tw", "Chinese (Traditional)", ("zh-TW-HsiaoChenNeural", "zh-TW-YunJheNeural")),
)

_BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}


class DubOptionError(ValueError):
    """A client-supplied dub option is not supported (maps to HTTP 400)."""


def language(code: str) -> Language:
    normalized = str(code or "").strip().lower()
    lang = _BY_CODE.get(normalized)
    if lang is None:
        raise DubOptionError(f"unsupported language {code!r}")
    return lang


def _cfg(name: str, default: Any) -> Any:
    try:
        from app.config import config

        value = config.app.get(name, None)
    except Exception:  # noqa: BLE001 - config is optional in pure contexts
        value = None
    return default if value in (None, "") else value


def _int_cfg(name: str, default: int) -> int:
    try:
        return max(0, int(_cfg(name, default)))
    except (TypeError, ValueError):
        return default


def elevenlabs_available(env: Mapping[str, str] | None = None) -> bool:
    """True when an ElevenLabs key is configured (names only; never the value)."""
    if env is not None:
        return bool(str(env.get("ELEVENLABS_API_KEY", "") or "").strip())
    try:
        from app.core.launch.formats import elevenlabs_configured

        if elevenlabs_configured():
            return True
    except Exception:  # noqa: BLE001 - fall through to env
        pass
    return bool(str(os.environ.get("ELEVENLABS_API_KEY", "") or "").strip())


def sidecar_image(env: Mapping[str, str] | None = None) -> str:
    """The configured pyvideotrans image tag, or "" when the sidecar is not set up."""
    source = os.environ if env is None else env
    image = str(source.get("PYVIDEOTRANS_IMAGE", "") or "").strip()
    if image or env is not None:
        return image
    return str(_cfg("dub_sidecar_image", "") or "").strip()


def sidecar_url(env: Mapping[str, str] | None = None) -> str:
    """The dub runner service URL (HTTP mode), or "" when the worker runs docker itself."""
    source = os.environ if env is None else env
    url = str(source.get("DUB_SIDECAR_URL", "") or "").strip()
    if url or env is not None:
        return url
    return str(_cfg("dub_sidecar_url", "") or "").strip()


def sidecar_configured(env: Mapping[str, str] | None = None) -> bool:
    """True when the engine can run: an image for docker mode or a runner URL."""
    return bool(sidecar_image(env) or sidecar_url(env))


def translation_engine(env: Mapping[str, str] | None = None) -> str:
    """``"relay"`` when our LLM Relay is configured, else the free ``"google"`` path."""
    source = _relay_env(env)
    return "relay" if str(source.get("RELAY_URL", "") or "").strip() else "google"


def _relay_env(env: Mapping[str, str] | None = None) -> Mapping[str, Any]:
    """Env with ``RAILYARD_RELAY_*`` mapped onto ``RELAY_*`` (the names the box uses)."""
    source = os.environ if env is None else env
    try:
        from app.integrations.railyard import relay_env

        return relay_env(source)
    except Exception:  # noqa: BLE001 - integration optional in pure contexts
        return source


@dataclass(frozen=True)
class DubPlan:
    """A validated, fully resolved dub request (stored on the ``Job`` params)."""

    source_language: str
    target_language: str
    voice_engine: str
    voice: str
    whisper_model: str
    translation: str
    free: bool
    credits_cost: int
    premium_voice_credits: int = 0

    def as_params(self) -> dict[str, Any]:
        return {
            "source_language": self.source_language,
            "target_language": self.target_language,
            "voice_engine": self.voice_engine,
            "voice": self.voice,
            "whisper_model": self.whisper_model,
            "translation": self.translation,
            "free": self.free,
            "credits_cost": self.credits_cost,
            "premium_voice_credits": self.premium_voice_credits,
        }


def is_free_path(voice_engine: str, whisper_model: str) -> bool:
    """Free-tier path: edge-tts voices + local faster-whisper (no paid API key)."""
    return voice_engine == VOICE_ENGINE_EDGE and whisper_model in WHISPER_MODELS


def credit_cost(free: bool) -> int:
    """Standard credits for a dub: the CPU work, the same for every voice."""
    return _int_cfg("reelforge_dub_free_cost", DEFAULT_FREE_COST)


def premium_voice_credit_cost(free: bool) -> int:
    """Premium voice credits for a dub (0 on the free-voice path)."""
    if free:
        return 0
    return _int_cfg("reelforge_dub_premium_voice_credits", DEFAULT_PREMIUM_VOICE_CREDITS)


def max_seconds() -> int:
    return _int_cfg("reelforge_dub_max_seconds", DEFAULT_MAX_SECONDS)


def max_bytes() -> int:
    return _int_cfg("reelforge_dub_max_bytes", DEFAULT_MAX_BYTES)


def resolve_plan(
    *,
    source_language: str,
    target_language: str,
    voice_engine: str = "",
    voice: str = "",
    whisper_model: str = "",
    elevenlabs_ok: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> DubPlan:
    """Validate client options and resolve defaults. Raises :class:`DubOptionError`.

    * languages must be in :data:`LANGUAGES` and differ;
    * the voice engine defaults to free edge-tts; ElevenLabs needs a key;
    * an edge voice must belong to the target language (defaults to its first);
    * an ElevenLabs voice is a voice name/id passed through (bounded length).
    """
    src = language(source_language)
    tgt = language(target_language)
    if src.code == tgt.code:
        raise DubOptionError("source and target languages must differ")

    engine = str(voice_engine or VOICE_ENGINE_EDGE).strip().lower()
    if engine not in VOICE_ENGINES:
        raise DubOptionError(f"unsupported voice engine {voice_engine!r}")
    if engine == VOICE_ENGINE_ELEVENLABS:
        ok = elevenlabs_available(env) if elevenlabs_ok is None else elevenlabs_ok
        if not ok:
            raise DubOptionError("ElevenLabs is not configured on this deployment; use a free voice")

    chosen_voice = str(voice or "").strip()
    if engine == VOICE_ENGINE_EDGE:
        if not chosen_voice:
            chosen_voice = tgt.edge_voices[0]
        elif chosen_voice not in tgt.edge_voices:
            raise DubOptionError(f"voice {chosen_voice!r} is not offered for {tgt.label}")
    else:
        if not chosen_voice:
            raise DubOptionError("pick an ElevenLabs voice")
        if len(chosen_voice) > 64 or not all(c.isalnum() or c in " -_." for c in chosen_voice):
            raise DubOptionError("invalid ElevenLabs voice name")

    model = str(whisper_model or DEFAULT_WHISPER_MODEL).strip().lower()
    if model not in WHISPER_MODELS:
        raise DubOptionError(f"unsupported speech model {whisper_model!r}")

    free = is_free_path(engine, model)
    return DubPlan(
        source_language=src.code,
        target_language=tgt.code,
        voice_engine=engine,
        voice=chosen_voice,
        whisper_model=model,
        translation=translation_engine(env),
        free=free,
        credits_cost=credit_cost(free),
        premium_voice_credits=premium_voice_credit_cost(free),
    )


def options_document(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """What the UI may offer right now (names/booleans only)."""
    eleven = elevenlabs_available(env)
    return {
        "available": sidecar_configured(env),
        "engine": f"pyvideotrans {PYVIDEOTRANS_VERSION} (separate container)",
        "languages": [
            {"code": lang.code, "label": lang.label, "voices": list(lang.edge_voices)}
            for lang in LANGUAGES
        ],
        "voice_engines": [
            {"id": VOICE_ENGINE_EDGE, "label": "Free voices (Microsoft edge-tts)", "available": True, "free": True},
            {"id": VOICE_ENGINE_ELEVENLABS, "label": "ElevenLabs", "available": eleven, "free": False},
        ],
        "whisper_models": list(WHISPER_MODELS),
        "default_whisper_model": DEFAULT_WHISPER_MODEL,
        "translation": translation_engine(env),
        "costs": {
            "free": credit_cost(True),
            "premium": credit_cost(False),
            "premium_voice_credits": premium_voice_credit_cost(False),
        },
        "max_seconds": max_seconds(),
        "max_bytes": max_bytes(),
    }


__all__ = [
    "DUB_JOB_KIND",
    "DubOptionError",
    "DubPlan",
    "LANGUAGES",
    "PYVIDEOTRANS_VERSION",
    "SUBTITLE_SOFT",
    "TRANSLATE_GOOGLE",
    "TRANSLATE_OPENAI_COMPATIBLE",
    "TTS_EDGE",
    "TTS_ELEVENLABS",
    "RECOGN_FASTER_WHISPER",
    "VOICE_ENGINE_EDGE",
    "VOICE_ENGINE_ELEVENLABS",
    "credit_cost",
    "elevenlabs_available",
    "premium_voice_credit_cost",
    "is_free_path",
    "language",
    "max_bytes",
    "max_seconds",
    "options_document",
    "resolve_plan",
    "sidecar_configured",
    "sidecar_url",
    "sidecar_image",
    "translation_engine",
]
