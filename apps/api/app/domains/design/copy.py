"""Design copy from the user's prompt + brand kit (LLM when configured, rules otherwise).

The LLM is only asked to shorten and arrange what the user wrote. Any number
(price, percentage, count) in its answer that is not in the prompt or brand
kit is rejected field by field, so a design never states a figure the user did
not give. With no LLM configured (or on timeout) the deterministic rules below
produce usable copy.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Any, Callable

from app.domains.design.layouts import Copy

LLM_TIMEOUT_S = 12.0
HEADLINE_MAX = 70
SUBLINE_MAX = 140
CTA_MAX = 24
BADGE_MAX = 18
POINT_MAX = 70
PROMPT_MAX = 1200

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_OFFER_RE = re.compile(r"(\d{1,3}\s?%\s?(?:off)?|free\s+\w+|\bnew\b)", re.IGNORECASE)

_CTA_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("app store", "download", "ios", "android", "install"), "Download the app"),
    (("game", "play"), "Play now"),
    (("shop", "store", "buy", "sale", "order", "product"), "Shop now"),
    (("book", "appointment", "reserve", "demo", "call"), "Book now"),
    (("sign up", "signup", "join", "waitlist", "register"), "Join now"),
    (("event", "webinar", "launch"), "Save your spot"),
)


def _clean(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0].rstrip(",.;:-")
    return cut or value[:limit]


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM_RE.findall(text or "")}


def rule_copy(prompt: str, brand: dict | None = None) -> Copy:
    """Deterministic copy: first sentence as headline, the rest (or tagline) as subline."""
    brand = brand or {}
    text = _clean(prompt, PROMPT_MAX)
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    headline = _clean(sentences[0].rstrip(".") if sentences else (brand.get("tagline") or brand.get("name") or ""),
                      HEADLINE_MAX)
    rest = " ".join(sentences[1:]) if len(sentences) > 1 else ""
    subline = _clean(rest or brand.get("tagline") or brand.get("description") or "", SUBLINE_MAX)
    if subline.lower() == headline.lower():
        subline = ""
    lower = text.lower()
    cta = "Learn more"
    for needles, label in _CTA_RULES:
        if any(n in lower for n in needles):
            cta = label
            break
    offer = _OFFER_RE.search(text)
    badge = _clean(offer.group(1), BADGE_MAX) if offer else ""
    points = tuple(_clean(s.rstrip("."), POINT_MAX) for s in sentences[1:4])
    if not points and brand.get("offer"):
        points = (_clean(brand.get("offer"), POINT_MAX),)
    return Copy(headline=headline or "Your headline here", subline=subline, cta=cta, badge=badge, points=points)


def build_prompt(prompt: str, brand: dict | None, preset: str) -> str:
    brand = brand or {}
    facts = {k: brand.get(k) for k in ("name", "tagline", "offer", "audience", "voice") if brand.get(k)}
    return (
        "You write short copy for a static social media design.\n"
        f"Format: {preset}. Brand facts (JSON): {json.dumps(facts, ensure_ascii=False)}\n"
        f"Request: {_clean(prompt, PROMPT_MAX)}\n"
        "Rules: use only facts from the request and brand facts; never invent numbers, prices, "
        "discounts, ratings or testimonials; no emoji; plain text.\n"
        'Reply with JSON only: {"headline": "<= 60 chars", "subline": "<= 120 chars", '
        '"cta": "<= 20 chars", "badge": "<= 16 chars or empty", "points": ["up to 3 items, <= 60 chars each"]}'
    )


def _parse(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def _safe(value: Any, limit: int, allowed: set[str]) -> str:
    text = _EMOJI_RE.sub("", _clean(value, limit)).strip()
    return text if text and _numbers(text) <= allowed else ""


def merge_llm(data: dict, fallback: Copy, allowed: set[str]) -> tuple[Copy, bool]:
    headline = _safe(data.get("headline"), HEADLINE_MAX, allowed)
    subline = _safe(data.get("subline"), SUBLINE_MAX, allowed)
    cta = _safe(data.get("cta"), CTA_MAX, allowed)
    badge = _safe(data.get("badge"), BADGE_MAX, allowed)
    raw_points = data.get("points") if isinstance(data.get("points"), list) else []
    points = tuple(p for p in (_safe(x, POINT_MAX, allowed) for x in raw_points[:3]) if p)
    used = bool(headline)
    return Copy(
        headline=headline or fallback.headline,
        subline=subline or fallback.subline,
        cta=cta or fallback.cta,
        badge=badge if headline else fallback.badge,
        points=points or fallback.points,
    ), used


def _default_generate(prompt: str) -> str:
    from app.services.llm import _generate_response

    return _generate_response(prompt)


def design_copy(prompt: str, brand: dict | None, preset: str, *, use_llm: bool = True,
                generate: Callable[[str], str] | None = None, timeout_s: float = LLM_TIMEOUT_S) -> tuple[Copy, str]:
    """Return ``(copy, source)`` where source is ``"llm"`` or ``"rules"``. Never raises."""
    fallback = rule_copy(prompt, brand)
    if not use_llm:
        return fallback, "rules"
    allowed = _numbers(prompt) | _numbers(json.dumps(brand or {}, ensure_ascii=False))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        raw = pool.submit(generate or _default_generate, build_prompt(prompt, brand, preset)).result(timeout=timeout_s)
    except Exception:  # noqa: BLE001 - no LLM configured / timeout / provider error
        raw = ""
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    copy, used = merge_llm(_parse(raw), fallback, allowed)
    return copy, "llm" if used else "rules"


__all__ = ["design_copy", "merge_llm", "rule_copy"]
