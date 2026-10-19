"""Mandatory ToS gate for trend scraping: consent decision + source allowlist.

Scraping a third-party platform is only permitted when BOTH hold:

1. the acting user has a CURRENT ``trend_scraping`` consent decision recorded as
   granted (read via the append-only compliance consent controller — the same
   pattern ``spend``/``byok`` use for their consent checks), and
2. the requested ``target`` (hashtag / sound / ``trending``) is on the deployer's
   allowlist (env ``TREND_PULL_ALLOWLIST``, a comma-separated list — copying the
   ``_configured_default_id`` env-read pattern from ``broll/providers/base.py``).

The allowlist is CLOSED by default: with no ``TREND_PULL_ALLOWLIST`` configured,
nothing is scrapable. The provider's ``is_enabled()`` and the worker BOTH refuse
to pull when either check fails, so a disabled/unconsented pull never spends
credits or touches the network.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

#: Consent dimension recorded against a user for trend scraping (ToS gate).
CONSENT_KIND: str = "trend_scraping"

#: Comma-separated allowlist of scrapable targets (hashtags/sounds), or the
#: sentinel ``*`` / ``all`` / ``trending`` to permit the For-You feed.
_ALLOWLIST_ENV: str = "TREND_PULL_ALLOWLIST"

#: Reserved target that always maps to the For-You/trending feed pull.
TRENDING_TARGET: str = "trending"


def _normalize_target(target: str) -> str:
    return str(target or "").strip().lstrip("#").strip().lower()


def _allowlist() -> set[str]:
    """The configured set of scrapable targets (lower-cased, ``#`` stripped)."""
    raw = os.getenv(_ALLOWLIST_ENV) or ""
    return {_normalize_target(part) for part in raw.split(",") if part.strip()}


def is_target_allowed(target: str) -> bool:
    """True when ``target`` is on the allowlist (closed by default).

    A ``*`` entry opens the allowlist to every target; otherwise the normalized
    target must be listed explicitly. An empty allowlist denies everything.
    """
    allow = _allowlist()
    if not allow:
        return False
    if "*" in allow:
        return True
    return _normalize_target(target) in allow


def is_consent_granted(session: Any, user_id: str) -> bool:
    """True when ``user_id``'s CURRENT ``trend_scraping`` consent is granted.

    Reads the newest append-only decision via the compliance consent controller.
    Any failure (compliance layer absent, DB hiccup) is treated as *no consent*
    — fail-closed — and never raises.
    """
    user_id = (user_id or "").strip()
    if not user_id:
        return False
    try:
        from app.services.compliance import consent as consent_service

        record = consent_service.get_consent(session, user_id, CONSENT_KIND)
    except Exception as exc:  # noqa: BLE001 - fail-closed on any consent-read error
        logger.warning(f"trend_pull: consent lookup failed for {user_id!r}: {exc}")
        return False
    return bool(record is not None and getattr(record, "granted", False))


def is_pull_allowed(session: Any, user_id: str, target: str) -> bool:
    """The single ToS gate: ``True`` only when consent AND allowlist both pass."""
    return is_consent_granted(session, user_id) and is_target_allowed(target)


__all__ = [
    "CONSENT_KIND",
    "TRENDING_TARGET",
    "is_target_allowed",
    "is_consent_granted",
    "is_pull_allowed",
]
