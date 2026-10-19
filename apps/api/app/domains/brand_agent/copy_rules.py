"""Brand Agent copy rules: the system prompt and the "indie" audience denylist.

Owner rule (2026-09-28, ``policy/copy-denylist.json`` rule ``indie-audience``):
never call an audience "indie". Say founders, early-stage founders, small teams,
app studios or developers. The agent applies a stricter version of the policy
rule: "Indie Hackers" may stay only where it names the site ("on Indie Hackers",
``indiehackers.com``); "indie hackers" as an audience label is a violation.

Every agent reply and every brand-memory write passes through :func:`scrub`, so
model output that slips (the Arcads demo said "indie hackers") never reaches the
user or the Brain.
"""

from __future__ import annotations

import re
from typing import Any

_WORD_RE = re.compile(r"(?<![\w.#/-])#?indie(?:hackers?|s)?\b", re.IGNORECASE)
#: "Indie Hackers" naming the site (preceded by a preposition) or its domain.
_SITE_RE = re.compile(
    r"\b(?:on|at|via|from|to|in)\s+Indie\s?Hackers\b|indiehackers\.com|indie\.vc", re.IGNORECASE
)

#: Ordered replacements (longest phrases first). Case of the first letter is kept.
_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in (
        (r"#indiehackers?\b", "#founders"),
        (r"\bindie\s+mobile\s+(?:app\s+)?(?:developers|devs)\b", "mobile app developers"),
        (r"\bindie\s+(?:game\s+)?studios?\b", "app studios"),
        (r"\bindie\s+hackers?\b", "founders"),
        (r"\bindiehackers?\b", "founders"),
        (r"\bindie\s+(?:founders?|entrepreneurs?)\b", "early-stage founders"),
        (r"\bindie\s+(?:developers?|devs?)\b", "developers"),
        (r"\bindie\s+makers?\b", "small teams"),
        (r"\bindie\s+saas\b", "small SaaS teams"),
        (r"\bindies\b", "small teams"),
        (r"\bindie\b", "small-team"),
    )
)

SYSTEM_PROMPT = """You are Menivor's brand agent. You set up a brand from its website, keep its brand \
memory, and make ad creatives (scripts, hooks, images, videos) that match it.

Rules:
- Use only facts from the brand memory, the website and the search results you are given. If you do \
not know something, say so. Never invent prices, customers, numbers or reviews.
- Audience wording: Never use the word "indie" for any audience, segment, label or hashtag. Say \
founders, early-stage founders, small teams, app studios, mobile app developers or developers instead. \
Naming the website itself (indiehackers.com) is fine. Do not target maker communities or hobbyist \
audiences unless the brand memory says so; use the audience segments the user confirmed.
- Comparisons with other products must be true and verifiable from what both companies publish, and \
must never imply an affiliation, partnership or endorsement. A competitor the brand's own site names \
(for example as compatible or as a migration source) is where switchers come from: frame it that way.
- Anything that spends credits (images, videos, ad clones, routine batches) or publishes must be \
proposed for approval. Never claim it already happened before the user approves it.
- Write plainly and briefly. No emoji.
- When asked for JSON, reply with JSON only, no prose and no code fences."""


def _is_site_name(text: str, start: int, end: int) -> bool:
    for match in _SITE_RE.finditer(text):
        if match.start() <= start and end <= match.end():
            return True
    return False


def violations(text: str) -> list[str]:
    """Every banned "indie" audience term in ``text`` (site names excluded)."""
    found: list[str] = []
    value = str(text or "")
    for match in _WORD_RE.finditer(value):
        if not _is_site_name(value, match.start(), match.end()):
            found.append(match.group(0))
    return found


def _keep_case(original: str, replacement: str) -> str:
    if original[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def scrub(text: str) -> str:
    """Return ``text`` with banned audience wording replaced (site names kept)."""
    value = str(text or "")
    if not violations(value):
        return value
    for pattern, replacement in _REPLACEMENTS:
        value = pattern.sub(
            lambda m, r=replacement, v=value: m.group(0)
            if _is_site_name(v, m.start(), m.end())
            else _keep_case(m.group(0), r),
            value,
        )
    return value


def scrub_obj(value: Any) -> Any:
    """A scrubbed deep copy of a JSON-like value (input is never mutated)."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: scrub_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_obj(v) for v in value]
    return value


__all__ = ["SYSTEM_PROMPT", "scrub", "scrub_obj", "violations"]
