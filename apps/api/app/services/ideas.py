"""SPARK — AI Idea Engine for ReelForge.

A creator describes their app / niche and this module asks the configured LLM
(Claude via litellm, or any other MPT provider) for N ready-to-shoot viral UGC
video *concepts*. Each concept is a plain, JSON-serializable dict::

    {
        "title": str,                    # short internal label for the idea
        "hook": str,                     # scroll-stopping first line (<=12 words)
        "angle": str,                    # the persuasion angle / narrative frame
        "format": str,                   # e.g. "talking head", "screen recording"
        "script_outline": list[str],     # 2-4 beats the reel should hit
        "suggested_layout": str,         # one of pip | hook_intro | split
        "suggested_caption_style": str,  # one of the 4 caption presets
        "language": str,                 # tr | en
        "est_duration_s": int,           # estimated reel length in seconds
    }

The module plugs into MPT's single LLM dispatch choke point
``app.services.llm._generate_response(prompt, app_config=None)`` and reuses its
helpers (``_clamp_text``, ``_strip_code_fence``, ``_max_retries`` and the
``"Error: " in response`` guard) exactly like ``app.services.script.ugc`` does,
rather than reimplementing any provider code.

All external-I/O failures return ``None`` from the public generator (or raise
``ValueError`` inside the private parser to trigger a retry) instead of crashing
the pipeline — mirroring MPT's ``generate_*`` conventions. One-click "Make this"
lives at the API layer: it maps an idea to the existing ``POST /jobs`` request
(``video_subject`` from hook/angle, ``prompt`` from ``script_outline``, and
``layout``/``caption_style``/``language`` straight from the suggestions here).
"""

from __future__ import annotations

import inspect
import json
import re

from loguru import logger

from app.services.llm import (
    _clamp_text,
    _generate_response,
    _max_retries,
    _strip_code_fence,
)

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #
MIN_IDEA_COUNT: int = 1
MAX_IDEA_COUNT: int = 10
DEFAULT_IDEA_COUNT: int = 6

MAX_APP_CONTEXT_LENGTH: int = 1000
MAX_AUDIENCE_LENGTH: int = 300

# Per-field clamps so a malformed model response cannot bloat the payload.
_MAX_TITLE_LENGTH: int = 120
_MAX_HOOK_LENGTH: int = 200
_MAX_ANGLE_LENGTH: int = 300
_MAX_FORMAT_LENGTH: int = 120
_MAX_BEAT_LENGTH: int = 300

# Structural bounds on the script outline.
_MIN_BEATS: int = 2
_MAX_BEATS: int = 4

# Duration guard rails (short-form reels only).
_MIN_DURATION_S: int = 5
_MAX_DURATION_S: int = 180
_DEFAULT_DURATION_S: int = 30

# Sampling temperature: high by default so repeated calls surface DISTINCT
# concepts (idea variety is the whole point of SPARK). Clamped before use.
DEFAULT_IDEA_TEMPERATURE: float = 0.9
_MIN_TEMPERATURE: float = 0.0
_MAX_TEMPERATURE: float = 2.0

# The 'suggested_*' enums MUST match what the compose/caption pipeline accepts.
# ``suggested_layout`` -> app.services.reelforge layout ids.
VALID_LAYOUTS: tuple[str, ...] = ("pip", "hook_intro", "split")
DEFAULT_LAYOUT: str = "pip"

# ``suggested_caption_style`` -> captions.presets.CAPTION_STYLE_PRESETS ids.
VALID_CAPTION_STYLES: tuple[str, ...] = (
    "karaoke_yellow",
    "karaoke_green",
    "clean_white",
    "bold_violet",
)
DEFAULT_CAPTION_STYLE: str = "karaoke_yellow"

# Native personas. "auto" lets the model pick the language from the app context.
_SUPPORTED_LANGUAGES: tuple[str, ...] = ("auto", "tr", "en")
VALID_IDEA_LANGUAGES: tuple[str, ...] = ("tr", "en")
DEFAULT_IDEA_LANGUAGE: str = "en"

_REQUIRED_KEYS: tuple[str, ...] = (
    "title",
    "hook",
    "angle",
    "format",
    "script_outline",
    "suggested_layout",
    "suggested_caption_style",
    "language",
    "est_duration_s",
)


# --------------------------------------------------------------------------- #
# Normalization helpers
# --------------------------------------------------------------------------- #
def _normalize_language(language: str) -> str:
    """Map an arbitrary language hint to one of the supported persona codes."""
    value = (language or "").strip().lower()
    if not value:
        return "auto"
    if value in _SUPPORTED_LANGUAGES:
        return value
    if value.startswith("tr") or value.startswith("turk"):
        return "tr"
    if value.startswith("en") or value.startswith("engl"):
        return "en"
    return "auto"


def _clamp_count(count: int) -> int:
    """Clamp a requested idea count into ``[MIN_IDEA_COUNT, MAX_IDEA_COUNT]``."""
    try:
        value = int(count)
    except (TypeError, ValueError):
        return DEFAULT_IDEA_COUNT
    return max(MIN_IDEA_COUNT, min(value, MAX_IDEA_COUNT))


def _clamp_temperature(temperature: float) -> float:
    """Clamp a requested sampling temperature into the supported range."""
    try:
        value = float(temperature)
    except (TypeError, ValueError):
        return DEFAULT_IDEA_TEMPERATURE
    return max(_MIN_TEMPERATURE, min(value, _MAX_TEMPERATURE))


def _coerce_enum(value: object, valid: tuple[str, ...], default: str) -> str:
    """Return ``value`` if it is a recognized id, else the default.

    Invalid / missing enum values are silently defaulted (never raised) so a
    single sloppy field does not throw away an otherwise usable idea.
    """
    candidate = ("" if value is None else str(value)).strip().lower()
    return candidate if candidate in valid else default


def _coerce_language(value: object) -> str:
    """Coerce a per-idea language into one of the shippable codes (tr|en)."""
    normalized = _normalize_language("" if value is None else str(value))
    return normalized if normalized in VALID_IDEA_LANGUAGES else DEFAULT_IDEA_LANGUAGE


def _coerce_duration(value: object) -> int:
    """Coerce/clamp an estimated duration into the short-form range."""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_DURATION_S
    if seconds <= 0:
        return _DEFAULT_DURATION_S
    return max(_MIN_DURATION_S, min(seconds, _MAX_DURATION_S))


def _coerce_outline(raw: object) -> list[str]:
    """Normalize ``script_outline`` into 2-4 non-empty beat strings.

    Raises ``ValueError`` when the outline is not a usable list of beats so the
    caller can retry (an idea with no script is not shootable).
    """
    if not isinstance(raw, list):
        raise ValueError("script_outline must be a list")
    beats = [_clamp_text(beat, _MAX_BEAT_LENGTH) for beat in raw]
    beats = [beat for beat in beats if beat]
    if len(beats) < _MIN_BEATS:
        raise ValueError(
            f"script_outline needs at least {_MIN_BEATS} beats, got {len(beats)}"
        )
    # Too many beats: keep the first _MAX_BEATS rather than discarding the idea.
    return beats[:_MAX_BEATS]


# --------------------------------------------------------------------------- #
# Prompt builder
# --------------------------------------------------------------------------- #
def _language_rule(language: str) -> str:
    """Return the language instruction block for the resolved language."""
    if language == "tr":
        return (
            'Tüm fikirleri (title, hook, angle, format, script_outline) doğal ve '
            'akıcı Türkçe yaz; çeviri gibi durmasın. Her fikrin "language" alanı '
            '"tr" olmalı. Türkçe karakterleri (ş, ç, ı, İ, ö, ü, ğ) doğru kullan.'
        )
    if language == "en":
        return (
            'Write every idea (title, hook, angle, format, script_outline) in '
            'natural, native English. Each idea\'s "language" field must be "en".'
        )
    return (
        "Detect the dominant language of the app context and write EVERY idea "
        "natively in that language (do not translate, do not mix languages). Set "
        'each idea\'s "language" field to "tr" for Turkish or "en" for English.'
    )


def build_ideas_prompt(
    app_context: str,
    audience: str,
    count: int,
    language: str,
) -> str:
    """Build the strict-JSON viral UGC idea-strategist prompt.

    Instructs the model to return exactly ``count`` ready-to-shoot concepts as a
    single minified JSON object ``{"ideas": [...]}`` with the fixed key contract,
    and to write natively in Turkish when ``language`` resolves to ``"tr"``.
    """
    ctx = _clamp_text(app_context, MAX_APP_CONTEXT_LENGTH)
    aud = _clamp_text(audience, MAX_AUDIENCE_LENGTH)
    n = _clamp_count(count)
    lang = _normalize_language(language)

    audience_block = aud if aud else "(not specified — infer a plausible audience)"
    layouts = ", ".join(VALID_LAYOUTS)
    caption_styles = ", ".join(VALID_CAPTION_STYLES)

    prompt = f"""
# Role: Viral UGC Content Strategist

You are a world-class short-form (Reels/TikTok/Shorts) content strategist. You
turn a product/niche description into concrete, ready-to-shoot UGC video concepts
that feel like a real creator's authentic post, not an ad. You know hooks,
retention, pattern interrupts, and native platform trends.

## Goal
Generate exactly {n} DISTINCT viral UGC video concepts for the app/niche below.
Each concept must be immediately shootable by a solo creator with a phone.

## Constraints
1. Respond ONLY with a single valid minified JSON object. No markdown, no code
   fences, no commentary before or after.
2. The top-level object must have exactly one key: "ideas", a JSON array with
   EXACTLY {n} items.
3. Each item in "ideas" must be a JSON object with EXACTLY these keys:
   "title", "hook", "angle", "format", "script_outline", "suggested_layout",
   "suggested_caption_style", "language", "est_duration_s".
4. "title": a short internal label for the idea (at most {_MAX_TITLE_LENGTH} chars).
5. "hook": the scroll-stopping spoken first line — AT MOST 12 WORDS.
6. "angle": one sentence describing the persuasion angle / narrative frame.
7. "format": the shooting format, e.g. "talking head", "screen recording",
   "day-in-the-life", "before/after", "voiceover b-roll".
8. "script_outline": a JSON array of {_MIN_BEATS}-{_MAX_BEATS} short beats (each a
   single plain sentence) describing the reel from hook to payoff, in order.
9. "suggested_layout": exactly one of: {layouts}.
10. "suggested_caption_style": exactly one of: {caption_styles}.
11. "language": exactly "tr" or "en" (see language rule below).
12. "est_duration_s": integer estimated reel length in seconds, between
    {_MIN_DURATION_S} and {_MAX_DURATION_S}.
13. Make the {n} ideas genuinely different from each other — vary the hook style,
    angle, format, layout and caption style. No near-duplicates.
14. {_language_rule(lang)}
15. Sound like a real creator, never like an ad. No emojis, no hashtags.

## Output Example
{{"ideas":[{{"title":"...","hook":"...","angle":"...","format":"talking head","script_outline":["...","...","..."],"suggested_layout":"{DEFAULT_LAYOUT}","suggested_caption_style":"{DEFAULT_CAPTION_STYLE}","language":"{DEFAULT_IDEA_LANGUAGE}","est_duration_s":{_DEFAULT_DURATION_S}}}]}}

## Context
### App / Niche
{ctx}

### Target Audience
{audience_block}
""".strip()
    return prompt


# --------------------------------------------------------------------------- #
# Parsing / validation
# --------------------------------------------------------------------------- #
def _coerce_json(response: str) -> dict:
    """Parse the raw LLM response into a dict, tolerating a wrapping code fence.

    Falls back to extracting the first ``{...}`` object (mirrors
    ``llm._parse_social_metadata``). Raises ``ValueError`` if nothing parses.
    """
    try:
        data = json.loads(_strip_code_fence(response))
    except Exception:
        match = re.search(r"\{.*\}", response or "", re.DOTALL)
        if not match:
            raise ValueError("ideas response is not a JSON object")
        try:
            data = json.loads(match.group())
        except Exception as exc:  # noqa: BLE001 - normalize to a retry signal
            raise ValueError(f"ideas response is not valid JSON: {exc}")

    if not isinstance(data, dict):
        raise ValueError("ideas response is not a JSON object")
    return data


def _parse_single_idea(raw: object) -> dict:
    """Validate and normalize one raw idea object into the shippable shape.

    Raises ``ValueError`` for structurally unusable ideas (not an object,
    missing required keys, empty hook, or an unusable outline). Invalid enum
    values (layout/caption_style/language) and durations are coerced to safe
    defaults rather than raised, so one sloppy field does not lose the idea.
    """
    if not isinstance(raw, dict):
        raise ValueError("idea is not a JSON object")

    missing = [key for key in _REQUIRED_KEYS if key not in raw]
    if missing:
        raise ValueError(f"idea is missing required keys: {missing}")

    title = _clamp_text(raw.get("title", ""), _MAX_TITLE_LENGTH)
    hook = _clamp_text(raw.get("hook", ""), _MAX_HOOK_LENGTH)
    if not hook:
        raise ValueError("idea is missing 'hook'")
    if not title:
        # A hook is enough to shoot from; synthesize a title so the idea survives.
        title = hook

    angle = _clamp_text(raw.get("angle", ""), _MAX_ANGLE_LENGTH)
    fmt = _clamp_text(raw.get("format", ""), _MAX_FORMAT_LENGTH)
    outline = _coerce_outline(raw.get("script_outline"))

    return {
        "title": title,
        "hook": hook,
        "angle": angle,
        "format": fmt,
        "script_outline": outline,
        "suggested_layout": _coerce_enum(
            raw.get("suggested_layout"), VALID_LAYOUTS, DEFAULT_LAYOUT
        ),
        "suggested_caption_style": _coerce_enum(
            raw.get("suggested_caption_style"),
            VALID_CAPTION_STYLES,
            DEFAULT_CAPTION_STYLE,
        ),
        "language": _coerce_language(raw.get("language")),
        "est_duration_s": _coerce_duration(raw.get("est_duration_s")),
    }


def _parse_ideas(response: str, count: int) -> list[dict]:
    """Validate and normalize an ideas LLM response into a list of dicts.

    Strips a wrapping code fence, ``json.loads`` the payload, validates each
    idea (required keys + enum coercion for layout/caption_style), and returns at
    most ``count`` normalized ideas. Raises ``ValueError`` on unusable JSON (no
    object, wrong shape, or zero valid ideas) so the caller can retry.
    """
    data = _coerce_json(response)

    raw_ideas = data.get("ideas")
    if not isinstance(raw_ideas, list):
        raise ValueError("ideas response is missing an 'ideas' array")
    if not raw_ideas:
        raise ValueError("ideas response contains an empty 'ideas' array")

    wanted = _clamp_count(count)
    parsed: list[dict] = []
    for raw in raw_ideas:
        try:
            parsed.append(_parse_single_idea(raw))
        except ValueError as exc:
            # Skip an individual malformed idea; only fail the whole batch if
            # nothing usable survives (checked below).
            logger.warning(f"skipping malformed idea: {exc}")
        if len(parsed) >= wanted:
            break

    if not parsed:
        raise ValueError("ideas response contained no usable ideas")
    return parsed


# --------------------------------------------------------------------------- #
# LLM invocation helper (threads temperature only when supported)
# --------------------------------------------------------------------------- #
def _call_generate_response(prompt: str, app_config, temperature: float) -> str:
    """Invoke ``_generate_response`` threading ``temperature`` only if supported.

    MPT's shared ``llm._generate_response(prompt, app_config=None)`` does not
    (yet) accept a ``temperature`` kwarg. We inspect the *currently bound*
    callable's signature and pass ``temperature`` only when it is accepted — so a
    future/overridden implementation (or a test double) can honor variety, while
    the stock implementation keeps working unchanged. ``app_config`` is passed
    only when set, preserving the existing pass-through identity semantics.
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


# --------------------------------------------------------------------------- #
# Performance bias — SPARK LEARNS from the creator's own winning hooks.
#
# ADDITIVE + SAFE by construction: biasing only ever *appends* a section to the
# base prompt, and only when the creator actually has winning-hook data. When
# there is nothing to inject (no session/user, the performance service is
# unavailable, the query errors, or the creator has logged no outcomes) the
# helpers return ``""`` and the prompt stays BYTE-FOR-BYTE identical to the prior
# ``build_ideas_prompt`` output — no new exception, no new failure mode, and no
# extra LLM cost (the fetch is a cheap owner-scoped DB read, not an LLM call).
# --------------------------------------------------------------------------- #
#: How many of the creator's top-performing hooks to feed back into the prompt.
MAX_WINNING_HOOKS_INJECTED: int = 5
#: Clamp each injected hook so a long stored subject cannot bloat the prompt.
_MAX_WINNING_HOOK_LENGTH: int = 200


def _winning_hooks_block(winners: list[dict]) -> str:
    """Render a creator's top winning hooks into a prompt bias section.

    Returns ``""`` when there is nothing usable to inject, so the caller keeps
    the prompt byte-for-byte identical to the no-data path. Each hook is clamped
    and only the top :data:`MAX_WINNING_HOOKS_INJECTED` are surfaced.
    """
    if not winners:
        return ""
    lines: list[str] = []
    for entry in winners[:MAX_WINNING_HOOKS_INJECTED]:
        if not isinstance(entry, dict):
            continue
        hook = _clamp_text(entry.get("hook", ""), _MAX_WINNING_HOOK_LENGTH)
        if not hook:
            continue
        try:
            score = float(entry.get("win_score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        lines.append(f'- "{hook}" (win score {score:g})')
    if not lines:
        return ""
    joined = "\n".join(lines)
    return (
        "\n\n## Proven Winning Hooks (this creator's own performance data)\n"
        "These hook patterns already earned strong real-world engagement and "
        "watch-through for THIS creator. Bias the new ideas toward the styles, "
        "angles and phrasing that make these convert — echo what works WITHOUT "
        "copying them verbatim:\n"
        f"{joined}"
    )


def _fetch_winning_hooks_block(session, user_id) -> str:
    """Defensively fetch the caller's winning hooks and render a bias block.

    Wrapped so biasing is best-effort: returns ``""`` (→ no prompt change, no new
    failure mode) when biasing is not possible for ANY reason — no session/user,
    the performance service cannot be imported, the query raises, or the creator
    has logged nothing. Never spends LLM tokens.
    """
    if session is None or not user_id:
        return ""
    try:
        from app.services.hook_performance import winning_hooks

        winners = winning_hooks(session, user_id, limit=MAX_WINNING_HOOKS_INJECTED)
        return _winning_hooks_block(winners)
    except Exception as exc:  # noqa: BLE001 - biasing is best-effort; never break ideas
        logger.warning(f"skipping winning-hooks bias: {exc}")
        return ""


# --------------------------------------------------------------------------- #
# Public generator
# --------------------------------------------------------------------------- #
def generate_ideas(
    app_context: str,
    audience: str = "",
    count: int = DEFAULT_IDEA_COUNT,
    language: str = "auto",
    temperature: float = DEFAULT_IDEA_TEMPERATURE,
    app_config=None,
    session=None,
    user_id: str | None = None,
) -> list[dict] | None:
    """Generate ``count`` ready-to-shoot viral UGC video concepts.

    Clamps ``count`` into ``[1, 10]`` and samples at a high ``temperature``
    (default ``0.9``) so repeated calls surface distinct ideas. Retries up to
    ``llm._max_retries`` times on invalid JSON / provider errors. Returns the
    list of parsed idea dicts (see ``_parse_ideas``) or ``None`` if every attempt
    fails — never raises to the caller and never returns raw model text.

    Performance bias (ADDITIVE + SAFE): when BOTH ``session`` and ``user_id`` are
    supplied, the creator's own top winning hooks are fetched via
    :func:`app.services.hook_performance.winning_hooks` and appended to the prompt
    so SPARK re-suggests patterns that actually convert. If either is absent, the
    fetch fails, or the creator has no logged outcomes, the prompt is
    byte-for-byte identical to the prior behaviour and no LLM cost is added.
    """
    ctx = _clamp_text(app_context, MAX_APP_CONTEXT_LENGTH)
    if not ctx:
        logger.error("cannot generate ideas: empty app_context")
        return None

    aud = _clamp_text(audience, MAX_AUDIENCE_LENGTH)
    n = _clamp_count(count)
    lang = _normalize_language(language)
    temp = _clamp_temperature(temperature)
    prompt = build_ideas_prompt(
        app_context=ctx,
        audience=aud,
        count=n,
        language=lang,
    )
    # ADDITIVE: only appends when the creator has winning-hook data; otherwise
    # ``prompt`` is left exactly as ``build_ideas_prompt`` produced it.
    bias_block = _fetch_winning_hooks_block(session, user_id)
    if bias_block:
        prompt = prompt + bias_block
        logger.info("biasing ideas with creator's winning hooks")
    logger.info(
        f"generating ideas: count={n}, language={lang}, temperature={temp}, "
        f"context_len={len(ctx)}"
    )

    for attempt in range(_max_retries):
        response = ""
        try:
            response = _call_generate_response(prompt, app_config, temp)

            # _generate_response never raises; it encodes failures as "Error: ...".
            if isinstance(response, str) and "Error: " in response:
                logger.error(f"failed to generate ideas: {response}")
            else:
                ideas = _parse_ideas(response, n)
                logger.success(f"ideas ready: count={len(ideas)}")
                return ideas
        except ValueError as exc:
            logger.warning(f"invalid ideas json: {exc}")
        except Exception as exc:  # noqa: BLE001 - keep the pipeline alive
            logger.warning(f"failed to generate ideas: {exc}")

        if attempt < _max_retries - 1:
            logger.warning(f"retrying ideas generation... {attempt + 1}")

    logger.error("failed to generate ideas after all retries")
    return None
