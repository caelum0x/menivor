"""Durable markers that keep the free signup credits to one per person (MN3).

Free credits (the signup grant) are the only thing worth farming, so every
grant records who it went to, keyed by the signals a farmer would have to vary:

* ``email``     the normalized sign-in email (Gmail dots and ``+tags`` folded),
* ``card``      the payment card fingerprint from the $1 card check,
* ``attest``    the App Attest key id of the device that attested,
* ``ip`` / ``net`` the client address and its /24 (IPv6: /48) for new device
  accounts.

Markers are append-only :class:`AuditLog` rows (``action`` below, ``target_id``
a SHA-256 hex digest, never the raw value), so they need no new table, survive
a Redis outage and never store a card fingerprint or email in the clear. A
signal already marked for a *different* user means "no grant"; the same user
re-checking is always allowed (idempotent flows).
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

GRANT_ACTION = "abuse.signup_grant"
DEVICE_ACCOUNT_ACTION = "abuse.device_account"

KIND_EMAIL = "email"
KIND_CARD = "card"
KIND_ATTEST = "attest"
KIND_IP = "ip"
KIND_NET = "net"

#: New anonymous device accounts allowed per client IP / network per day.
DEFAULT_ACCOUNTS_PER_IP_DAY = 5
DEFAULT_ACCOUNTS_PER_NET_DAY = 20

_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
_DEVICE_EMAIL_SUFFIX = "@accounts.reelforge.app"
_PEPPER_ENV = "REELFORGE_DEVICE_AUTH_SECRET"


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, "") or default))
    except ValueError:
        return default


def accounts_per_ip_day() -> int:
    return _int_env("MENIVOR_DEVICE_ACCOUNTS_PER_IP_DAY", DEFAULT_ACCOUNTS_PER_IP_DAY)


def accounts_per_net_day() -> int:
    return _int_env("MENIVOR_DEVICE_ACCOUNTS_PER_NET_DAY", DEFAULT_ACCOUNTS_PER_NET_DAY)


# --------------------------------------------------------------------------- #
# Normalization + hashing
# --------------------------------------------------------------------------- #
def normalize_email(email: str | None) -> str:
    """Fold the aliases one mailbox can have: case, ``+tags``, Gmail dots.

    Returns "" for blank input and for synthetic device-account emails (they
    identify an install, not a person).
    """
    raw = str(email or "").strip().lower()
    if "@" not in raw or raw.endswith(_DEVICE_EMAIL_SUFFIX):
        return ""
    local, _, domain = raw.rpartition("@")
    local = local.split("+", 1)[0]
    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    if not local or not domain:
        return ""
    return f"{local}@{domain}"


def network_of(ip: str) -> str:
    """The /24 (IPv4) or /48 (IPv6) network an address belongs to ("" if invalid)."""
    try:
        addr = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return ""
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))


def digest(kind: str, value: str) -> str:
    """Keyed SHA-256 hex of a signal (64 chars: fits ``audit_log.target_id``)."""
    pepper = os.getenv(_PEPPER_ENV, "")
    return hashlib.sha256(f"{pepper}|{kind}|{value}".encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def _marker_owners(session: Any, action: str, kind: str, value: str) -> set[str]:
    from sqlalchemy import select

    from app.models.db.models import AuditLog

    rows = session.execute(
        select(AuditLog.actor_user_id).where(
            AuditLog.action == action,
            AuditLog.target_type == kind,
            AuditLog.target_id == digest(kind, value),
        )
    ).scalars().all()
    return {str(r) for r in rows}


def repeat_signals(session: Any, user_id: str, signals: dict[str, str]) -> list[str]:
    """Kinds among ``signals`` already used for a grant by someone else."""
    repeats: list[str] = []
    for kind, value in signals.items():
        if not value:
            continue
        owners = _marker_owners(session, GRANT_ACTION, kind, value)
        if owners - {str(user_id)}:
            repeats.append(kind)
    return repeats


def count_recent(session: Any, action: str, kind: str, value: str, *, hours: int = 24) -> int:
    from sqlalchemy import func, select

    from app.models.db.models import AuditLog

    if not value:
        return 0
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return int(
        session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == action,
                AuditLog.target_type == kind,
                AuditLog.target_id == digest(kind, value),
                AuditLog.created_at >= since,
            )
        ).scalar()
        or 0
    )


def device_account_quota_left(session: Any, ip: str) -> bool:
    """False once this IP or its network hit today's new-account cap."""
    if not ip:
        return True
    if count_recent(session, DEVICE_ACCOUNT_ACTION, KIND_IP, ip) >= accounts_per_ip_day():
        return False
    net = network_of(ip)
    return count_recent(session, DEVICE_ACCOUNT_ACTION, KIND_NET, net) < accounts_per_net_day()


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def _add(session: Any, user_id: str, action: str, kind: str, value: str, ip: str | None) -> None:
    from app.models.db.models import AuditLog

    session.add(
        AuditLog(
            actor_user_id=str(user_id),
            action=action,
            target_type=kind,
            target_id=digest(kind, value),
            meta={},
            ip=(ip or None),
        )
    )


def record_grant(
    session: Any, user_id: str, signals: dict[str, str], *, ip: str | None = None
) -> None:
    """Mark each non-empty signal as used by ``user_id``'s free grant."""
    for kind, value in signals.items():
        if value:
            _add(session, user_id, GRANT_ACTION, kind, value, ip)
    session.flush()


def record_device_account(session: Any, user_id: str, ip: str) -> None:
    """Count a new anonymous device account against its IP and network."""
    if not ip:
        return
    _add(session, user_id, DEVICE_ACCOUNT_ACTION, KIND_IP, ip, ip)
    net = network_of(ip)
    if net:
        _add(session, user_id, DEVICE_ACCOUNT_ACTION, KIND_NET, net, ip)
    session.flush()


def grant_allowed(session: Any, user_id: str, signals: dict[str, str]) -> bool:
    """True when no signal was already used for someone else's free grant."""
    repeats = repeat_signals(session, user_id, signals)
    if repeats:
        logger.info(f"free grant withheld for user={user_id}: repeat {','.join(sorted(repeats))}")
    return not repeats


def email_signals(email: str | None) -> dict[str, str]:
    return {KIND_EMAIL: normalize_email(email)}


def merge(*parts: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in parts:
        out.update({k: v for k, v in part.items() if v})
    return out


__all__ = [
    "DEVICE_ACCOUNT_ACTION",
    "GRANT_ACTION",
    "KIND_ATTEST",
    "KIND_CARD",
    "KIND_EMAIL",
    "accounts_per_ip_day",
    "accounts_per_net_day",
    "device_account_quota_left",
    "digest",
    "email_signals",
    "grant_allowed",
    "merge",
    "network_of",
    "normalize_email",
    "record_device_account",
    "record_grant",
    "repeat_signals",
]
