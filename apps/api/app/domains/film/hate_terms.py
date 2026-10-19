"""Curated slur and hate-symbol list for the Very ___ Time guard-rail (item 7).

The list lives in ``assets/moderation/hate_terms.json``: the slur subset of the
LDNOOBW lists (CC-BY-4.0, attribution in THIRD_PARTY_NOTICES.md; the upstream
files mix slurs with general profanity, so only reviewed slurs are copied) plus
curated hate symbols and regional slurs the upstream misses. It is checked
against every user text field, in addition to the preset's banned lists and the
operator's ``VERY_TIME_BLOCKED_WORDS``. Maintenance: ``tools/moderation/refresh_hate_terms.py``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

HATE_TERMS_FILE = Path(__file__).resolve().parents[3] / "assets" / "moderation" / "hate_terms.json"


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    data = json.loads(HATE_TERMS_FILE.read_text(encoding="utf-8"))
    if data.get("id") != "hate-terms" or not data.get("categories"):
        raise ValueError("hate_terms.json: wrong id or no categories")
    return data


def by_category() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, groups in load()["categories"].items():
        terms = [*groups.get("upstream", []), *groups.get("curated", [])]
        out[name] = [t for t in dict.fromkeys(str(t).strip() for t in terms) if t]
    return out


@lru_cache(maxsize=1)
def terms() -> tuple[str, ...]:
    return tuple(dict.fromkeys(t for group in by_category().values() for t in group))


__all__ = ["HATE_TERMS_FILE", "by_category", "load", "terms"]
