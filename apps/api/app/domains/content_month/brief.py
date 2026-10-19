"""Site brief: what a website says about itself, reduced to the facts posts may use.

Input is the output of :func:`app.domains.brand_agent.site_analysis.analyze_site`
(name, one-liner, headings, sample lines, features, pricing hook, category,
colours, fonts, logo). Output is a :class:`SiteBrief` with cleaned value lines,
an audience phrase, a topic and a typical pain for the site's category, plus
the set of numbers the site itself states (posts may never state any other
figure).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_SPACE_RE = re.compile(r"\s+")
_AUDIENCE_RE = re.compile(r"(?:^|[.!?]\s+)(?:made for|for)\s+([a-z][a-z ,&\-]{3,80}?)(?:[.;:!]|$)", re.I)
#: Words that follow "for" on landing pages but are not an audience.
_NOT_AUDIENCE = frozenset({"agents", "agent", "ai", "free", "everyone", "you", "life", "good", "now", "more"})
_NAV_WORDS = ("sign in", "log in", "sign up", "cookie", "privacy", "terms", "copyright", "all rights")
LINE_MIN = 12
LINE_MAX = 160
FEATURE_MAX = 90

#: Category -> (topic, default audience, typical pain, old habit, outcome).
CATEGORY_ANGLES: dict[str, tuple[str, str, str, str, str]] = {
    "Developer tools: backend platform": (
        "backend setup", "developers", "lose a weekend wiring up a database and auth",
        "setting up servers by hand", "ship a backend"),
    "Marketing: AI video and ads": (
        "short-form video", "founders", "know you should post video but never find the hours",
        "editing every video by hand", "post a video every day"),
    "E-commerce store": (
        "your store", "shop owners", "spend hours on posts that nobody sees",
        "guessing what customers want", "turn visitors into orders"),
    "Mobile app": (
        "app growth", "app makers", "launch an app and hear nothing back",
        "hoping the app store sends users", "get your first users"),
    "Education": (
        "studying", "students", "study for hours and still forget it",
        "rereading notes the night before", "learn faster"),
    "Finance": (
        "money admin", "small businesses", "lose time on payments and paperwork",
        "chasing payments by email", "get paid on time"),
    "Health and fitness": (
        "your routine", "busy people", "start a routine and drop it in a week",
        "starting over every Monday", "stick to a routine"),
}
DEFAULT_ANGLE = ("your workflow", "small teams", "do the same task by hand every week",
                 "doing it all by hand", "get it done faster")


def clean(text: Any, limit: int = LINE_MAX) -> str:
    value = _SPACE_RE.sub(" ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0].rstrip(",.;:-")
    return cut or value[:limit]


def numbers_in(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM_RE.findall(text or "")}


def _usable(line: str) -> bool:
    lower = line.lower()
    return LINE_MIN <= len(line) <= LINE_MAX and not any(w in lower for w in _NAV_WORDS)


def _dedupe(lines: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.lower().rstrip(".")
        if key and key not in seen:
            seen.add(key)
            out.append(line)
        if len(out) >= limit:
            break
    return out


def _audience(lines: list[str], default: str) -> str:
    for line in lines:
        match = _AUDIENCE_RE.search(line)
        if match:
            phrase = clean(match.group(1), 60).strip(" ,&-").lower()
            first = phrase.split()[0] if phrase else ""
            if 3 <= len(phrase) and first not in _NOT_AUDIENCE and not phrase.startswith(
                    ("the price", "a ", "an ", "your ")):
                return phrase
    return default


@dataclass(frozen=True)
class SiteBrief:
    name: str
    url: str
    domain: str
    one_liner: str
    category: str
    topic: str
    audience: str
    pain: str
    old_habit: str
    outcome: str
    value_lines: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    pricing_hook: str = ""
    colors: tuple[str, ...] = ()
    fonts: tuple[str, ...] = ()
    logo_url: str = ""
    language: str = "en"
    allowed_numbers: frozenset[str] = field(default_factory=frozenset)

    def facts(self) -> dict[str, Any]:
        """What the LLM may use (JSON-safe)."""
        return {
            "name": self.name, "website": self.domain, "one_liner": self.one_liner, "category": self.category,
            "audience": self.audience, "value_lines": list(self.value_lines), "features": list(self.features),
            "pricing": self.pricing_hook,
        }

    def brand(self) -> dict[str, Any]:
        """Brand block in the Design Studio shape (``style_from_brand``)."""
        return {"name": self.name, "colors": list(self.colors), "fonts": list(self.fonts), "logo_url": self.logo_url}

    def to_dict(self) -> dict[str, Any]:
        return {**self.facts(), "url": self.url, "topic": self.topic, "pain": self.pain,
                "colors": list(self.colors), "fonts": list(self.fonts), "logo_url": self.logo_url,
                "language": self.language}


def _hexes(values: Any) -> tuple[str, ...]:
    out = []
    for value in values or []:
        hex_value = value.get("hex") if isinstance(value, dict) else value
        if isinstance(hex_value, str) and hex_value.startswith("#"):
            out.append(hex_value.lower())
    return tuple(out[:6])


def _fonts(values: Any) -> tuple[str, ...]:
    out = []
    for value in values or []:
        family = value.get("family") if isinstance(value, dict) else value
        if isinstance(family, str) and family.strip():
            out.append(family.strip())
    return tuple(out[:3])


def from_analysis(analysis: dict[str, Any]) -> SiteBrief:
    """Build a :class:`SiteBrief` from ``analyze_site`` output."""
    url = str(analysis.get("website_url") or "")
    domain = (urlparse(url).hostname or "").removeprefix("www.")
    name = clean(analysis.get("name"), 60) or domain
    one_liner = clean(analysis.get("one_liner") or analysis.get("description"), 220)
    raw_lines = [clean(x) for x in [*(analysis.get("headings") or []), *(analysis.get("sample_lines") or [])]]
    value_lines = _dedupe([x for x in raw_lines if _usable(x)], 12)
    features = _dedupe([clean(x, FEATURE_MAX) for x in analysis.get("features") or []
                        if LINE_MIN <= len(clean(x, 400)) <= FEATURE_MAX], 8)
    category = str(analysis.get("category") or "Software")
    topic, audience, pain, old_habit, outcome = CATEGORY_ANGLES.get(category, DEFAULT_ANGLE)
    corpus = " ".join([one_liner, *value_lines, *features, str(analysis.get("pricing_hook") or "")])
    return SiteBrief(
        name=name, url=url, domain=domain, one_liner=one_liner, category=category, topic=topic,
        audience=_audience([one_liner, *value_lines], audience), pain=pain, old_habit=old_habit, outcome=outcome,
        value_lines=tuple(value_lines), features=tuple(features),
        pricing_hook=clean(analysis.get("pricing_hook"), 80), colors=_hexes(analysis.get("colors")),
        fonts=_fonts(analysis.get("fonts")),
        logo_url=str(((analysis.get("logo") or {}).get("url")) or analysis.get("image_url") or ""),
        language=str(analysis.get("language") or "en")[:8] or "en",
        allowed_numbers=frozenset(numbers_in(corpus)),
    )


__all__ = ["CATEGORY_ANGLES", "SiteBrief", "clean", "from_analysis", "numbers_in"]
