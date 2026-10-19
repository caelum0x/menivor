"""Opening-hook angles for generated reel scripts.

A one-flow run fans one topic out into N variants that share the subject and
differ in the first line. Sampling temperature alone does not guarantee that:
the stock LLM dispatch ignores ``temperature`` and a model happily writes the
same kind of opener three times. Each variant therefore gets a distinct
``hook_style``; the script stage asks the model for that angle, checks the
returned hook actually has the angle's shape, retries, and as a last resort
swaps in a deterministic hook of that angle. Two variants with different styles
can then never open with the same kind of line.

Pure module (no DB, no network). The LLM call itself lives in
:func:`generate_styled_script`, which reuses the UGC script prompt and parser.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from loguru import logger

HOOK_STYLES: tuple[str, ...] = ("pov", "question", "nobody_tells_you", "stat", "story")
"""The default angles, in the rotation order used for multi-variant runs."""

MEME_HOOK_STYLES: tuple[str, ...] = (
    "met_me_at",
    "nobody_me",
    "wish_i_knew",
    "before_after",
    "tell_me_without",
    "day_in_life",
)
"""Short-form meme text-hook structures. Only the STRUCTURE is borrowed (a text
pattern everyone recognizes); the words are written for the creator's own
product. Opt-in via an explicit ``hook_style`` or a style's hook family; never
part of the default rotation."""

ALL_HOOK_STYLES: tuple[str, ...] = HOOK_STYLES + MEME_HOOK_STYLES
"""Every accepted ``hook_style`` id."""

_MAX_TEMPLATE_SUBJECT = 80
_TURKISH_CHARS = re.compile(r"[çğıöşüİĞŞÇÖÜ]")

# What the model is asked to do for each angle. The stat angle forbids invented
# figures: a made-up statistic in an ad is a false claim, not a hook.
_DIRECTIVES: dict[str, str] = {
    "pov": (
        'Open with a POV hook. The hook MUST start with "POV:" and put the viewer '
        "inside a specific, relatable moment about the subject."
    ),
    "question": (
        "Open with a question hook. The hook MUST be a single direct question to "
        'the viewer that ends with "?" and that the rest of the script answers.'
    ),
    "nobody_tells_you": (
        "Open with a what-nobody-tells-you hook. The hook MUST promise an "
        'overlooked truth about the subject and contain the word "nobody" '
        '(Turkish: "kimse").'
    ),
    "stat": (
        "Open with a number hook. The hook MUST contain one specific number "
        "(written as digits) that is genuinely true for the subject: a well-known "
        "fact, a time span, a count or a step count. NEVER invent statistics, "
        "percentages, studies or survey results."
    ),
    "story": (
        "Open with a story hook. The hook MUST start a short first-person story "
        "(a moment, a mistake, a turning point) in a plain statement, not a "
        'question, and must not start with "POV".'
    ),
    "met_me_at": (
        'Open with the meme hook structure "You met me at a very ___ time in my '
        'life." The hook MUST contain "met me at a very" (in Turkish use the '
        'natural equivalent with "tanıştın") and fill the blank with ONE funny, '
        "relatable adjective tied to the problem the subject solves."
    ),
    "nobody_me": (
        'Open with the "Nobody: / Me:" meme hook. The hook MUST be two short '
        'parts: "Nobody:" then "Me:" and an over-the-top, relatable action '
        "related to the subject. In Turkish use \"Kimse:\" and \"Ben:\" instead."
    ),
    "wish_i_knew": (
        'Open with the "things I wish I knew before ___" hook. The hook MUST '
        'contain "wish I knew" (in Turkish, "keşke ... bilseydim") and name the '
        "specific situation the subject is for."
    ),
    "before_after": (
        'Open with a before/after hook shaped exactly like "Before: <problem>. '
        'After: <result>." (in Turkish, "Önce: ... Sonra: ..."), two short, '
        "concrete halves contrasting life without and with the subject. Use only "
        "the output language, never both. Never invent numbers."
    ),
    "tell_me_without": (
        'Open with the "Tell me you ___ without telling me you ___" meme hook. '
        'The hook MUST contain "without telling me" (in Turkish, "söylemeden") '
        "and name who the subject is for in a playful, specific way."
    ),
    "day_in_life": (
        'Open with a "day in the life" hook. The hook MUST contain "day in the '
        'life" (in Turkish, "bir günü") and name the specific person the subject '
        "helps (a founder, a creator, a developer ...)."
    ),
}

_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "pov": "POV: you finally figured out {s}.",
        "question": "What would change if you got {s} right?",
        "nobody_tells_you": "Here is what nobody tells you about {s}.",
        "stat": "One number changes how you see {s}.",
        "story": "Let me tell you a quick story about {s}.",
        "met_me_at": "You met me at a very confusing time with {s}.",
        "nobody_me": "Nobody: / Me: explaining {s} to everyone I know.",
        "wish_i_knew": "Things I wish I knew before trying {s}.",
        "before_after": "Before {s}: chaos. After: it just works.",
        "tell_me_without": "Tell me you need {s} without telling me you need {s}.",
        "day_in_life": "A day in the life of someone who finally tried {s}.",
    },
    "tr": {
        "pov": "POV: sonunda {s} konusunu çözdün.",
        "question": "{s} konusunu doğru yapsan ne değişirdi?",
        "nobody_tells_you": "{s} hakkında kimsenin söylemediği şey şu.",
        "stat": "Tek bir rakam {s} konusuna bakışını değiştirir.",
        "story": "Sana {s} hakkında kısa bir hikaye anlatayım.",
        "met_me_at": "Benimle {s} konusunda hayatımın çok karışık bir döneminde tanıştın.",
        "nobody_me": "Kimse: / Ben: herkese {s} anlatırken.",
        "wish_i_knew": "Keşke {s} denemeden önce bilseydim dediğim şeyler.",
        "before_after": "{s} öncesi: kaos. Sonrası: her şey yolunda.",
        "tell_me_without": "{s} lazım olduğunu söylemeden bana {s} lazım de.",
        "day_in_life": "Sonunda {s} deneyen birinin bir günü.",
    },
}

LABELS: dict[str, str] = {
    "pov": "POV hook",
    "question": "Question hook",
    "nobody_tells_you": "What-nobody-tells-you hook",
    "stat": "Number hook",
    "story": "Story hook",
    "met_me_at": "You-met-me-at-a-very hook",
    "nobody_me": "Nobody / me hook",
    "wish_i_knew": "Wish-I-knew hook",
    "before_after": "Before / after hook",
    "tell_me_without": "Tell-me-without-telling-me hook",
    "day_in_life": "Day-in-the-life hook",
}


class HookStyleError(ValueError):
    """An unknown hook style was requested."""


def normalize_hook_style(value: Any) -> str:
    """Return the canonical style id, ``""`` for none; raise on an unknown id."""
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        return ""
    if text not in ALL_HOOK_STYLES:
        raise HookStyleError(
            f"unknown hook_style {value!r} (allowed: {', '.join(ALL_HOOK_STYLES)})"
        )
    return text


def rotate_hook_styles(count: int, first: str = "") -> list[str]:
    """``count`` distinct styles, starting with ``first`` when one is given.

    ``count`` is capped at the number of styles, so every returned style is
    unique. Raises :class:`HookStyleError` for an unknown ``first``.
    """
    lead = normalize_hook_style(first)
    order = ([lead] if lead else []) + [s for s in HOOK_STYLES if s != lead]
    return order[: max(0, min(int(count), len(order)))]


def rotate_family(count: int, family: tuple[str, ...] | list[str]) -> list[str]:
    """``count`` styles cycling through ``family`` (a style's hook family).

    Unlike :func:`rotate_hook_styles` a family may be shorter than ``count``
    (a POV-only style opens every variant with POV); the model still writes a
    different line per variant. Unknown ids raise :class:`HookStyleError`; an
    empty family returns ``[]`` (the caller falls back to the default rotation).
    """
    clean = [normalize_hook_style(style) for style in family if str(style or "").strip()]
    if not clean:
        return []
    total = max(0, int(count))
    return [clean[index % len(clean)] for index in range(total)]


def script_language(language: str, subject: str) -> str:
    """``tr`` or ``en`` for template hooks (``auto`` inspects the subject)."""
    lang = str(language or "").strip().lower()
    if lang.startswith("tr"):
        return "tr"
    if lang.startswith("en"):
        return "en"
    return "tr" if _TURKISH_CHARS.search(subject or "") else "en"


def directive_for(style: str) -> str:
    """The prompt instruction for ``style`` (``""`` when no style)."""
    return _DIRECTIVES.get(normalize_hook_style(style), "")


def hook_matches_style(hook: str, style: str) -> bool:
    """Whether ``hook`` has the recognizable shape of ``style``."""
    text = str(hook or "").strip()
    if not text:
        return False
    lowered = text.lower()
    key = normalize_hook_style(style)
    if key == "pov":
        return lowered.startswith("pov")
    if key == "question":
        return text.rstrip("\"'”’ ").endswith("?")
    if key == "nobody_tells_you":
        return any(word in lowered for word in ("nobody", "no one", "kimse"))
    if key == "stat":
        return bool(re.search(r"\d", text))
    if key == "story":
        return not lowered.startswith("pov") and not text.rstrip().endswith("?")
    if key == "met_me_at":
        return "met me at a" in lowered or ("tanıştın" in lowered and "dönem" in lowered)
    if key == "nobody_me":
        return ("nobody" in lowered and "me:" in lowered) or ("kimse" in lowered and "ben:" in lowered)
    if key == "wish_i_knew":
        return "wish i knew" in lowered or ("keşke" in lowered and "bil" in lowered)
    if key == "before_after":
        return ("before" in lowered and "after" in lowered) or ("önce" in lowered and "sonra" in lowered)
    if key == "tell_me_without":
        return "without telling me" in lowered or "söylemeden" in lowered
    if key == "day_in_life":
        return "day in the life" in lowered or "bir günü" in lowered
    return True


def _template_subject(subject: str) -> str:
    clean = re.sub(r"\s+", " ", str(subject or "")).strip().rstrip(".!?…").strip()
    if len(clean) > _MAX_TEMPLATE_SUBJECT:
        cut = clean[:_MAX_TEMPLATE_SUBJECT]
        space = cut.rfind(" ")
        clean = cut[:space] if space > _MAX_TEMPLATE_SUBJECT * 0.6 else cut
    if len(clean) > 1 and clean[0].isupper() and clean[1].islower():
        clean = clean[0].lower() + clean[1:]
    return clean or "this"


def template_hook(style: str, subject: str, language: str) -> str:
    """A deterministic hook of ``style`` about ``subject``."""
    key = normalize_hook_style(style) or "nobody_tells_you"
    lang = script_language(language, subject)
    line = _TEMPLATES[lang][key].format(s=_template_subject(subject))
    return line[0].upper() + line[1:]


def styled_prompt(base_prompt: str, style: str) -> str:
    """Append the required-angle section to a UGC script prompt."""
    directive = directive_for(style)
    if not directive:
        return base_prompt
    return (
        f"{base_prompt}\n\n## Opening hook angle (REQUIRED)\n{directive}\n"
        "The rest of the script keeps the same subject and pacing rules."
    )


def _rebuild(script: dict, hook: str) -> dict:
    segments = list(script.get("segments") or [])
    cta = str(script.get("cta") or "")
    full_text = "\n\n".join([hook, *segments, cta]) if cta else "\n\n".join([hook, *segments])
    return {**script, "hook": hook, "full_text": full_text}


def generate_styled_script(
    *,
    video_subject: str,
    language: str,
    target_duration_s: int,
    hook_style: str,
    generate: Callable[[str], str] | None = None,
    attempts: int | None = None,
) -> dict | None:
    """Generate a UGC script whose hook has ``hook_style``'s shape.

    Uses the UGC prompt with an extra required-angle section. A response whose
    hook does not match the angle is retried; when every attempt misses the
    angle, the last valid script is kept and only its hook line is replaced with
    :func:`template_hook`. Returns ``None`` only when no attempt produced a
    parseable script (the caller fails the stage, as for an unstyled script).
    """
    from app.services.script import ugc

    style = normalize_hook_style(hook_style)
    base = ugc.build_ugc_script_prompt(
        video_subject=video_subject,
        language=language,
        target_duration_s=target_duration_s,
    )
    prompt = styled_prompt(base, style)
    call = generate or (
        lambda p: ugc._call_generate_response(p, None, ugc.DEFAULT_UGC_TEMPERATURE)
    )
    tries = max(1, int(attempts if attempts is not None else ugc._max_retries))

    last_valid: dict | None = None
    for attempt in range(tries):
        try:
            response = call(prompt)
            if isinstance(response, str) and "Error: " in response:
                logger.error(f"styled script generation failed: {response}")
                continue
            script = ugc._parse_ugc_script(response)
        except ValueError as exc:
            logger.warning(f"invalid styled ugc script json: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - keep the pipeline alive
            logger.warning(f"styled ugc script generation error: {exc}")
            continue
        last_valid = script
        if hook_matches_style(script["hook"], style):
            return {**script, "hook_style": style, "hook_source": "model"}
        logger.info(
            f"hook {script['hook']!r} does not match style {style!r} "
            f"(attempt {attempt + 1}/{tries})"
        )

    if last_valid is None:
        return None
    hook = template_hook(style, video_subject, language)
    logger.warning(f"model missed hook style {style!r}; using template hook")
    return {**_rebuild(last_valid, hook), "hook_style": style, "hook_source": "template"}


__all__ = [
    "ALL_HOOK_STYLES",
    "HOOK_STYLES",
    "MEME_HOOK_STYLES",
    "rotate_family",
    "LABELS",
    "HookStyleError",
    "directive_for",
    "generate_styled_script",
    "hook_matches_style",
    "normalize_hook_style",
    "rotate_hook_styles",
    "script_language",
    "styled_prompt",
    "template_hook",
]
