"""Routines: scheduled agent jobs such as "3 new ad variations every Monday".

A routine never spends or publishes by itself. When it is due, the beat tick
(:mod:`app.domains.brand_agent.tasks`) creates one ``pending`` routine-batch
action in the approval gate and moves ``next_run_at`` forward with a guarded
update, so a re-run of the same tick creates nothing twice. Times are UTC.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent import gate
from app.domains.brand_agent.models import AgentRoutine

UTC = timezone.utc
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
#: Skills a routine may run, and the media each one makes.
ROUTINE_SKILLS: dict[str, str] = {
    "ad_variations": "image",
    "hook_variations": "image",
    "image_ad": "image",
    "video_ad": "video",
    "ugc_script": "video",
}
DEFAULT_HOUR = 9
MAX_COUNT = 10
MAX_ROUTINES = 25
MAX_DUE_PER_TICK = 200

_EVERY_RE = re.compile(r"\bevery\s+(" + "|".join(WEEKDAYS) + r")\b", re.I)
_DAILY_RE = re.compile(r"\b(?:daily|every\s*day|each\s+day)\b", re.I)
_COUNT_RE = re.compile(r"\b(\d{1,2})\b")
_HOUR_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_SKILL_WORDS = (
    ("hook", "hook_variations"),
    ("script", "ugc_script"),
    ("video", "video_ad"),
    ("image", "image_ad"),
    ("variation", "ad_variations"),
    ("ad", "ad_variations"),
)


class RoutineError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_schedule(text: str) -> dict[str, Any] | None:
    """``"3 new ad variations every Monday"`` -> ``{count, weekday, hour, skill}``; None if no schedule."""
    value = str(text or "")
    weekly = _EVERY_RE.search(value)
    daily = _DAILY_RE.search(value)
    if not weekly and not daily:
        return None
    hour_match = _HOUR_RE.search(value)
    hour = DEFAULT_HOUR
    if hour_match:
        hour = int(hour_match.group(1)) % 24
        if (hour_match.group(3) or "").lower() == "pm" and hour < 12:
            hour += 12
    without_time = _HOUR_RE.sub(" ", value)
    count_match = _COUNT_RE.search(without_time)
    lowered = value.lower()
    skill = next((s for word, s in _SKILL_WORDS if word in lowered), "ad_variations")
    return {
        "count": int(count_match.group(1)) if count_match else 1,
        "weekday": WEEKDAYS.index(weekly.group(1).lower()) if weekly else None,
        "hour": hour,
        "skill": skill,
    }


def validate(*, count: int, hour: int, weekday: int | None, skill: str) -> None:
    if not 1 <= int(count) <= MAX_COUNT:
        raise RoutineError(f"A routine makes 1 to {MAX_COUNT} items per run.")
    if not 0 <= int(hour) <= 23:
        raise RoutineError("Pick an hour from 0 to 23 (UTC).")
    if weekday is not None and not 0 <= int(weekday) <= 6:
        raise RoutineError("Pick a weekday from Monday to Sunday.")
    if skill not in ROUTINE_SKILLS:
        raise RoutineError("That skill cannot run on a schedule.")


def next_run(*, weekday: int | None, hour: int, after: datetime) -> datetime:
    """The first slot strictly after ``after`` (UTC)."""
    base = _aware(after)
    candidate = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    if weekday is None:
        return candidate if candidate > base else candidate + timedelta(days=1)
    candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
    return candidate if candidate > base else candidate + timedelta(days=7)


def view(row: AgentRoutine) -> dict[str, Any]:
    return {
        "id": row.id,
        "space_id": row.space_id,
        "name": row.name,
        "skill": row.skill,
        "count": row.count,
        "weekday": row.weekday,
        "weekday_name": WEEKDAYS[row.weekday].capitalize() if row.weekday is not None else "Every day",
        "hour": row.hour,
        "enabled": bool(row.enabled),
        "requires_approval": True,
        "next_run_at": _aware(row.next_run_at).isoformat() if row.next_run_at else None,
        "last_run_at": _aware(row.last_run_at).isoformat() if row.last_run_at else None,
    }


def describe(rule: dict[str, Any]) -> str:
    when = f"every {WEEKDAYS[rule['weekday']].capitalize()}" if rule.get("weekday") is not None else "every day"
    return f"{rule['count']} x {rule['skill'].replace('_', ' ')} {when} at {rule['hour']:02d}:00 UTC"


def list_routines(session: Any, user_id: str, space_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(AgentRoutine).where(AgentRoutine.user_id == user_id)
    if space_id:
        stmt = stmt.where(AgentRoutine.space_id == space_id)
    return [view(r) for r in session.execute(stmt.order_by(AgentRoutine.created_at)).scalars().all()]


def create(session: Any, user_id: str, space_id: str, *, name: str, skill: str, count: int, weekday: int | None,
           hour: int, now: datetime | None = None) -> dict[str, Any]:
    validate(count=count, hour=hour, weekday=weekday, skill=skill)
    if len(list_routines(session, user_id)) >= MAX_ROUTINES:
        raise RoutineError(f"You can have up to {MAX_ROUTINES} routines.")
    moment = now or datetime.now(UTC)
    row = AgentRoutine(user_id=user_id, space_id=space_id, name=clean_text(name, 200) or skill, skill=skill,
                       count=int(count), weekday=weekday, hour=int(hour), enabled=True,
                       next_run_at=next_run(weekday=weekday, hour=int(hour), after=moment))
    session.add(row)
    session.flush()
    return view(row)


def _get(session: Any, user_id: str, routine_id: str) -> AgentRoutine:
    row = session.get(AgentRoutine, routine_id) if routine_id else None
    if row is None or row.user_id != user_id:
        raise RoutineError("routine not found", 404)
    return row


def update_routine(session: Any, user_id: str, routine_id: str, *, enabled: bool | None = None,
                   count: int | None = None, hour: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    row = _get(session, user_id, routine_id)
    new_count = row.count if count is None else int(count)
    new_hour = row.hour if hour is None else int(hour)
    validate(count=new_count, hour=new_hour, weekday=row.weekday, skill=row.skill)
    row.count, row.hour = new_count, new_hour
    if enabled is not None:
        row.enabled = bool(enabled)
    if hour is not None or enabled:
        row.next_run_at = next_run(weekday=row.weekday, hour=new_hour, after=now or datetime.now(UTC))
    session.flush()
    return view(row)


update = update_routine


def delete(session: Any, user_id: str, routine_id: str) -> None:
    session.delete(_get(session, user_id, routine_id))
    session.flush()


def run_due(session: Any, *, now: datetime | None = None, limit: int = MAX_DUE_PER_TICK) -> int:
    """Create one pending batch action per due routine. Returns how many ran."""
    from sqlalchemy import update as sql_update

    moment = _aware(now or datetime.now(UTC))
    due = session.execute(
        select(AgentRoutine).where(AgentRoutine.enabled.is_(True), AgentRoutine.next_run_at <= moment)
        .order_by(AgentRoutine.next_run_at).limit(limit)
    ).scalars().all()
    ran = 0
    for row in due:
        scheduled = row.next_run_at
        following = next_run(weekday=row.weekday, hour=row.hour, after=moment)
        claimed = session.execute(
            sql_update(AgentRoutine)
            .where(AgentRoutine.id == row.id, AgentRoutine.next_run_at == scheduled)
            .values(next_run_at=following, last_run_at=moment)
            .execution_options(synchronize_session=False)
        ).rowcount
        if not claimed:
            continue
        try:
            gate.propose(session, row.user_id, row.space_id, None, kind=gate.KIND_ROUTINE_BATCH,
                         title=f"{row.name}: {row.count} new {row.skill.replace('_', ' ')}",
                         payload={"count": row.count, "skill": row.skill, "media": ROUTINE_SKILLS[row.skill],
                                  "prompt": f"{row.skill.replace('_', ' ')} for this week"},
                         routine_id=row.id)
        except Exception as exc:  # noqa: BLE001 - one bad routine never stops the tick
            logger.warning(f"brand agent routine {row.id} failed to queue: {type(exc).__name__}")
            continue
        ran += 1
    session.flush()
    return ran


__all__ = [
    "ROUTINE_SKILLS",
    "RoutineError",
    "WEEKDAYS",
    "create",
    "delete",
    "describe",
    "list_routines",
    "next_run",
    "parse_schedule",
    "run_due",
    "update",
    "validate",
    "view",
]
