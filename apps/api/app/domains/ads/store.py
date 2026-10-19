"""Paid-campaign state stored on Ad Studio variants (no new table).

Each creative in a campaign keeps one entry under
``AdVariant.spec['paid_ads'][<campaign_key>]``: the platform ids of its ad set
/ video / ad, its current daily budget and allocation, and the last stats pulled
from the platform. Campaign-level settings are copied into every entry under
``campaign`` so any one row can describe the campaign. Writes always assign a
fresh ``spec`` dict (JSON columns do not track in-place mutation).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.domains.adstudio.models import AdVariant

SPEC_KEY = "paid_ads"
SCAN_LIMIT = 2000

PHASE_UPLOADING = "uploading"
PHASE_PROCESSING = "processing"
PHASE_LIVE = "live"
PHASE_FAILED = "failed"

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_ERROR = "error"
STATUS_ARCHIVED = "archived"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_key() -> str:
    return uuid.uuid4().hex[:16]


def entry(variant: Any, key: str) -> dict | None:
    raw = ((variant.spec or {}).get(SPEC_KEY) or {}).get(key)
    return dict(raw) if isinstance(raw, dict) else None


def write(variant: Any, key: str, value: dict) -> None:
    spec = dict(variant.spec or {})
    paid = dict(spec.get(SPEC_KEY) or {})
    paid[key] = value
    spec[SPEC_KEY] = paid
    variant.spec = spec


def update_campaign(rows: list[tuple[Any, dict]], key: str, **changes: Any) -> list[tuple[Any, dict]]:
    """Apply campaign-level ``changes`` to every creative's copy; return new rows."""
    out = []
    for variant, item in rows:
        fresh = {**item, "campaign": {**(item.get("campaign") or {}), **changes}}
        write(variant, key, fresh)
        out.append((variant, fresh))
    return out


def _user_variants(session: Any, user_id: str) -> list[AdVariant]:
    stmt = (
        select(AdVariant)
        .where(AdVariant.user_id == user_id)
        .order_by(AdVariant.updated_at.desc())
        .limit(SCAN_LIMIT)
    )
    return list(session.execute(stmt).scalars().all())


def campaigns(session: Any, user_id: str) -> "OrderedDict[str, list[tuple[Any, dict]]]":
    """Every paid campaign of ``user_id``: key -> [(variant, entry)], newest first."""
    grouped: dict[str, list[tuple[Any, dict]]] = {}
    for variant in _user_variants(session, user_id):
        for key, raw in ((variant.spec or {}).get(SPEC_KEY) or {}).items():
            if isinstance(raw, dict):
                grouped.setdefault(key, []).append((variant, dict(raw)))
    ordered = sorted(
        grouped.items(),
        key=lambda kv: str((kv[1][0][1].get("campaign") or {}).get("created_at") or ""),
        reverse=True,
    )
    return OrderedDict((k, sorted(v, key=lambda r: int(r[1].get("order", 0)))) for k, v in ordered)


def campaign_rows(session: Any, user_id: str, key: str) -> list[tuple[Any, dict]]:
    return campaigns(session, user_id).get(key, [])


__all__ = [
    "PHASE_FAILED", "PHASE_LIVE", "PHASE_PROCESSING", "PHASE_UPLOADING", "SPEC_KEY", "STATUS_ACTIVE",
    "STATUS_ARCHIVED", "STATUS_ERROR", "STATUS_PAUSED", "campaign_rows", "campaigns", "entry", "new_key",
    "now_iso", "update_campaign", "write",
]
