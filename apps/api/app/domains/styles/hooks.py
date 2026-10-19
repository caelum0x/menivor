"""Write opening hooks for a pasted link in a style's hook family.

Link runs write their own scripts (the page's real description and features
are the body), so the only creative line is the hook. For meme formats ("you
met me at a very ___ time in my life", "Nobody: / Me:", "things I wish I knew
before ___", "Before: / After:") and the classic angles, this asks the LLM for
ONE hook per requested format, grounded ONLY in the page content, validates the
shape with :func:`hook_matches_style`, and falls back to a deterministic
template hook per format when the model misses. Output is always one hook per
format, in the requested order.

Pure apart from the injectable ``generate`` callable (the default uses the same
LLM dispatch as the script stage).
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from loguru import logger

from app.domains.experiments.hook_styles import (
    directive_for,
    hook_matches_style,
    normalize_hook_style,
    script_language,
    template_hook,
)

MAX_HOOK_CHARS = 140
MAX_FORMATS = 3
_MAX_CONTEXT_CHARS = 1200
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _clean(text: object, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def page_context(title: str, description: str, features: list[str] | tuple[str, ...]) -> str:
    """Compact, bounded page facts for the prompt (never the raw HTML)."""
    lines = [f"Product: {_clean(title, 120) or 'unknown'}"]
    if description:
        lines.append(f"What it does: {_clean(description, 400)}")
    for feature in list(features or [])[:5]:
        item = _clean(feature, 140)
        if item:
            lines.append(f"- {item}")
    return "\n".join(lines)[:_MAX_CONTEXT_CHARS]


_TURKISH_HINT = re.compile(r"\s*\((?:in )?Turkish[^)]*\)|\s*In Turkish[^.]*\.", re.IGNORECASE)


def directive_in(fmt: str, language: str) -> str:
    """The format's directive; English runs never see the Turkish hints."""
    text = directive_for(fmt)
    return text if language == "tr" else _TURKISH_HINT.sub("", text)


def build_prompt(context: str, formats: list[str], language: str) -> str:
    lang = "Turkish" if language == "tr" else "English"
    rules = "\n".join(f'- "{fmt}": {directive_in(fmt, language)}' for fmt in formats)
    keys = ", ".join(f'"{fmt}"' for fmt in formats)
    return (
        "You write the FIRST on-screen line of a short vertical video ad.\n"
        f"Write in {lang}. Use ONLY the facts below; never invent numbers, awards, "
        "reviews, customers or claims, and never name an audience (who it is for) that the "
        "facts do not name. No emoji, no hashtags, no quotes around the line. "
        f"Each hook is at most {MAX_HOOK_CHARS} characters.\n\n"
        f"## Page facts\n{context}\n\n"
        f"## Formats (one hook each)\n{rules}\n\n"
        f"Return ONLY a JSON object with exactly these keys: {keys}. "
        "Each value is the hook text."
    )


def parse_hooks(response: str) -> dict[str, str]:
    """Parse the model's JSON object into ``{format: hook}`` (tolerant)."""
    match = _JSON_BLOCK.search(str(response or ""))
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        text = _clean(value, MAX_HOOK_CHARS * 2)
        if text:
            out[str(key).strip().lower()] = text
    return out


def _default_generate(prompt: str) -> str:
    from app.services.script import ugc

    return ugc._call_generate_response(prompt, None, ugc.DEFAULT_UGC_TEMPERATURE)


def normalize_formats(formats: list[Any] | tuple[Any, ...]) -> list[str]:
    """Canonical, de-duplicated formats (max 3); raises on an unknown id."""
    clean: list[str] = []
    for fmt in formats or []:
        key = normalize_hook_style(fmt)
        if key and key not in clean:
            clean.append(key)
    return clean[:MAX_FORMATS]


def write_hooks(
    *,
    title: str,
    description: str = "",
    features: list[str] | tuple[str, ...] = (),
    formats: list[str] | tuple[str, ...],
    language: str = "auto",
    generate: Callable[[str], str] | None = None,
    attempts: int = 2,
) -> list[dict[str, str]]:
    """One ``{hook_style, hook, source}`` per format (``model`` or ``template``)."""
    wanted = normalize_formats(list(formats))
    if not wanted:
        return []
    lang = script_language(language, f"{title} {description}")
    prompt = build_prompt(page_context(title, description, list(features)), wanted, lang)
    call = generate or _default_generate

    accepted: dict[str, str] = {}
    for attempt in range(max(1, attempts)):
        missing = [fmt for fmt in wanted if fmt not in accepted]
        if not missing:
            break
        try:
            response = call(prompt if attempt == 0 else build_prompt(
                page_context(title, description, list(features)), missing, lang))
        except Exception as exc:  # noqa: BLE001 - fall back to templates
            logger.warning(f"style hooks: generation failed: {type(exc).__name__}: {exc}")
            continue
        if isinstance(response, str) and response.startswith("Error: "):
            logger.warning("style hooks: provider returned an error string")
            continue
        for fmt, text in parse_hooks(response).items():
            if fmt in missing and len(text) <= MAX_HOOK_CHARS and hook_matches_style(text, fmt):
                accepted[fmt] = text

    subject = _clean(title, 80) or "this"
    return [
        {"hook_style": fmt, "hook": accepted[fmt], "source": "model"}
        if fmt in accepted
        else {"hook_style": fmt, "hook": template_hook(fmt, subject, lang), "source": "template"}
        for fmt in wanted
    ]


__all__ = [
    "MAX_FORMATS",
    "MAX_HOOK_CHARS",
    "build_prompt",
    "normalize_formats",
    "page_context",
    "parse_hooks",
    "write_hooks",
]
