"""Exact promo-text / subtitle rewrite suggestions for the App Store audit.

Routed through Railyard Relay only (same OpenAI-compatible
``${RELAY_URL}/openai/v1/chat/completions`` surface the web app's
``/api/tools/generate`` route calls), with a deterministic, offline fallback
when Relay is not configured or the call fails. Never invents features: the
prompt is built strictly from the listing's own title/description/genre, and
the fallback is a plain template over the same facts.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable, Optional

from app.domains.railyard.config import RailyardEnv, get_relay_config

PROMO_MAX = 170
SUBTITLE_MAX = 30
DEFAULT_MODEL = "tensorzero::model_name::anthropic::claude-haiku-4-5"
_TIMEOUT_S = 20.0

ChatFn = Callable[[str, str, str, Optional[str]], str]


@dataclass(frozen=True)
class Rewrite:
    promo_text: str
    subtitle: str
    source: str  # "relay" | "fallback"


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().strip('"\'')
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;: ")


def _first_benefit_sentence(description: str) -> str:
    sentence = re.split(r"(?<=[.!?])\s+|\n+", (description or "").strip(), maxsplit=1)[0]
    return sentence or description or ""


def fallback_rewrite(title: str, description: str, genre: str) -> Rewrite:
    """Deterministic rewrite built only from the listing's own facts."""
    lede = _first_benefit_sentence(description)
    promo = _clip(lede, PROMO_MAX) or _clip(f"{title} — {genre}".strip(" —"), PROMO_MAX)
    # Prefer the part after a colon in the title as a subtitle seed (e.g. "CalDesk AI: Calorie Counter").
    after_colon = title.split(":", 1)[1].strip() if ":" in title else ""
    subtitle_seed = after_colon or genre or title
    subtitle = _clip(subtitle_seed, SUBTITLE_MAX)
    return Rewrite(promo_text=promo, subtitle=subtitle, source="fallback")


def _build_prompt(title: str, description: str, genre: str, rating: float | None) -> str:
    facts = [
        f"App name: {title}",
        f"Category: {genre}" if genre else "",
        f"Rating: {rating}/5" if rating else "",
        f"Description (first 600 characters): {description[:600]}",
    ]
    return "\n".join(
        [
            "You write exact App Store metadata rewrites. Use ONLY the facts given below.",
            "Never invent features, numbers, awards or claims not present in the facts.",
            f"Write a promo text (at most {PROMO_MAX} characters) that leads with the single most concrete benefit in the facts.",
            f"Write a subtitle (at most {SUBTITLE_MAX} characters) that states the outcome, not just the brand name.",
            "No emoji. No quotes around the output. Plain English.",
            'Return ONLY JSON: {"promo_text":"...","subtitle":"..."}',
            "",
            "<facts>",
            "\n".join(f for f in facts if f),
            "</facts>",
        ]
    )


def _default_chat(prompt: str, base_url: str, api_key: str, model: str | None) -> str:
    import httpx

    response = httpx.post(
        f"{base_url}/chat/completions",
        json={
            "model": model or DEFAULT_MODEL,
            "max_tokens": 300,
            "temperature": 0.6,
            "messages": [{"role": "user", "content": prompt}],
        },
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    data = response.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def _parse(text: str) -> tuple[str, str] | None:
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    promo = str(data.get("promo_text") or "").strip()
    subtitle = str(data.get("subtitle") or "").strip()
    if not promo or not subtitle:
        return None
    return promo, subtitle


def _relay_env(env: Optional[RailyardEnv]) -> RailyardEnv:
    """Accept the ``RAILYARD_RELAY_*`` names the box env uses (same fallback as
    ``app.core.moderation_safeguard``) without changing the shared Railyard
    config other features read."""
    source = env if env is not None else os.environ
    return {
        **source,
        "RELAY_URL": source.get("RELAY_URL") or source.get("RAILYARD_RELAY_URL") or "",
        "RELAY_API_KEY": source.get("RELAY_API_KEY") or source.get("RAILYARD_RELAY_API_KEY") or "",
    }


def generate_rewrite(
    title: str,
    description: str,
    genre: str,
    rating: float | None = None,
    *,
    env: Optional[RailyardEnv] = None,
    chat: ChatFn = _default_chat,
) -> Rewrite:
    """Relay-backed rewrite when configured, else the deterministic fallback.

    Any Relay failure (not configured, network error, unusable output) falls
    back silently to :func:`fallback_rewrite` — the audit always returns a
    usable suggestion.
    """
    config = get_relay_config(_relay_env(env))
    if not config.configured or not config.openai_base_url:
        return fallback_rewrite(title, description, genre)
    prompt = _build_prompt(title, description, genre, rating)
    try:
        text = chat(prompt, config.openai_base_url, config.api_key or "", None)
    except Exception:  # noqa: BLE001 - any Relay failure degrades to the fallback
        return fallback_rewrite(title, description, genre)
    parsed = _parse(text)
    if parsed is None:
        return fallback_rewrite(title, description, genre)
    promo, subtitle = parsed
    return Rewrite(promo_text=_clip(promo, PROMO_MAX), subtitle=_clip(subtitle, SUBTITLE_MAX), source="relay")


__all__ = ["PROMO_MAX", "SUBTITLE_MAX", "Rewrite", "fallback_rewrite", "generate_rewrite"]
