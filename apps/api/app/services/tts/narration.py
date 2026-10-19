"""Reel narration voice chain (M1.4): Kokoro first, edge-tts kept as fallback.

Order for a reel narrated by a free voice:

1. **Kokoro** (self-hosted sidecar on box 1, word timings included) when
   ``KOKORO_URL`` is set, ``MENIVOR_KOKORO_PRIMARY`` is not off, and the reel's
   language is in ``MENIVOR_KOKORO_LANGS`` (default ``en``: English is the only
   language where Kokoro-82M is clearly good; others are opt-in, never faked).
2. **edge-tts** (Microsoft neural voice for the language). Always kept.
3. **ElevenLabs**, only when it is configured AND the job paid for a premium
   voice. A standard credit never pays for ElevenLabs.
4. Otherwise a clear :class:`NarrationUnavailable` error.

When the creator chose a premium voice and paid for it, ElevenLabs goes first
(they get what they paid for) and the free engines follow as fallbacks.

Voices from other explicit engines (Chatterbox, Gemini, Azure v2, SiliconFlow,
MiMo, ``kokoro:``, no-voice) are used as chosen, with the free chain behind
them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from loguru import logger

ENGINE_KOKORO = "kokoro"
ENGINE_EDGE = "edge-tts"
ENGINE_ELEVENLABS = "elevenlabs"
ENGINE_CHOSEN = "chosen"

_OFF = {"0", "off", "false", "no", "disabled"}
DEFAULT_KOKORO_LANGS = ("en",)

# Language prefix -> (female, male) Kokoro-82M v1.0 voice ids. Only languages
# the model ships voices for; en-GB gets the British voices.
KOKORO_VOICES: dict[str, tuple[str, str]] = {
    "en": ("af_heart", "am_michael"),
    "en-gb": ("bf_emma", "bm_george"),
    "es": ("ef_dora", "em_alex"),
    "fr": ("ff_siwis", "ff_siwis"),
    "it": ("if_sara", "im_nicola"),
    "pt": ("pf_dora", "pm_alex"),
    "hi": ("hf_alpha", "hm_omega"),
    "ja": ("jf_alpha", "jm_kumo"),
    "zh": ("zf_xiaobei", "zm_yunjian"),
}

_EXPLICIT_PREFIXES = ("siliconflow:", "gemini:", "mimo:", "chatterbox:", "kokoro:")


class NarrationUnavailable(RuntimeError):
    """No voice engine could narrate the script. ``attempts`` lists what was tried."""

    def __init__(self, attempts: list[str]):
        self.attempts = list(attempts)
        tried = ", ".join(attempts) if attempts else "none"
        super().__init__(
            "No voice engine could narrate this reel right now "
            f"(tried: {tried}). Please try again shortly."
        )


@dataclass(frozen=True)
class VoiceStep:
    engine: str
    voice_name: str


@dataclass(frozen=True)
class NarrationResult:
    sub_maker: Any
    engine: str
    voice_name: str
    attempts: tuple[str, ...]

    @property
    def fell_back(self) -> bool:
        return len(self.attempts) > 1


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def kokoro_languages(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    raw = str(_env(env).get("MENIVOR_KOKORO_LANGS", "") or "").strip().lower()
    if not raw:
        return DEFAULT_KOKORO_LANGS
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def kokoro_primary_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = _env(env)
    if not str(source.get("KOKORO_URL", "") or "").strip():
        return False
    flag = str(source.get("MENIVOR_KOKORO_PRIMARY", "") or "").strip().lower()
    return flag not in _OFF


def _lang_key(language: str) -> str:
    return str(language or "").strip().lower().replace("_", "-")


def kokoro_supports(language: str, env: Mapping[str, str] | None = None) -> bool:
    """True when Kokoro is the primary free voice for ``language`` here."""
    key = _lang_key(language)
    prefix = key[:2]
    if not prefix or prefix not in KOKORO_VOICES:
        return False
    return prefix in kokoro_languages(env)


def kokoro_voice_for(language: str, gender: str = "female") -> str:
    """``kokoro:<id>`` for the language and gender, or ``""`` when none exists."""
    key = _lang_key(language)
    pair = KOKORO_VOICES.get(key[:5]) or KOKORO_VOICES.get(key[:2])
    if not pair:
        return ""
    return f"kokoro:{pair[1] if gender == 'male' else pair[0]}"


def free_voice_engine(language: str, env: Mapping[str, str] | None = None) -> str:
    """Which engine narrates a free-voice reel in ``language`` (for honest UI copy)."""
    if kokoro_primary_enabled(env) and kokoro_supports(language, env):
        return ENGINE_KOKORO
    return ENGINE_EDGE


def is_edge_voice(voice_name: str) -> bool:
    """A plain edge-tts voice (``xx-YY-NameNeural[-Gender]``), not Azure v2."""
    name = str(voice_name or "").strip()
    if not name or name.startswith("elevenlabs:") or name.startswith(_EXPLICIT_PREFIXES):
        return False
    if name.lower() in {"no-voice", "none"}:
        return False
    bare = name.replace("-Female", "").replace("-Male", "")
    return "Neural" in bare and not bare.endswith("-V2")


def _gender(voice_name: str) -> str:
    return "male" if str(voice_name or "").endswith("-Male") else "female"


def _language_of(voice_name: str, language: str) -> str:
    if language and language.strip().lower() not in {"auto", "detect"}:
        return language
    # "en-US-AriaNeural-Female" -> "en-us"
    parts = str(voice_name or "").split("-")
    return "-".join(parts[:2]).lower() if len(parts) >= 2 else ""


def plan_chain(
    voice_name: str,
    *,
    language: str = "",
    free_voice: str = "",
    premium_voice: str = "",
    premium_first: bool = False,
    env: Mapping[str, str] | None = None,
) -> list[VoiceStep]:
    """The ordered engines to try for one narration.

    ``voice_name`` is the voice picked after the premium/free decision.
    ``free_voice`` is the edge-tts voice for the language. ``premium_voice`` is an
    ``elevenlabs:`` voice ONLY when ElevenLabs is configured and the job paid for
    it; ``premium_first`` puts it at the front (the creator chose it).
    """
    steps: list[VoiceStep] = []
    seen: set[str] = set()

    def add(engine: str, name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            steps.append(VoiceStep(engine, name))

    if premium_voice and premium_first:
        add(ENGINE_ELEVENLABS, premium_voice)

    edge = voice_name if is_edge_voice(voice_name) else free_voice
    if voice_name and not is_edge_voice(voice_name) and not voice_name.startswith("elevenlabs:"):
        # An explicit engine the creator chose (or no-voice) goes first.
        add(ENGINE_KOKORO if voice_name.startswith("kokoro:") else ENGINE_CHOSEN, voice_name)

    lang = _language_of(edge or voice_name, language)
    if kokoro_primary_enabled(env) and kokoro_supports(lang, env):
        add(ENGINE_KOKORO, kokoro_voice_for(lang, _gender(edge or voice_name)))
    add(ENGINE_EDGE, edge)

    if premium_voice and not premium_first:
        add(ENGINE_ELEVENLABS, premium_voice)
    return steps


TtsFn = Callable[..., Any]


def narrate(
    text: str,
    steps: list[VoiceStep],
    voice_file: str,
    voice_rate: float = 1.0,
    *,
    tts_fn: TtsFn | None = None,
) -> NarrationResult:
    """Try each step in order; the first one that writes audio wins."""
    if tts_fn is None:
        from app.services import voice

        tts_fn = voice.tts
    attempts: list[str] = []
    for step in steps:
        attempts.append(f"{step.engine}:{step.voice_name}")
        if os.path.exists(voice_file):
            os.remove(voice_file)  # never let a failed engine's partial file pass as audio
        try:
            sub_maker = tts_fn(
                text=text, voice_name=step.voice_name, voice_rate=voice_rate, voice_file=voice_file
            )
        except Exception as exc:  # noqa: BLE001 - one engine down never ends the chain
            logger.warning(f"narration engine {step.engine} failed: {exc}")
            sub_maker = None
        if sub_maker is not None and os.path.isfile(voice_file) and os.path.getsize(voice_file) > 0:
            if len(attempts) > 1:
                logger.warning(f"narration fell back to {step.engine} after {attempts[:-1]}")
            return NarrationResult(sub_maker, step.engine, step.voice_name, tuple(attempts))
        logger.warning(f"narration engine {step.engine} produced no audio")
    raise NarrationUnavailable(attempts)
