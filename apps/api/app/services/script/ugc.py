"""UGC-creator script generation for ReelForge.

This module plugs into MPT's single LLM dispatch choke point
``app.services.llm._generate_response(prompt, app_config=None)`` and reuses its
helpers (``_strip_code_fence``, ``_clamp_text``, ``_max_retries`` and the
``"Error: " in response`` guard) rather than reimplementing any provider code.

The generator asks the model for a *structured* UGC reel script and returns a
plain, JSON-serializable dict::

    {
        "hook": str,               # scroll-stopping first line
        "segments": list[str],     # body beats, spoken in order
        "cta": str,                # closing call-to-action
        "full_text": str,          # hook + segments + cta, reconstructed here
        "est_duration_s": int,     # estimated narration length in seconds
    }

Language personas are authored natively (native Turkish glyphs, native English)
and 12 hook few-shot examples per language are loaded from
``resource/hooks/<lang>.yaml``.

All external-I/O failures return ``None`` (or raise ``ValueError`` inside the
private parser to trigger a retry) instead of crashing the pipeline — mirroring
MPT's ``generate_*`` conventions.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import re
from functools import lru_cache

import yaml
from loguru import logger

from app.services.llm import (
    _clamp_text,
    _generate_response,
    _max_retries,
    _strip_code_fence,
)
from app.utils import utils

# --------------------------------------------------------------------------- #
# Tunables (prescribed by INTEGRATION_CONTRACT §2.1)
# --------------------------------------------------------------------------- #
MAX_UGC_SUBJECT_LENGTH: int = 500
UGC_WORDS_PER_SECOND: float = 2.5  # ~150 wpm narration
UGC_SEGMENT_MIN: int = 1
UGC_SEGMENT_MAX: int = 8

# Duration guard rails so a malformed model response cannot request a 3-hour reel.
_MIN_TARGET_DURATION_S: int = 5
_MAX_TARGET_DURATION_S: int = 180

# Default sampling temperature for batch-variant diversity (§5a / CTO §4). A
# high value makes repeated calls with the *same* subject yield DISTINCT scripts,
# which is what "N variants per run" relies on. Clamped to a sane range before
# use so a caller cannot request a nonsensical value.
DEFAULT_UGC_TEMPERATURE: float = 0.9
_MIN_TEMPERATURE: float = 0.0
_MAX_TEMPERATURE: float = 2.0

# Per-field clamps to keep prompts and outputs bounded.
_MAX_HOOK_LENGTH: int = 240
_MAX_SEGMENT_LENGTH: int = 500
_MAX_CTA_LENGTH: int = 240

# Supported native personas. "auto" lets the model choose based on the subject.
_SUPPORTED_LANGUAGES: tuple[str, ...] = ("auto", "tr", "en")
_HOOK_FALLBACK: dict[str, list[str]] = {
    "tr": ["Bunu keşke daha önce bilseydim..."],
    "en": ["I wish someone told me this sooner..."],
}


# --------------------------------------------------------------------------- #
# Hook few-shot loading
# --------------------------------------------------------------------------- #
def _normalize_language(language: str) -> str:
    """Map an arbitrary language hint to one of the supported persona codes."""
    value = (language or "").strip().lower()
    if not value:
        return "auto"
    # Accept common variants like "tr-TR", "turkish", "en-US", "english".
    if value in _SUPPORTED_LANGUAGES:
        return value
    if value.startswith("tr") or value.startswith("turk"):
        return "tr"
    if value.startswith("en") or value.startswith("engl"):
        return "en"
    return "auto"


@lru_cache(maxsize=8)
def _load_hooks(language: str) -> tuple[str, ...]:
    """Load the native hook templates for ``language`` from resource/hooks/<lang>.yaml.

    Returns a tuple (hashable, so it is lru_cache friendly). On any failure the
    module-level fallback is used so prompt building never crashes.
    """
    lang = language if language in _HOOK_FALLBACK else "en"
    path = os.path.join(utils.resource_dir("hooks"), f"{lang}.yaml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        hooks = data.get("hooks") if isinstance(data, dict) else None
        cleaned = [str(h).strip() for h in (hooks or []) if str(h).strip()]
        if cleaned:
            return tuple(cleaned)
        logger.warning(f"no hooks found in {path}; using fallback")
    except FileNotFoundError:
        logger.warning(f"hook file not found: {path}; using fallback")
    except Exception as exc:  # noqa: BLE001 - never let resource loading crash prompts
        logger.warning(f"failed to load hooks from {path}: {exc}; using fallback")
    return tuple(_HOOK_FALLBACK[lang])


def _render_hook_examples(language: str, subject: str) -> str:
    """Render the 12 few-shot hook lines for ``language`` with {subject} filled in."""
    hooks = _load_hooks(language)
    lines: list[str] = []
    for hook in hooks:
        try:
            rendered = hook.replace("{subject}", subject) if subject else hook
        except Exception:  # noqa: BLE001 - defensive; templates are trusted
            rendered = hook
        lines.append(f"- {rendered}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Personas
# --------------------------------------------------------------------------- #
_TR_PERSONA = (
    "Sen viral kısa video (Reels/TikTok) senaryoları yazan bir Türk UGC "
    "içerik üreticisisin. Doğal, samimi ve konuşma diliyle yazarsın; birinci "
    "tekil şahıs kullanır, izleyiciyle 'sen' diye konuşursun. Reklam gibi değil, "
    "gerçek bir insanın deneyimini anlatır gibi yazarsın. Cümleler kısa ve "
    "akıcıdır. Türkçe karakterleri (ş, ç, ı, İ, ö, ü, ğ) doğru kullanırsın."
)
_EN_PERSONA = (
    "You are a native English-speaking UGC creator who writes viral short-form "
    "video scripts (Reels/TikTok). You write in a natural, conversational, "
    "first-person voice, speaking directly to the viewer as 'you'. It sounds "
    "like a real person sharing an experience, never like an ad. Sentences are "
    "short and punchy."
)


def _persona_block(language: str) -> str:
    """Return the persona instruction block for the requested language."""
    if language == "tr":
        return _TR_PERSONA
    if language == "en":
        return _EN_PERSONA
    # auto: give the model both personas and let it match the subject language.
    return (
        "You are a native UGC creator who writes viral short-form video scripts. "
        "Detect the dominant language of the video subject and write the ENTIRE "
        "script natively in that language (do not translate).\n"
        f"- If Turkish: {_TR_PERSONA}\n"
        f"- If English: {_EN_PERSONA}"
    )


# --------------------------------------------------------------------------- #
# Prompt builder
# --------------------------------------------------------------------------- #
def build_ugc_script_prompt(
    video_subject: str,
    language: str = "auto",
    target_duration_s: int = 30,
) -> str:
    """Build the structured-JSON UGC script prompt.

    Embeds the native persona plus 12 native hook few-shot examples for the
    resolved language(s), and instructs the model to return a single minified
    JSON object with hook/segments/cta/est_duration_s.
    """
    subject = _clamp_text(video_subject, MAX_UGC_SUBJECT_LENGTH)
    lang = _normalize_language(language)
    duration = _clamp_duration(target_duration_s)

    # Rough word budget so the model paces the narration for the target length.
    word_budget = max(int(round(duration * UGC_WORDS_PER_SECOND)), 1)

    if lang == "auto":
        hook_examples = (
            "### Turkish hook examples\n"
            + _render_hook_examples("tr", subject)
            + "\n\n### English hook examples\n"
            + _render_hook_examples("en", subject)
        )
        language_rule = (
            "Write the entire script natively in the language of the video "
            "subject. Do NOT translate; do NOT mix languages."
        )
    else:
        label = "Turkish" if lang == "tr" else "English"
        hook_examples = f"### {label} hook examples\n" + _render_hook_examples(
            lang, subject
        )
        language_rule = f"Write the entire script natively in {label}. Do NOT translate."

    prompt = f"""
# Role: Viral UGC Short-Video Scriptwriter

{_persona_block(lang)}

## Goal
Write a single spoken UGC reel script about the subject below. It must open with
a scroll-stopping hook, deliver the value in a few short body beats, and end with
a natural call-to-action.

## Hook inspiration (style only — write a fresh, subject-specific hook)
{hook_examples}

## Constraints
1. Respond ONLY with a single valid minified JSON object. No markdown, no code
   fences, no commentary before or after.
2. The JSON must contain exactly these keys: "hook", "segments", "cta",
   "est_duration_s".
3. "hook": one punchy opening line (at most {_MAX_HOOK_LENGTH} characters).
4. "segments": a JSON array of {UGC_SEGMENT_MIN}-{UGC_SEGMENT_MAX} short spoken
   sentences that form the body, in the order they are spoken. Each is a single
   plain sentence with no line breaks.
5. "cta": one closing call-to-action line (at most {_MAX_CTA_LENGTH} characters).
6. "est_duration_s": integer estimate of the total spoken length in seconds.
7. Aim for roughly {word_budget} spoken words total (~{duration}s at
   {UGC_WORDS_PER_SECOND} words/sec). Do not pad.
8. {language_rule}
9. Sound like a real creator talking to a friend — no "voiceover"/"narrator"
   labels, no stage directions, no emojis, no hashtags.

## Output Example
{{"hook":"...","segments":["...","..."],"cta":"...","est_duration_s":{duration}}}

## Context
### Video Subject
{subject}

### Target Duration (seconds)
{duration}
""".strip()
    return prompt


# --------------------------------------------------------------------------- #
# Parsing / validation
# --------------------------------------------------------------------------- #
def _clamp_duration(target_duration_s: int) -> int:
    """Clamp a requested duration into the supported range."""
    try:
        value = int(target_duration_s)
    except (TypeError, ValueError):
        return 30
    return max(_MIN_TARGET_DURATION_S, min(value, _MAX_TARGET_DURATION_S))


def _clamp_temperature(temperature: float) -> float:
    """Clamp a requested sampling temperature into the supported range."""
    try:
        value = float(temperature)
    except (TypeError, ValueError):
        return DEFAULT_UGC_TEMPERATURE
    return max(_MIN_TEMPERATURE, min(value, _MAX_TEMPERATURE))


def _call_generate_response(prompt: str, app_config, temperature: float) -> str:
    """Invoke ``_generate_response`` threading ``temperature`` only if supported.

    MPT's shared ``llm._generate_response(prompt, app_config=None)`` does not
    (yet) accept a ``temperature`` kwarg. Rather than guess, we inspect the
    *currently bound* callable's signature and pass ``temperature`` only when it
    is accepted — so a future/overridden implementation (or a test double) can
    honor variant diversity, while the stock implementation keeps working
    unchanged. Passing ``app_config`` is likewise conditional on it being set, to
    preserve the existing pass-through identity semantics.
    """
    kwargs: dict = {}
    if app_config is not None:
        kwargs["app_config"] = app_config
    try:
        params = inspect.signature(_generate_response).parameters
    except (TypeError, ValueError):  # pragma: no cover - defensive
        params = {}
    if "temperature" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    ):
        kwargs["temperature"] = temperature
    return _generate_response(prompt, **kwargs)


def _estimate_duration_from_text(full_text: str) -> int:
    """Estimate narration seconds from a word count (fallback when the model omits it)."""
    words = len(re.findall(r"\S+", full_text or ""))
    if words <= 0:
        return _MIN_TARGET_DURATION_S
    return max(int(math.ceil(words / UGC_WORDS_PER_SECOND)), _MIN_TARGET_DURATION_S)


def _coerce_json(response: str) -> dict:
    """Parse the raw LLM response into a dict, tolerating a wrapping code fence.

    Falls back to extracting the first ``{...}`` object (mirrors
    ``llm._parse_social_metadata``). Raises ValueError if nothing parses.
    """
    try:
        data = json.loads(_strip_code_fence(response))
    except Exception:
        match = re.search(r"\{.*\}", response or "", re.DOTALL)
        if not match:
            raise ValueError("ugc script response is not a JSON object")
        data = json.loads(match.group())

    if not isinstance(data, dict):
        raise ValueError("ugc script response is not a JSON object")
    return data


def _parse_ugc_script(response: str) -> dict:
    """Validate and normalize a UGC script LLM response.

    Returns ``{hook, segments, cta, full_text, est_duration_s}``. ``full_text``
    is reconstructed from ``hook``/``segments``/``cta`` here because the litellm
    (and other OpenAI-compatible) adapters strip embedded newlines — relying on
    them would collapse the paragraphs. Raises ``ValueError`` on invalid JSON or
    missing/empty fields so the caller can retry.
    """
    data = _coerce_json(response)

    hook = _clamp_text(data.get("hook", ""), _MAX_HOOK_LENGTH)
    if not hook:
        raise ValueError("ugc script response is missing 'hook'")

    raw_segments = data.get("segments", [])
    if not isinstance(raw_segments, list):
        raise ValueError("ugc script 'segments' must be a list")
    segments = [_clamp_text(seg, _MAX_SEGMENT_LENGTH) for seg in raw_segments]
    segments = [seg for seg in segments if seg]
    if len(segments) < UGC_SEGMENT_MIN or len(segments) > UGC_SEGMENT_MAX:
        raise ValueError(
            f"ugc script must have {UGC_SEGMENT_MIN}-{UGC_SEGMENT_MAX} segments, "
            f"got {len(segments)}"
        )

    cta = _clamp_text(data.get("cta", ""), _MAX_CTA_LENGTH)
    if not cta:
        raise ValueError("ugc script response is missing 'cta'")

    # Reconstruct the spoken text from parts (newlines get stripped upstream).
    full_text = "\n\n".join([hook, *segments, cta])

    est_duration_s = data.get("est_duration_s")
    try:
        est_duration_s = int(est_duration_s)
    except (TypeError, ValueError):
        est_duration_s = 0
    if est_duration_s <= 0:
        est_duration_s = _estimate_duration_from_text(full_text)
    est_duration_s = _clamp_duration(est_duration_s)

    return {
        "hook": hook,
        "segments": segments,
        "cta": cta,
        "full_text": full_text,
        "est_duration_s": est_duration_s,
    }


# --------------------------------------------------------------------------- #
# Public generator
# --------------------------------------------------------------------------- #
def generate_ugc_script(
    video_subject: str,
    language: str = "auto",
    target_duration_s: int = 30,
    temperature: float = DEFAULT_UGC_TEMPERATURE,
    app_config=None,
) -> dict | None:
    """Generate a structured UGC reel script.

    ``temperature`` controls sampling diversity (§5a / CTO §4): the default of
    ``0.9`` makes repeated calls with the *same* subject produce DISTINCT scripts
    so batch mode can fan a single request out into N different reels. It is
    threaded through to the LLM only when the bound ``_generate_response`` accepts
    a ``temperature`` kwarg (see ``_call_generate_response``); the stock MPT
    dispatch does not yet accept it, in which case the value is documented/ignored
    rather than silently altering behavior.

    Retries up to ``llm._max_retries`` times on invalid JSON / provider errors.
    Returns the parsed dict (see ``_parse_ugc_script``) or ``None`` if every
    attempt fails — never raises to the caller.
    """
    subject = _clamp_text(video_subject, MAX_UGC_SUBJECT_LENGTH)
    if not subject:
        logger.error("cannot generate ugc script: empty video_subject")
        return None

    lang = _normalize_language(language)
    duration = _clamp_duration(target_duration_s)
    temp = _clamp_temperature(temperature)
    prompt = build_ugc_script_prompt(
        video_subject=subject,
        language=lang,
        target_duration_s=duration,
    )
    logger.info(
        f"generating ugc script: language={lang}, target_duration_s={duration}, "
        f"temperature={temp}, subject_len={len(subject)}"
    )

    for attempt in range(_max_retries):
        response = ""
        try:
            response = _call_generate_response(prompt, app_config, temp)

            # _generate_response never raises; it encodes failures as "Error: ...".
            if isinstance(response, str) and "Error: " in response:
                logger.error(f"failed to generate ugc script: {response}")
            else:
                script = _parse_ugc_script(response)
                logger.success(
                    "ugc script ready: "
                    f"segments={len(script['segments'])}, "
                    f"est_duration_s={script['est_duration_s']}"
                )
                return script
        except ValueError as exc:
            logger.warning(f"invalid ugc script json: {exc}")
        except Exception as exc:  # noqa: BLE001 - keep the pipeline alive
            logger.warning(f"failed to generate ugc script: {exc}")

        if attempt < _max_retries - 1:
            logger.warning(f"retrying ugc script generation... {attempt + 1}")

    logger.error("failed to generate ugc script after all retries")
    return None
