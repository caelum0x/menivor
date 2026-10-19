"""MH9 growth loop: the weekly "new presets" drop (Wave P PM3.0).

How a drop works:

* The trends domain proposes formats (:func:`brief`: the recommended trend
  labels of the last 14 days). We make **original** preset versions of them
  (no copied assets) and render their preview loops; each preview entry in
  ``assets/presets/previews.json`` carries ``"drop": "<ISO week>"`` (for
  example ``2026-W41``). Model-preset previews are paid renders from the owner
  promo budget (item M2): their entries say ``funded_by = owner-promo-M2``.
* A preset whose entry names a drop stays hidden from the shelf until that
  drop is released (``presets_hub.previews.visible`` asks :func:`released`).
* Every Monday the beat calls :func:`publish_week`. A drop is released only
  with **at least 3** ready presets (a real loop and poster, clean copy, a
  known preset id, the model ones funded) and only while the week's preview
  spend stays inside ``MENIVOR_PRESET_DROP_BUDGET_USD`` (default 20). Fewer
  than 3, or over budget: nothing is released and the reason is returned.
  One row per week, so a second run is a no-op.

Routes (public, edge-cached): ``GET /api/v1/presets/drops`` and
``GET /api/v1/presets/drops/latest``.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Request, Response
from loguru import logger
from sqlalchemy import JSON, DateTime, Float, String, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.db.base import Base
from app.utils import utils

MIN_DROP = 3
DEFAULT_BUDGET_USD = 20.0
BUDGET_ENV = "MENIVOR_PRESET_DROP_BUDGET_USD"
OWNER_PROMO_DROP = "owner-promo-M2"
OWNER_PROMO_SHELF = "owner-promo-M1"
READY_STATUSES = frozenset({"staged", "published"})
CACHE_CONTROL = "public, max-age=60, s-maxage=300"
RELEASED_CACHE_S = 60.0
BRIEF_DAYS = 14
BRIEF_LIMIT = 8


def _id() -> str:
    return uuid.uuid4().hex


class PresetDrop(Base):
    """One released weekly drop (migration e5b7d9f1a3c6)."""

    __tablename__ = "preset_drops"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    week: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    preset_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    spend_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------- #
# Weeks, budget, readiness
# --------------------------------------------------------------------------- #
def iso_week(moment: Optional[datetime] = None) -> str:
    year, week, _ = (moment or datetime.now(timezone.utc)).isocalendar()
    return f"{year}-W{week:02d}"


def budget_usd(env: Optional[Mapping[str, str]] = None) -> float:
    raw = (env if env is not None else os.environ).get(BUDGET_ENV)
    try:
        return max(0.0, float(raw)) if raw not in (None, "") else DEFAULT_BUDGET_USD
    except ValueError:
        return DEFAULT_BUDGET_USD


def _ready_reason(preset: Any, entry: Mapping[str, Any]) -> str:
    """'' when the preset can ship in a drop, else why not."""
    from app.domains.presets_hub import catalog

    if preset is None:
        return "unknown preset"
    if not entry.get("loop") or not entry.get("poster"):
        return "no preview loop yet"
    if str(entry.get("status") or "") not in READY_STATUSES:
        return "preview not uploaded"
    if preset.kind == catalog.KIND_MODEL and entry.get("funded_by") not in (OWNER_PROMO_DROP, OWNER_PROMO_SHELF):
        return "model preview not funded from the promo budget"
    if catalog.vendor_hits(f"{preset.name} {preset.blurb}"):
        return "copy names a tool or model"
    return ""


def candidates(week: str, manifest: Optional[Mapping[str, Mapping]] = None) -> dict[str, Any]:
    """The presets planned for ``week``: which are ready and why the others are not."""
    from app.domains.presets_hub import catalog, previews

    manifest = previews.load_manifest() if manifest is None else manifest
    ready: list[str] = []
    waiting: dict[str, str] = {}
    spend = 0.0
    for preset_id, entry in sorted(manifest.items()):
        if str((entry or {}).get("drop") or "") != week:
            continue
        reason = _ready_reason(catalog.get(preset_id), entry)
        if reason:
            waiting[preset_id] = reason
            continue
        ready.append(preset_id)
        spend += float(entry.get("spend_usd") or 0.0)
    return {"week": week, "ready": ready, "waiting": waiting, "spend_usd": round(spend, 2)}


# --------------------------------------------------------------------------- #
# Release
# --------------------------------------------------------------------------- #
_released_cache: dict[str, Any] = {"at": 0.0, "ids": frozenset()}


def reset_cache() -> None:
    _released_cache.update(at=0.0, ids=frozenset())


def publish_week(session: Session, week: Optional[str] = None, *,
                 manifest: Optional[Mapping[str, Mapping]] = None,
                 env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Release the drop for ``week`` when 3+ presets are ready inside the budget. Idempotent."""
    week = week or iso_week()
    existing = session.execute(select(PresetDrop).where(PresetDrop.week == week)).scalar_one_or_none()
    if existing is not None:
        return {"published": True, "week": week, "preset_ids": list(existing.preset_ids), "already": True}
    plan = candidates(week, manifest)
    if len(plan["ready"]) < MIN_DROP:
        return {"published": False, "week": week, "reason": f"only {len(plan['ready'])} of {MIN_DROP} presets ready",
                "waiting": plan["waiting"]}
    cap = budget_usd(env)
    if plan["spend_usd"] > cap:
        return {"published": False, "week": week,
                "reason": f"preview spend ${plan['spend_usd']:.2f} is over the weekly promo cap ${cap:.2f}"}
    try:
        with session.begin_nested():
            session.add(PresetDrop(week=week, preset_ids=list(plan["ready"]), spend_usd=plan["spend_usd"]))
    except IntegrityError:
        return {"published": True, "week": week, "already": True}
    session.flush()
    reset_cache()
    return {"published": True, "week": week, "preset_ids": list(plan["ready"]), "spend_usd": plan["spend_usd"]}


def _load_released() -> frozenset[str]:
    from app.models.db.base import get_session

    with get_session() as session:
        rows = session.execute(select(PresetDrop.preset_ids)).scalars().all()
    return frozenset(pid for ids in rows for pid in (ids or []))


def released(preset_id: str, *, loader=None) -> bool:
    """Whether ``preset_id`` shipped in a released drop (cached 60 s; a read failure hides it)."""
    now = time.monotonic()
    if now - float(_released_cache["at"]) > RELEASED_CACHE_S:
        try:
            ids = (loader or _load_released)()
        except (SQLAlchemyError, RuntimeError, OSError) as exc:
            logger.warning(f"preset drops: released set not read: {type(exc).__name__}")
            ids = frozenset()
        _released_cache.update(at=now, ids=frozenset(ids))
    return preset_id in _released_cache["ids"]


# --------------------------------------------------------------------------- #
# Trends brief: what the next drop should be about
# --------------------------------------------------------------------------- #
def brief(session: Session, *, now: Optional[datetime] = None, limit: int = BRIEF_LIMIT) -> list[dict[str, Any]]:
    """Recommended trend formats of the last 14 days, best opportunity first (labels only)."""
    from app.models.db.trends import TrendObservation

    since = (now or datetime.now(timezone.utc)) - timedelta(days=BRIEF_DAYS)
    rows = session.execute(
        select(TrendObservation.trend_id, TrendObservation.kind, TrendObservation.label,
               func.max(TrendObservation.opportunity_bps))
        .where(TrendObservation.recommend.is_(True), TrendObservation.observed_at >= since)
        .group_by(TrendObservation.trend_id, TrendObservation.kind, TrendObservation.label)
        .order_by(func.max(TrendObservation.opportunity_bps).desc())
        .limit(limit)
    ).all()
    return [{"trend_id": r[0], "kind": r[1], "label": r[2], "opportunity_bps": int(r[3] or 0)} for r in rows]


# --------------------------------------------------------------------------- #
# Public reads
# --------------------------------------------------------------------------- #
def drop_view(row: PresetDrop, manifest: Optional[Mapping[str, Mapping]] = None) -> dict[str, Any]:
    from app.domains.presets_hub import service as shelf

    tiles = {t["id"]: t for t in shelf.shelf(manifest)}
    return {"week": row.week, "published_at": row.published_at.isoformat() if row.published_at else None,
            "presets": [tiles[pid] for pid in row.preset_ids if pid in tiles]}


def recent(session: Session, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = session.execute(select(PresetDrop).order_by(PresetDrop.week.desc()).limit(limit)).scalars().all()
    return [drop_view(r) for r in rows]


router = new_router()


def get_session():
    from app.models.db.base import get_session as _get_session

    return _get_session()


@router.get("/presets/drops", summary="Recent weekly preset drops (public)")
def list_drops(request: Request, response: Response):
    from app.controllers.v1.jobs import _require_db

    _require_db(base.get_task_id(request))
    with get_session() as session:
        drops = recent(session)
    response.headers["Cache-Control"] = CACHE_CONTROL
    return utils.get_response(200, {"drops": drops})


@router.get("/presets/drops/latest", summary="This week's new presets (public)")
def latest_drop(request: Request, response: Response):
    from app.controllers.v1.jobs import _require_db

    _require_db(base.get_task_id(request))
    with get_session() as session:
        drops = recent(session, limit=1)
    response.headers["Cache-Control"] = CACHE_CONTROL
    return utils.get_response(200, drops[0] if drops else {"week": None, "presets": []})


def run_weekly() -> dict[str, Any]:
    """The Monday beat body (``preset_drop_tasks``)."""
    from app.models.db.base import get_session as _get_session

    with _get_session() as session:
        result = publish_week(session)
    if not result.get("published"):
        logger.info(f"preset drop {result.get('week')}: not released ({result.get('reason')})")
    return result


__all__ = ["MIN_DROP", "PresetDrop", "brief", "budget_usd", "candidates", "iso_week", "publish_week", "recent",
           "released", "reset_cache", "router", "run_weekly"]
