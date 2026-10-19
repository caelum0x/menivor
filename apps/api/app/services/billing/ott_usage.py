"""Hourly OTT meters (MV7, Wave P PM3.1): GB stored, minutes delivered, encode minutes, AI minutes.

Sources, per creator and UTC hour:

* **minutes delivered**: every segment the access layer hands to a player
  (``ott_access.service.segment_url``) adds its length to a Redis counter
  ``ott:usage:delivered:<channel>:<hour>`` (3-day TTL; a Redis outage never
  blocks playback, the count is then lost for that hour and logged);
* **encode minutes**: the source length of every OTT encode job that finished
  in the hour (``ott_encode_jobs``);
* **AI minutes**: media minutes the AI panel processed (MV16 calls
  :func:`count_ai_minutes`);
* **GB stored**: a snapshot of the creator's objects under ``ott-uploads/<user>/``
  and ``ott/<channel>/`` in the OTT bucket, as GB-hours.

:func:`run_hour` writes one ``ott_usage_hours`` row per (creator, hour, meter)
(unique, so a re-run is a no-op) and posts it:

* to **Rago** through the Railyard outbox (``menivor.ott.*``, transaction id
  ``menivor:ott.<meter>:<user>:<hour>``), always, with the full quantity;
* to **Dodo** (``dodo_usage_events``, event id ``ott_<meter>_<user>_<hour>``,
  Dodo's idempotency key) for metered Dodo subscribers only, with the
  *billable* quantity: everything when the creator opted into overage,
  otherwise only what is still inside the month's allowance, so nothing past
  the cap is ever billed without the opt-in.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import ott_plans

SEGMENT_S = 2.0
COUNTER_TTL_S = 3 * 24 * 3600
BACKFILL_HOURS = 48
RAGO_CODES = {
    "gb_stored": "menivor.ott.gb_stored",
    "minutes_delivered": "menivor.ott.minutes_delivered",
    "encode_minutes": "menivor.ott.encode_minutes",
    "ai_minutes": "menivor.ai.minutes",
}
DODO_EVENTS = {meter: f"ott.{meter}" for meter in ott_plans.METERS}
GB = 1024 ** 3


def hour_key(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")


def hour_start(key: str) -> datetime:
    return datetime.strptime(key, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Counters (delivered seconds per channel, AI minutes per creator)
# --------------------------------------------------------------------------- #
class Counter(Protocol):
    def add(self, key: str, amount: float) -> None: ...
    def get(self, key: str) -> float: ...


class RedisCounter:
    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _redis(self) -> Any:
        if self._client is None:
            from app.services.billing.service import _get_redis

            self._client = _get_redis()
        return self._client

    def add(self, key: str, amount: float) -> None:
        client = self._redis()
        client.incrbyfloat(key, float(amount))
        client.expire(key, COUNTER_TTL_S)

    def get(self, key: str) -> float:
        raw = self._redis().get(key)
        return float(raw.decode() if isinstance(raw, bytes) else raw or 0.0)

    def claim(self, key: str, ttl: int) -> bool:
        return bool(self._redis().set(key, "1", nx=True, ex=max(1, int(ttl))))


class MemoryCounter:
    def __init__(self) -> None:
        self.values: dict[str, float] = defaultdict(float)

    def add(self, key: str, amount: float) -> None:
        self.values[key] += float(amount)

    def get(self, key: str) -> float:
        return float(self.values.get(key, 0.0))

    def claim(self, key: str, ttl: int) -> bool:
        if key in self.values:
            return False
        self.values[key] = 1.0
        return True


_COUNTER: Optional[Counter] = None


def counter() -> Counter:
    global _COUNTER
    if _COUNTER is None:
        _COUNTER = RedisCounter()
    return _COUNTER


def _delivered_key(channel_id: str, hour: str) -> str:
    return f"ott:usage:delivered:{channel_id}:{hour}"


def _ai_key(user_id: str, hour: str) -> str:
    return f"ott:usage:ai:{user_id}:{hour}"


def count_delivered(channel_id: str, seconds: float = SEGMENT_S, *, now: Optional[float] = None) -> None:
    """Add delivered media seconds for a channel. Never raises (playback comes first)."""
    try:
        hour = hour_key(datetime.fromtimestamp(now or time.time(), tz=timezone.utc))
        counter().add(_delivered_key(channel_id, hour), seconds)
    except Exception as exc:  # noqa: BLE001 - a counter outage never stops playback
        logger.warning(f"ott usage: delivered seconds not counted: {type(exc).__name__}")


def first_delivery(session_id: str, path: str, client: str = "", *, ttl_s: int = 3600) -> bool:
    """True the first time this playback session (from this client) asks for this segment.

    Verifier fix (Wave P P3): delivered minutes are billed to the creator, so a
    viewer who replays one segment URL in a loop must not add minutes each
    time. Each (grant session, client, segment) counts once for the grant's
    life. A counter without ``claim`` (or an outage) counts nothing new here:
    playback is never blocked.
    """
    import hashlib

    digest = hashlib.sha256(f"{session_id}|{client}|{path}".encode()).hexdigest()[:32]
    try:
        claim = getattr(counter(), "claim", None)
        return True if claim is None else bool(claim(f"ott:usage:seen:{digest}", ttl_s))
    except Exception as exc:  # noqa: BLE001 - a counter outage never stops playback
        logger.warning(f"ott usage: segment dedupe unavailable: {type(exc).__name__}")
        return False


def count_ai_minutes(user_id: str, minutes: float, *, now: Optional[float] = None) -> None:
    try:
        hour = hour_key(datetime.fromtimestamp(now or time.time(), tz=timezone.utc))
        counter().add(_ai_key(user_id, hour), minutes)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"ott usage: AI minutes not counted: {type(exc).__name__}")


# --------------------------------------------------------------------------- #
# Storage size
# --------------------------------------------------------------------------- #
Sizer = Callable[[str], int]


def r2_sizer() -> Sizer:
    """Sum of object sizes under a prefix of the OTT bucket (paged listing)."""
    from app.services.ott_transcode.uploads import R2Storage

    store = R2Storage()

    def size(prefix: str) -> int:
        total = 0
        paginator = store._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=store._bucket, Prefix=prefix):
            total += sum(int(obj.get("Size", 0)) for obj in page.get("Contents", []) or [])
        return total

    return size


# --------------------------------------------------------------------------- #
# Measure and record one hour
# --------------------------------------------------------------------------- #
def measure(session: Session, hour: str, *, counter_: Optional[Counter] = None,
            sizer: Optional[Sizer] = None) -> dict[str, dict[str, float]]:
    """``{user_id: {meter: quantity}}`` for one UTC hour (zero meters omitted)."""
    from app.domains.ott.models import OttChannel
    from app.services.ott_transcode.models import DONE, OttEncodeJob

    counts = counter_ or counter()
    start = hour_start(hour)
    end = start + timedelta(hours=1)
    usage: dict[str, dict[str, float]] = defaultdict(dict)
    channels = session.execute(select(OttChannel.id, OttChannel.user_id)).all()
    for channel_id, user_id in channels:
        seconds = counts.get(_delivered_key(channel_id, hour))
        if seconds > 0:
            usage[user_id]["minutes_delivered"] = usage[user_id].get("minutes_delivered", 0.0) + seconds / 60.0
        ai = counts.get(_ai_key(user_id, hour))
        if ai > 0:
            usage[user_id]["ai_minutes"] = ai
        if sizer is not None:
            stored = sizer(f"ott-uploads/{user_id}/") + sizer(f"ott/{channel_id}/")
            if stored > 0:
                usage[user_id]["gb_stored"] = stored / GB
    jobs = session.execute(
        select(OttEncodeJob.user_id, OttEncodeJob.source_seconds)
        .where(OttEncodeJob.status == DONE, OttEncodeJob.finished_at >= start, OttEncodeJob.finished_at < end)
    ).all()
    for user_id, seconds in jobs:
        usage[user_id]["encode_minutes"] = usage[user_id].get("encode_minutes", 0.0) + float(seconds or 0) / 60.0
    return {uid: meters for uid, meters in usage.items() if meters}


def _billable(session: Session, user_id: str, meter: str, quantity: float, hour: str) -> tuple[float, bool]:
    """(quantity to bill, whether part of it is overage) for one reading."""
    moment = hour_start(hour)
    used = ott_plans.month_to_date(session, user_id, moment, before_hour=hour)[meter]
    remaining = max(0.0, ott_plans.allowance(ott_plans.caps_for(session, user_id), meter, moment) - used)
    if ott_plans.overage_opted_in(session, user_id):
        return quantity, quantity > remaining
    return min(quantity, remaining), False


def _post_dodo(session: Session, row: Any, meter: str, *, overage: bool) -> bool:
    from app.models.db.dodo_usage_event import DodoUsageEvent
    from app.services.billing import dodo_usage

    subscription = dodo_usage.metered_subscription(session, row.user_id)
    if subscription is None or row.billable <= 0:
        return False
    event_id = f"ott_{meter}_{row.user_id}_{row.hour}"
    if session.execute(select(DodoUsageEvent.id).where(DodoUsageEvent.event_id == event_id)).first():
        return False
    session.add(DodoUsageEvent(event_id=event_id, user_id=row.user_id, customer_id=subscription.customer_ref,
                               event_name=DODO_EVENTS[meter], timestamp=hour_start(row.hour) + timedelta(hours=1),
                               meta={"quantity": round(row.billable, 4), "hour": row.hour,
                                     "unit": ott_plans.UNITS[meter]},
                               overage=overage))
    session.flush()
    return True


def run_hour(session: Session, hour: str, *, counter_: Optional[Counter] = None,
             sizer: Optional[Sizer] = None) -> dict[str, int]:
    """Record and post one hour. Idempotent: rows that exist are left alone."""
    from app.domains.ott_viewers.models import OttUsageHour
    from app.integrations.railyard import meters as railyard

    counts = {"rows": 0, "rago": 0, "dodo": 0}
    for user_id, meters in sorted(measure(session, hour, counter_=counter_, sizer=sizer).items()):
        for meter, quantity in sorted(meters.items()):
            exists = session.execute(select(OttUsageHour.id).where(
                OttUsageHour.user_id == user_id, OttUsageHour.hour == hour, OttUsageHour.meter == meter)).first()
            if exists is not None:
                continue
            billable, overage = _billable(session, user_id, meter, quantity, hour)
            row = OttUsageHour(user_id=user_id, hour=hour, meter=meter, quantity=round(quantity, 6),
                               billable=round(billable, 6))
            try:
                with session.begin_nested():
                    session.add(row)
            except IntegrityError:
                continue
            counts["rows"] += 1
            if railyard.record(session, code=RAGO_CODES[meter], source_id=f"{user_id}:{hour}", customer=user_id,
                               timestamp=hour_start(hour).timestamp() + 3600,
                               properties={"quantity": row.quantity, "billable": row.billable,
                                           "unit": ott_plans.UNITS[meter], "hour": hour}):
                counts["rago"] += 1
            if _post_dodo(session, row, meter, overage=overage):
                counts["dodo"] += 1
    session.flush()
    return counts


def due_hours(session: Session, *, now: Optional[datetime] = None, back: int = BACKFILL_HOURS) -> list[str]:
    """Completed hours in the backfill window, oldest first (the current hour is never due)."""
    moment = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    return [hour_key(moment - timedelta(hours=h)) for h in range(back, 0, -1)]


def tick(session: Session, *, now: Optional[datetime] = None, counter_: Optional[Counter] = None,
         sizer: Optional[Sizer] = None, back: int = 2) -> dict[str, int]:
    """The hourly beat: the last ``back`` completed hours (storage is sized once, for the newest)."""
    totals = {"rows": 0, "rago": 0, "dodo": 0}
    hours = due_hours(session, now=now, back=back)
    for hour in hours:
        result = run_hour(session, hour, counter_=counter_, sizer=sizer if hour == hours[-1] else None)
        for key in totals:
            totals[key] += result[key]
    return totals


__all__ = ["DODO_EVENTS", "MemoryCounter", "RAGO_CODES", "RedisCounter", "SEGMENT_S", "count_ai_minutes",
           "count_delivered", "counter", "due_hours", "first_delivery", "hour_key", "hour_start", "measure", "r2_sizer", "run_hour",
           "tick"]


def set_counter(new: Optional[Counter]) -> None:
    """Swap the counter (tests use :class:`MemoryCounter`)."""
    global _COUNTER
    _COUNTER = new
