"""Publishing port: schedule a finished reel through Menivor's scheduled publishing.

``publish(*, session, user_id, payload) -> dict`` where ``payload`` carries
``job_id``, ``platforms`` and optional ``scheduled_at`` (ISO, default +10 min).
The default calls :func:`app.services.scheduler.schedule_publish`, which checks
the job belongs to the user and is complete. Only ever called after approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .base import PortUnavailable

DEFAULT_DELAY = timedelta(minutes=10)


class PublishPort(Protocol):
    def publish(self, *, session: Any, user_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class SchedulerPublisher:
    def publish(self, *, session: Any, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from app.services import scheduler

        job_id = str(payload.get("job_id") or "").strip()
        if not job_id:
            raise PortUnavailable("Pick a finished video from your Library to publish first.")
        raw_when = str(payload.get("scheduled_at") or "")
        try:
            when = datetime.fromisoformat(raw_when) if raw_when else datetime.now(timezone.utc) + DEFAULT_DELAY
        except ValueError as exc:
            raise PortUnavailable("The publish time is not a valid date.") from exc
        try:
            row = scheduler.schedule_publish(session, user_id, job_id, list(payload.get("platforms") or []), when)
        except (ValueError, LookupError, PermissionError) as exc:
            raise PortUnavailable(str(exc)[:200]) from exc
        return {"status": "scheduled", "ref": str(getattr(row, "id", "")), "scheduled_at": when.isoformat()}


def get_port() -> PublishPort:
    return SchedulerPublisher()


__all__ = ["PublishPort", "SchedulerPublisher", "get_port"]
