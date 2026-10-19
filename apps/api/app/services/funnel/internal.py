"""Internal (staff / smoke-test / marketing-render) accounts, kept out of metrics.

An account is internal when its email domain is one of ours or the address is
listed explicitly. Defaults cover our own domains, so the prod smoke user and
the Megaphone renderer (``smoke-internal@menivor.com``) never count as a
signup, card check, first reel or payment.

Override with ``MENIVOR_INTERNAL_EMAIL_DOMAINS`` / ``MENIVOR_INTERNAL_EMAILS``
(comma-separated).
"""

from __future__ import annotations

import os
from typing import Any, Iterable

from sqlalchemy import select

DEFAULT_INTERNAL_DOMAINS: tuple[str, ...] = ("menivor.com", "ereboslab.com")


def _csv(name: str, default: Iterable[str] = ()) -> frozenset[str]:
    raw = os.environ.get(name)
    items = default if raw is None else raw.split(",")
    return frozenset(i.strip().lower() for i in items if i and i.strip())


def internal_domains() -> frozenset[str]:
    return _csv("MENIVOR_INTERNAL_EMAIL_DOMAINS", DEFAULT_INTERNAL_DOMAINS)


def internal_emails() -> frozenset[str]:
    return _csv("MENIVOR_INTERNAL_EMAILS")


def is_internal_email(email: str | None) -> bool:
    value = (email or "").strip().lower()
    if not value or "@" not in value:
        return False
    if value in internal_emails():
        return True
    return value.rsplit("@", 1)[1] in internal_domains()


def internal_user_ids(session: Any) -> frozenset[str]:
    """Ids of every internal account (small table scan; users is tiny)."""
    from app.models.db.models import User

    rows = session.execute(select(User.id, User.email)).all()
    return frozenset(str(uid) for uid, email in rows if is_internal_email(email))
