"""Session-injected persistence for the unattended channel runner.

Mirrors the repo rule used by ``MotionRenderRepository`` / ``RenderJobRepository``:
the repository NEVER opens its own session — the caller owns the transaction and
passes an active :class:`~sqlalchemy.orm.Session`. Two repos:

* :class:`ChannelClipRepository` — the dedupe + publish-scheduling authority.
  ``seen_hashes(channel_id)`` feeds ``plan_fanout(seen_hashes=...)`` so a
  combination already rendered in a PRIOR run is skipped; ``create`` persists a
  clip's ``spec_hash`` after a successful render enqueue; ``list_pending_publish``
  returns clips whose owning job is COMPLETE and which have not yet been queued to
  publish; ``mark_scheduled`` links a clip to its :class:`ScheduledPublish`.
* :class:`ChannelRunRepository` — optional run bookkeeping.

All reads are ``channel_id``-scoped so one channel's runner can never dedupe
against, or publish, another channel's clips.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import const
from app.models.db.models import Job, ScheduledPublish
from app.models.db.series_runs import (
    CLIP_STATUS_FAILED,
    CLIP_STATUS_PENDING,
    CLIP_STATUS_SCHEDULED,
    ChannelClip,
    ChannelRun,
)

#: ``ScheduledPublish.status`` for a resolved (already attempted) publish failure.
_SCHEDULE_STATUS_FAILED = "failed"


def _utc_day_start(now: datetime) -> datetime:
    """Midnight UTC of ``now``'s calendar day (tz-aware)."""
    day = now.astimezone(timezone.utc)
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


class ChannelClipRepository:
    """CRUD + dedupe / publish-scheduling reads for ``channel_clips``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def seen_hashes(self, channel_id: str) -> set[str]:
        """Return every ``spec_hash`` already persisted for ``channel_id``.

        This is the cross-run dedupe set fed back into ``plan_fanout`` so an
        identical (body × hook × template × aspect × account) combination is
        never rendered twice across runs. A blank ``channel_id`` matches nothing.
        """
        normalized = (channel_id or "").strip()
        if not normalized:
            return set()
        stmt = select(ChannelClip.spec_hash).where(
            ChannelClip.channel_id == normalized
        )
        return set(self._session.execute(stmt).scalars().all())

    def create(
        self,
        *,
        channel_id: str,
        run_id: str,
        spec_hash: str,
        job_id: str,
        account: str = "",
        platform: str = "",
        status: str = CLIP_STATUS_PENDING,
    ) -> ChannelClip:
        """Persist a rendered clip (after a successful render enqueue) and flush.

        The ``spec_hash`` becomes visible to the next run's :meth:`seen_hashes`
        — so a clip is only recorded once its render has actually been enqueued,
        keeping a failed-enqueue combination eligible for a later retry.
        """
        row = ChannelClip(
            channel_id=channel_id,
            run_id=run_id,
            spec_hash=spec_hash,
            job_id=job_id,
            account=account or "",
            platform=platform or "",
            status=status or CLIP_STATUS_PENDING,
        )
        self._session.add(row)
        self._session.flush()  # populate row.id without ending the transaction
        return row

    def get(self, clip_id: str) -> ChannelClip | None:
        return self._session.get(ChannelClip, clip_id)

    def list_pending_publish(self, channel_id: str) -> list[ChannelClip]:
        """Return the channel's clips ready to be queued for publishing.

        A clip qualifies when it is still ``pending`` (not yet scheduled), has no
        ``scheduled_publish_id`` and its owning :class:`Job` is COMPLETE — the
        exact set the publish-scheduler paces onto the calendar. Ordered oldest
        first so the earliest-rendered clip is scheduled first.
        """
        normalized = (channel_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(ChannelClip)
            .join(Job, Job.id == ChannelClip.job_id)
            .where(
                ChannelClip.channel_id == normalized,
                ChannelClip.status == CLIP_STATUS_PENDING,
                ChannelClip.scheduled_publish_id.is_(None),
                Job.state == const.TASK_STATE_COMPLETE,
            )
            .order_by(ChannelClip.created_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def mark_scheduled(self, clip_id: str, scheduled_publish_id: str) -> ChannelClip | None:
        """Link a clip to its :class:`ScheduledPublish` and flip it ``scheduled``.

        Returns the updated row, or ``None`` when the clip does not exist.
        """
        row = self._session.get(ChannelClip, clip_id)
        if row is None:
            return None
        row.scheduled_publish_id = scheduled_publish_id
        row.status = CLIP_STATUS_SCHEDULED
        self._session.flush()
        return row

    def mark_failed(self, clip_id: str) -> ChannelClip | None:
        """Flip a clip to ``failed`` (render enqueue reconciled — never published)."""
        row = self._session.get(ChannelClip, clip_id)
        if row is None:
            return None
        row.status = CLIP_STATUS_FAILED
        self._session.flush()
        return row

    def scheduled_run_ats(
        self, channel_id: str, *, now: datetime | None = None
    ) -> list[tuple[str, str, datetime]]:
        """Already-scheduled publish times for this channel's clips, TODAY (UTC).

        Returns ``(account, platform, scheduled_at)`` for every clip already
        linked to a :class:`ScheduledPublish` whose ``scheduled_at`` lands on
        the current UTC day. The publish-scheduler seeds its per-pass recent
        history with these so the per-account daily cap / min-gap are honored
        ACROSS the 5-minute beat ticks (not just within one pass) — otherwise a
        later tick would re-fill the cap it already spent earlier the same day.
        """
        normalized = (channel_id or "").strip()
        if not normalized:
            return []
        day_start = _utc_day_start(now or datetime.now(timezone.utc))
        stmt = (
            select(
                ChannelClip.account,
                ChannelClip.platform,
                ScheduledPublish.scheduled_at,
            )
            .join(ScheduledPublish, ScheduledPublish.id == ChannelClip.scheduled_publish_id)
            .where(
                ChannelClip.channel_id == normalized,
                ChannelClip.scheduled_publish_id.is_not(None),
                ScheduledPublish.scheduled_at >= day_start,
            )
        )
        out: list[tuple[str, str, datetime]] = []
        for account, platform, scheduled_at in self._session.execute(stmt).all():
            if scheduled_at is None:
                continue
            out.append((account or "", platform or "", scheduled_at))
        return out

    def rendered_today_counts(
        self, channel_id: str, *, now: datetime | None = None
    ) -> dict[str, int]:
        """Count of non-failed clips rendered for each account TODAY (UTC).

        The render pace-cap is a per-DAY budget, but a single hourly run only
        sees the specs it just planned. Feeding these counts back lets the runner
        subtract clips already rendered earlier today so 24 hourly ticks cannot
        together blow past the daily cap for one account.
        """
        normalized = (channel_id or "").strip()
        if not normalized:
            return {}
        day_start = _utc_day_start(now or datetime.now(timezone.utc))
        stmt = select(ChannelClip.account).where(
            ChannelClip.channel_id == normalized,
            ChannelClip.status != CLIP_STATUS_FAILED,
            ChannelClip.created_at >= day_start,
        )
        counts: dict[str, int] = {}
        for (account,) in self._session.execute(stmt).all():
            key = account or ""
            counts[key] = counts.get(key, 0) + 1
        return counts

    def consecutive_publish_failures(self, channel_id: str) -> dict[tuple[str, str], int]:
        """Trailing consecutive publish-failure count per ``(account, platform)``.

        For each account+platform, orders that account's scheduled publishes
        newest-first and counts the leading run of ``failed`` rows (stopping at
        the first non-failed). The scheduler feeds this into
        ``scheduling_policy.decide`` so a persistently failing account is backed
        off exponentially instead of being handed a fresh publish every tick.
        """
        normalized = (channel_id or "").strip()
        if not normalized:
            return {}
        stmt = (
            select(
                ChannelClip.account,
                ChannelClip.platform,
                ScheduledPublish.status,
                ScheduledPublish.scheduled_at,
            )
            .join(ScheduledPublish, ScheduledPublish.id == ChannelClip.scheduled_publish_id)
            .where(
                ChannelClip.channel_id == normalized,
                ChannelClip.scheduled_publish_id.is_not(None),
            )
            .order_by(ScheduledPublish.scheduled_at.desc())
        )
        seen_resolved: set[tuple[str, str]] = set()
        failures: dict[tuple[str, str], int] = {}
        for account, platform, status, _scheduled_at in self._session.execute(stmt).all():
            key = (account or "", platform or "")
            if key in seen_resolved:
                continue  # a newer non-failed post already broke this account's streak
            if status == _SCHEDULE_STATUS_FAILED:
                failures[key] = failures.get(key, 0) + 1
            else:
                seen_resolved.add(key)  # streak ends at the first non-failed row
        return failures


class ChannelRunRepository:
    """CRUD for ``channel_runs`` (optional run bookkeeping)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, user_id: str, channel_id: str, params: dict | None = None) -> ChannelRun:
        row = ChannelRun(
            user_id=user_id,
            channel_id=channel_id,
            params=dict(params or {}),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, run_id: str) -> ChannelRun | None:
        return self._session.get(ChannelRun, run_id)

    def list_for_channel(self, channel_id: str, limit: int = 50) -> list[ChannelRun]:
        normalized = (channel_id or "").strip()
        if not normalized:
            return []
        stmt = (
            select(ChannelRun)
            .where(ChannelRun.channel_id == normalized)
            .order_by(ChannelRun.created_at.desc())
            .limit(max(1, limit))
        )
        return list(self._session.execute(stmt).scalars().all())


__all__ = [
    "ChannelClipRepository",
    "ChannelRunRepository",
]
