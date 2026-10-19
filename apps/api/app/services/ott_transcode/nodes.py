"""Transcode nodes (MV2): register, authenticate by token, heartbeat.

A node (the owner's Mac or a burst box) is registered once by staff; the raw
token is shown once and only its SHA-256 is stored. A node is "live" when its
heartbeat is under 60 s old; the Mac also needs more than 10 GB free.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LANE_BURST, LANE_MAC, OttNode

HEARTBEAT_MAX_AGE = timedelta(seconds=60)
MAC_MIN_FREE_GB = 10.0
KINDS = (LANE_MAC, LANE_BURST)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def register(session: Session, name: str, kind: str) -> tuple[OttNode, str]:
    if kind not in KINDS:
        raise ValueError(f"node kind is one of {KINDS}")
    token = "ottn_" + secrets.token_urlsafe(32)
    node = OttNode(name=name.strip()[:60], kind=kind, token_hash=_hash(token))
    session.add(node)
    session.flush()
    return node, token


def authenticate(session: Session, token: str) -> OttNode | None:
    if not token or not token.startswith("ottn_"):
        return None
    digest = _hash(token)
    node = session.execute(select(OttNode).where(OttNode.token_hash == digest)).scalar_one_or_none()
    if node is None or not node.enabled or not hmac.compare_digest(node.token_hash, digest):
        return None
    return node


def heartbeat(session: Session, node: OttNode, *, free_gb: float, cores: int, now: datetime | None = None) -> None:
    node.last_heartbeat_at = now or datetime.now(timezone.utc)
    node.free_gb = max(0.0, float(free_gb))
    node.cores = max(0, int(cores))
    session.flush()


def is_live(node: OttNode, *, now: datetime | None = None) -> bool:
    seen = _utc(node.last_heartbeat_at)
    moment = now or datetime.now(timezone.utc)
    if not node.enabled or seen is None or moment - seen >= HEARTBEAT_MAX_AGE:
        return False
    return node.kind != LANE_MAC or node.free_gb > MAC_MIN_FREE_GB


def live_nodes(session: Session, kind: str, *, now: datetime | None = None) -> list[OttNode]:
    rows = session.execute(select(OttNode).where(OttNode.kind == kind, OttNode.enabled.is_(True))).scalars().all()
    return [n for n in rows if is_live(n, now=now)]


__all__ = ["HEARTBEAT_MAX_AGE", "MAC_MIN_FREE_GB", "authenticate", "heartbeat", "is_live", "live_nodes", "register"]
