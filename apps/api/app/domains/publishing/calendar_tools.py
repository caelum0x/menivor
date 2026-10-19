"""Unified publishing calendar: every scheduled post, policy-checked moves, slot hints.

The calendar shows two kinds of entries side by side:

* ``native`` - a :class:`~app.models.db.models.ScheduledPublish` (a finished reel
  cross-posted to TikTok / Instagram / YouTube through the native connectors);
* ``post``   - a :class:`~.extended.models.PlatformPost` (Facebook, LinkedIn, X,
  Threads, Pinterest, Bluesky, and the Telegram / Discord / Mastodon channels).

Dragging an entry to a new time goes through :func:`check_slot`, which runs
:func:`.scheduling_policy.decide` for every platform of the entry against the
creator's other posts on that platform (daily cap + minimum gap). A move that
breaks the policy is refused with the reason and the next legal slot, unless
the creator explicitly keeps it anyway (``force``). A time in the past is
always refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from .extended.catalog import is_channel
from .extended.models import (
    POST_PROCESSING,
    POST_PUBLISHED,
    POST_PUBLISHING,
    POST_SCHEDULED,
    PlatformPost,
)
from .scheduling_policy import decide, platform_config
from .tone import platform_label

SOURCE_NATIVE = "native"
SOURCE_POST = "post"
SOURCES = frozenset({SOURCE_NATIVE, SOURCE_POST})
MAX_RANGE = timedelta(days=92)
# Neighbouring posts that can affect a candidate slot (daily cap = same UTC day, min gap < 1 day).
_NEIGHBOUR_WINDOW = timedelta(days=2)
_NATIVE_BUSY = ("pending", "publishing", "published")
_POST_BUSY = (POST_SCHEDULED, POST_PUBLISHING, POST_PROCESSING, POST_PUBLISHED)
_POLICY_ALIASES = {"youtube_shorts": "youtube"}


class CalendarToolError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, details: dict | None = None) -> None:
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    v = _utc(value)
    return v.isoformat() if v else None


def policy_key(platform: str) -> str:
    plat = str(platform or "").strip().lower()
    return _POLICY_ALIASES.get(plat, plat)


def best_hours(platforms: list[str] | tuple[str, ...]) -> dict[str, list[int]]:
    """``{platform: [UTC hours]}`` of the policy's high-engagement windows."""
    return {p: sorted(int(h) for h in platform_config(policy_key(p))["best_hours"]) for p in platforms}


def _scheduled_publish_model():
    from app.models.db.models import ScheduledPublish

    return ScheduledPublish


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def _native_entry(row: Any) -> dict:
    platforms = list(row.platforms or [])
    return {
        "source": SOURCE_NATIVE,
        "id": row.id,
        "job_id": row.job_id,
        "platforms": platforms,
        "labels": [platform_label(p) for p in platforms],
        "scheduled_at": _iso(row.scheduled_at),
        "status": row.status,
        "text": "",
        "url": "",
        "error": "",
        "target_id": "",
        "can_move": row.status == "pending",
    }


def _post_entry(row: PlatformPost, channel_labels: dict[str, str]) -> dict:
    return {
        "source": SOURCE_POST,
        "id": row.id,
        "job_id": row.job_id or None,
        "platforms": [row.platform],
        "labels": [platform_label(row.platform)],
        "scheduled_at": _iso(row.scheduled_at),
        "status": row.status,
        "text": (row.text or "")[:280],
        "url": row.url or "",
        "error": (row.error or "")[:300],
        "target_id": row.target_id or "",
        "channel_label": channel_labels.get(row.target_id or "", ""),
        "can_move": row.status == POST_SCHEDULED and int(row.attempts or 0) == 0,
    }


def _channel_labels(session: Any, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    try:
        from .extended.channel_models import SocialChannelCredential
    except Exception:  # pragma: no cover
        return {}
    rows = session.execute(
        select(SocialChannelCredential.id, SocialChannelCredential.label, SocialChannelCredential.target_name)
        .where(SocialChannelCredential.id.in_(list(ids)))
    ).all()
    return {str(i): str(label or name or "") for i, label, name in rows}


def entries(session: Any, user_id: str, start: datetime, end: datetime) -> dict:
    """Every calendar entry of the owner in ``[start, end]`` (clamped to 92 days)."""
    start_utc, end_utc = _utc(start), _utc(end)
    if start_utc is None or end_utc is None or start_utc >= end_utc:
        raise CalendarToolError("start must be strictly before end")
    end_utc = min(end_utc, start_utc + MAX_RANGE)
    SP = _scheduled_publish_model()
    native_rows = session.execute(
        select(SP).where(SP.user_id == user_id, SP.scheduled_at >= start_utc, SP.scheduled_at <= end_utc)
        .order_by(SP.scheduled_at.asc())
    ).scalars().all()
    post_rows = session.execute(
        select(PlatformPost).where(
            PlatformPost.user_id == user_id,
            PlatformPost.scheduled_at >= start_utc,
            PlatformPost.scheduled_at <= end_utc,
        ).order_by(PlatformPost.scheduled_at.asc())
    ).scalars().all()
    labels = _channel_labels(session, {r.target_id for r in post_rows if r.target_id})
    items = [_native_entry(r) for r in native_rows] + [_post_entry(r, labels) for r in post_rows]
    items.sort(key=lambda e: e["scheduled_at"] or "")
    platforms = sorted({p for e in items for p in e["platforms"]})
    return {
        "entries": items,
        "start": start_utc.isoformat(),
        "end": end_utc.isoformat(),
        "best_hours_utc": best_hours(platforms),
    }


# --------------------------------------------------------------------------- #
# Slot policy
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PlatformVerdict:
    platform: str
    allow: bool
    reason: str
    suggested_at: datetime | None

    def to_record(self) -> dict:
        return {"platform": self.platform, "label": platform_label(self.platform), "allow": self.allow,
                "reason": self.reason, "suggested_at": _iso(self.suggested_at)}


@dataclass(frozen=True)
class SlotCheck:
    allow: bool
    reason: str
    suggested_at: datetime | None
    verdicts: tuple[PlatformVerdict, ...] = field(default_factory=tuple)
    best_hours_utc: dict = field(default_factory=dict)

    def to_record(self) -> dict:
        return {
            "allow": self.allow,
            "reason": self.reason,
            "suggested_at": _iso(self.suggested_at),
            "platforms": [v.to_record() for v in self.verdicts],
            "best_hours_utc": self.best_hours_utc,
        }


def _load(session: Any, user_id: str, source: str, entry_id: str) -> Any:
    if source not in SOURCES:
        raise CalendarToolError("unknown entry source", status_code=404)
    model = _scheduled_publish_model() if source == SOURCE_NATIVE else PlatformPost
    row = session.get(model, entry_id)
    if row is None or row.user_id != user_id:
        raise CalendarToolError("calendar entry not found", status_code=404)
    return row


def _platforms_of(source: str, row: Any) -> list[str]:
    return list(row.platforms or []) if source == SOURCE_NATIVE else [row.platform]


def _neighbours(session: Any, user_id: str, platform: str, around: datetime, *,
                exclude: tuple[str, str], channel_target: str = "") -> list[datetime]:
    """The owner's other busy post times on ``platform`` near ``around``.

    For Telegram / Discord / Mastodon (``channel_target`` set) only posts to the
    same channel count: two different channels never cannibalize each other.
    """
    lo, hi = around - _NEIGHBOUR_WINDOW, around + _NEIGHBOUR_WINDOW
    key = policy_key(platform)
    times: list[datetime] = []
    SP = _scheduled_publish_model()
    for row in session.execute(
        select(SP).where(SP.user_id == user_id, SP.status.in_(_NATIVE_BUSY),
                         SP.scheduled_at >= lo, SP.scheduled_at <= hi)
    ).scalars().all():
        if (SOURCE_NATIVE, row.id) == exclude:
            continue
        if any(policy_key(p) == key for p in (row.platforms or [])):
            times.append(_utc(row.scheduled_at))  # type: ignore[arg-type]
    for row in session.execute(
        select(PlatformPost).where(PlatformPost.user_id == user_id, PlatformPost.status.in_(_POST_BUSY),
                                   PlatformPost.scheduled_at >= lo, PlatformPost.scheduled_at <= hi)
    ).scalars().all():
        if (SOURCE_POST, row.id) == exclude or policy_key(row.platform) != key:
            continue
        if channel_target and row.target_id != channel_target:
            continue
        times.append(_utc(row.published_at or row.scheduled_at))  # type: ignore[arg-type]
    return times


def check_slot(session: Any, user_id: str, source: str, entry_id: str, candidate: datetime, *,
               now: datetime | None = None) -> SlotCheck:
    moment = _utc(now) or datetime.now(timezone.utc)
    when = _utc(candidate)
    if when is None:
        raise CalendarToolError("scheduled_at is required")
    row = _load(session, user_id, source, entry_id)
    platforms = _platforms_of(source, row)
    hints = best_hours(platforms)
    if when <= moment:
        return SlotCheck(allow=False, reason="That time has already passed.", suggested_at=None, best_hours_utc=hints)
    verdicts: list[PlatformVerdict] = []
    channel_target = row.target_id if source == SOURCE_POST and is_channel(row.platform) else ""
    for platform in platforms:
        recent = _neighbours(session, user_id, platform, when, exclude=(source, entry_id),
                             channel_target=channel_target or "")
        decision = decide(policy_key(platform), when, now=moment, recent_posts=recent)
        reason = "" if decision.allow else _explain(platform, decision.reason)
        verdicts.append(PlatformVerdict(platform=platform, allow=decision.allow, reason=reason,
                                        suggested_at=None if decision.allow else decision.run_at))
    blocked = [v for v in verdicts if not v.allow]
    if not blocked:
        return SlotCheck(allow=True, reason="", suggested_at=None, verdicts=tuple(verdicts), best_hours_utc=hints)
    suggested = max((v.suggested_at for v in blocked if v.suggested_at), default=None)
    return SlotCheck(allow=False, reason=" ".join(v.reason for v in blocked), suggested_at=suggested,
                     verdicts=tuple(verdicts), best_hours_utc=hints)


def _explain(platform: str, reason: str) -> str:
    label = platform_label(platform)
    cfg = platform_config(policy_key(platform))
    if reason.startswith("daily cap"):
        return f"{label} already has {cfg['daily_cap']} posts that day (the daily limit)."
    if reason.startswith("min-gap"):
        return f"{label} posts need at least {cfg['min_gap_h']:g} hours between them."
    return f"{label}: {reason}."


# --------------------------------------------------------------------------- #
# Move
# --------------------------------------------------------------------------- #
def move(session: Any, user_id: str, source: str, entry_id: str, new_at: datetime, *, force: bool = False,
         now: datetime | None = None) -> dict:
    """Move one still-unstarted entry to ``new_at`` after the policy check."""
    moment = _utc(now) or datetime.now(timezone.utc)
    when = _utc(new_at)
    if when is None or when <= moment:
        raise CalendarToolError("pick a time in the future")
    row = _load(session, user_id, source, entry_id)
    if source == SOURCE_NATIVE and row.status != "pending":
        raise CalendarToolError("this publish already started and can no longer move", status_code=409)
    if source == SOURCE_POST and (row.status != POST_SCHEDULED or int(row.attempts or 0) > 0):
        raise CalendarToolError("this post already started and can no longer move", status_code=409)
    check = check_slot(session, user_id, source, entry_id, when, now=moment)
    if not check.allow and not force:
        raise CalendarToolError(check.reason or "that slot is not allowed", status_code=409,
                                details={"check": check.to_record()})
    if source == SOURCE_NATIVE:
        from app.services import calendar as calendar_service

        try:
            calendar_service.reschedule_publish(session, user_id, entry_id, when)
        except PermissionError as exc:
            raise CalendarToolError("calendar entry not found", status_code=404) from exc
        except calendar_service.CalendarError as exc:
            raise CalendarToolError(str(exc), status_code=409) from exc
        session.flush()
        refreshed = session.get(_scheduled_publish_model(), entry_id)
        entry = _native_entry(refreshed)
    else:
        row.scheduled_at = when
        row.next_attempt_at = when
        session.flush()
        entry = _post_entry(row, _channel_labels(session, {row.target_id} if row.target_id else set()))
    return {"entry": entry, "check": check.to_record(), "forced": bool(force and not check.allow)}
