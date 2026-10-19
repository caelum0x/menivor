"""LLM-powered script translation for ReelForge multi-language dubbing.

Given a finished reel's source UGC script, this module produces the *same*
script rewritten in a target language so the normal pipeline (TTS via the
ElevenLabs multilingual model, captions from the new timestamps, avatar,
compose) can be re-run per language. The N dubbed jobs are grouped under one
``batch_id`` and surface in the existing batch-review UI.

It plugs into MPT's single LLM dispatch choke point
``app.services.llm._generate_response(prompt, app_config=None)`` and reuses its
helpers (``_strip_code_fence``, ``_clamp_text``, the ``"Error: " in response``
guard) rather than reimplementing any provider code.

Only the languages whose glyphs are covered by the bundled fonts are supported:
``en, tr, es, fr, de, pt, it``. Translation is intentionally *not* literal — the
model is asked to preserve the spoken UGC tone, the scroll-stopping hook and the
CTA while phrasing everything the way a native creator would actually say it.

All external-I/O failures return ``None`` instead of crashing the pipeline,
mirroring MPT's ``generate_*`` conventions.
"""

from __future__ import annotations

import inspect
from typing import Optional

from loguru import logger

from app.services.llm import (
    _clamp_text,
    _generate_response,
    _strip_code_fence,
)

# --------------------------------------------------------------------------- #
# Supported languages (bundled fonts cover exactly these glyph sets)
# --------------------------------------------------------------------------- #
# Ordered list of {code, name}. ``en`` is first because it is the most common
# source language; the rest follow the Latin-script languages the fonts cover.
SUPPORTED_DUB_LANGUAGES: list[dict[str, str]] = [
    {"code": "en", "name": "English"},
    {"code": "tr", "name": "Turkish"},
    {"code": "es", "name": "Spanish"},
    {"code": "fr", "name": "French"},
    {"code": "de", "name": "German"},
    {"code": "pt", "name": "Portuguese"},
    {"code": "it", "name": "Italian"},
]

# Fast lookup: normalized code -> human-readable language name.
_SUPPORTED_BY_CODE: dict[str, str] = {
    entry["code"]: entry["name"] for entry in SUPPORTED_DUB_LANGUAGES
}

# Guard rail so a pathological source script cannot balloon the prompt.
MAX_TRANSLATE_SCRIPT_LENGTH: int = 8000


def _normalize_code(code: str) -> str:
    """Normalize a language code to its bare, lower-cased primary subtag.

    Accepts region/script variants such as ``"pt-BR"``, ``"EN_US"`` or
    ``" fr "`` and reduces them to the two-letter primary subtag (``"pt"``,
    ``"en"``, ``"fr"``). Non-string input yields an empty string so callers can
    treat it as unsupported rather than crashing.
    """
    if not isinstance(code, str):
        return ""
    token = code.strip().lower()
    if not token:
        return ""
    # Split on the common BCP-47 / locale separators and keep the primary subtag.
    for separator in ("-", "_", " "):
        token = token.split(separator, 1)[0]
    return token


def is_supported_language(code: str) -> bool:
    """Return ``True`` if ``code`` names a language the fonts/TTS can dub.

    Region variants collapse to their primary subtag, so ``"pt-BR"`` and
    ``"PT"`` both resolve to Portuguese. Any non-string or unknown value returns
    ``False``.
    """
    return _normalize_code(code) in _SUPPORTED_BY_CODE


def language_name(code: str) -> Optional[str]:
    """Return the human-readable language name for ``code`` (or ``None``)."""
    return _SUPPORTED_BY_CODE.get(_normalize_code(code))


def build_translate_prompt(script: str, language_name_: str) -> str:
    """Build the translation prompt for a spoken UGC script.

    The prompt insists on a *native, natural* rendering (not a literal, word-for
    -word translation) while preserving the hook, tone and CTA — and on returning
    ONLY the translated text so the caller does not have to strip commentary.
    """
    return (
        "# Role: Native UGC Script Localizer\n\n"
        f"Rewrite the short-form UGC video script below in {language_name_}.\n\n"
        "## Rules:\n"
        f"1. Write the way a native {language_name_} creator would actually speak "
        "- natural, idiomatic phrasing, NOT a literal word-for-word translation.\n"
        "2. Preserve the original tone, energy and pacing. Keep it short and "
        "punchy - this is spoken, not written.\n"
        "3. Keep the scroll-stopping hook as a strong hook, and keep the "
        "call-to-action (CTA) as a compelling CTA in the target language.\n"
        "4. Preserve the paragraph/line structure so the timings still line up.\n"
        "5. Do NOT add, remove or explain anything. No preamble, no notes, no "
        "quotes, no markdown, no code fences.\n"
        f"6. Respond with ONLY the {language_name_} script text, nothing else.\n\n"
        "## Source script:\n"
        f"{script}"
    )


def _call_generate_response(prompt: str, app_config) -> str:
    """Invoke ``_generate_response`` passing ``app_config`` only when supported.

    MPT's shared ``llm._generate_response(prompt, app_config=None)`` is the
    single dispatch choke point. We inspect the *currently bound* callable's
    signature so a test double that only accepts ``(prompt)`` still works, while
    the stock implementation receives the config snapshot unchanged.
    """
    kwargs: dict = {}
    if app_config is not None:
        try:
            params = inspect.signature(_generate_response).parameters
        except (TypeError, ValueError):  # pragma: no cover - defensive
            params = {}
        if "app_config" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            kwargs["app_config"] = app_config
    return _generate_response(prompt, **kwargs)


def _clean_translation(response: object) -> str:
    """Return the usable translated text from a raw LLM response.

    Strips a wrapping markdown code fence (Claude/Gemini often add one even when
    asked not to) and surrounding whitespace/quotes. Returns ``""`` for empty,
    non-string or provider-error responses so the caller can retry / fail.
    """
    if not isinstance(response, str):
        return ""
    # ``_generate_response`` never raises; it encodes failures as "Error: ...".
    if "Error: " in response:
        return ""
    text = _strip_code_fence(response).strip()
    # Some models wrap the whole answer in matching quotes - unwrap once.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    return text


def translate_script(
    script: str,
    target_language: str,
    app_config=None,
) -> Optional[str]:
    """Translate a UGC reel script into ``target_language``.

    Prompts ``llm._generate_response`` to rewrite ``script`` natively in the
    target language, preserving tone, hook and CTA (see ``build_translate_prompt``),
    and returns ONLY the translated text with any wrapping code fence stripped.

    Retries once if the model returns an empty response. Returns ``None`` if the
    input is empty/blank, the language is unsupported, or every attempt fails --
    never raises to the caller.
    """
    name = language_name(target_language)
    if name is None:
        logger.error(
            f"cannot translate: unsupported target language {target_language!r}"
        )
        return None

    source = _clamp_text(script, MAX_TRANSLATE_SCRIPT_LENGTH)
    if not source:
        logger.error("cannot translate: empty script")
        return None

    prompt = build_translate_prompt(source, name)
    logger.info(
        f"translating script -> {name} ({_normalize_code(target_language)}), "
        f"source_len={len(source)}"
    )

    # One initial attempt plus one retry on an empty/failed response.
    for attempt in range(2):
        try:
            response = _call_generate_response(prompt, app_config)
            translated = _clean_translation(response)
            if translated:
                logger.success(
                    f"translation ready: {name}, chars={len(translated)}"
                )
                return translated
            logger.warning(
                f"empty translation for {name} (attempt {attempt + 1})"
            )
        except Exception as exc:  # noqa: BLE001 - keep the pipeline alive
            logger.warning(f"translation attempt {attempt + 1} failed: {exc}")

    logger.error(f"failed to translate script to {name} after retries")
    return None
