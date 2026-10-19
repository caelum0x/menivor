"""Derive 8-10 generic App Store search terms from a listing's category and
description. Deterministic and offline (no LLM): a curated genre -> term map,
extended with the most frequent meaningful nouns in the listing's own
description. These are the terms the audit then checks the app's rank for via
the public iTunes Search API (see :mod:`app.domains.appaudit.visibility`).
"""

from __future__ import annotations

import re
from collections import Counter

MIN_TERMS = 6
MAX_TERMS = 10

# Curated fallback terms per Apple's ``primaryGenreName`` (lowercased). Not
# exhaustive: genres missing here fall back to "<genre> app".
GENRE_TERMS: dict[str, tuple[str, ...]] = {
    "health & fitness": ("fitness tracker", "workout app", "health tracker"),
    "food & drink": ("calorie tracker", "diet app", "nutrition tracker"),
    "photo & video": ("photo editor", "video editor", "photo editor app"),
    "productivity": ("productivity app", "task manager", "notes app"),
    "games": ("mobile game", "puzzle game"),
    "education": ("learning app", "study app", "flashcard app"),
    "finance": ("budgeting app", "finance tracker", "money tracker"),
    "utilities": ("utility app",),
    "lifestyle": ("lifestyle app",),
    "social networking": ("social app", "chat app"),
    "entertainment": ("entertainment app",),
    "business": ("business app",),
    "travel": ("travel app", "trip planner"),
    "shopping": ("shopping app", "deals app"),
    "music": ("music app",),
    "sports": ("sports app",),
    "medical": ("medical app", "health app"),
    "navigation": ("navigation app", "maps app"),
    "reference": ("reference app",),
    "weather": ("weather app",),
}

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "your", "you", "are", "that", "this", "from", "have", "has",
    "all", "our", "can", "get", "will", "app", "apps", "use", "using", "into", "each", "every",
    "more", "than", "then", "when", "where", "what", "who", "how", "why", "not", "but", "was",
    "were", "been", "being", "its", "it's", "their", "they", "them", "about", "over", "also",
    "just", "like", "one", "two", "new", "now", "today", "day", "days", "free", "track", "data",
    "powered", "features", "feature", "download", "support", "privacy", "policy", "terms", "please",
    "subscription", "subscriptions", "auto", "renew", "unless", "canceled", "manage", "anytime",
    "account", "settings", "https", "www", "com", "sell", "share", "control", "stays", "private",
    "advanced", "informational", "medical", "dietary", "clinical", "advice",
    "estimates", "estimate", "estimated", "fast", "point", "seconds", "review", "adjust", "saving",
    "complete", "access", "based", "goals", "beautiful", "easy", "read", "charts", "rings", "great",
    "companion", "matters", "makes", "different", "whole", "searching", "instant", "real", "side",
})
_WORD = re.compile(r"[a-z]{4,}")


def _genre_key(genre: str) -> str:
    return (genre or "").strip().lower()


def _top_description_nouns(description: str, limit: int) -> list[str]:
    words = [w for w in _WORD.findall((description or "").lower()) if w not in _STOPWORDS]
    counts = Counter(words)
    # Stable order: frequency desc, then first-seen order (Counter preserves
    # insertion order for ties as of Python 3.7+, so this is deterministic).
    ranked = sorted(counts.items(), key=lambda item: (-item[1], words.index(item[0])))
    return [word for word, count in ranked if count >= 2][:limit]


def derive_search_terms(genre: str, description: str, title: str = "") -> list[str]:
    """8-10 generic search terms a shopper might type, derived from the listing.

    Deterministic: a curated genre map plus the listing's own most-repeated
    description nouns, each turned into a two-word "<noun> tracker/app" term.
    Never includes the app's own brand name.
    """
    key = _genre_key(genre)
    base = list(GENRE_TERMS.get(key, (f"{key} app",) if key else ()))
    # Only the brand/company part of the title (before a colon, if any) is
    # excluded from candidate nouns; a subtitle after the colon (e.g. "Calorie
    # Counter" in "CalDesk AI: Calorie Counter") is real category language.
    brand_part = title.split(":", 1)[0] if title else ""
    brand_words = {w.lower() for w in _WORD.findall(brand_part.lower())}
    nouns = [w for w in _top_description_nouns(description, limit=MAX_TERMS * 2) if w not in brand_words]

    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        norm = term.strip().lower()
        if norm and norm not in seen and len(terms) < MAX_TERMS:
            seen.add(norm)
            terms.append(norm)

    for term in base:
        add(term)
    for noun in nouns:
        if len(terms) >= MAX_TERMS:
            break
        add(f"{noun} tracker")
    for noun in nouns:
        if len(terms) >= MAX_TERMS:
            break
        add(f"{noun} app")
    if len(terms) < MIN_TERMS and key:
        add(f"{key} app")
    return terms[:MAX_TERMS]


__all__ = ["GENRE_TERMS", "MAX_TERMS", "MIN_TERMS", "derive_search_terms"]
