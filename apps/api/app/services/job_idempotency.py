"""Lifecycle management for durable ``POST /jobs`` idempotency records.

The request rows must survive transient client retries, yet need no indefinite
retention: the authoritative job and immutable credit ledger retain operational
and financial history.  This module is deliberately small so Celery beat can
run it without importing the API controller.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import config
from app.models.db.base import get_session
from app.models.db.repositories import JobRequestRepository

_DEFAULT_RETENTION_HOURS = 24
_DEFAULT_SWEEP_LIMIT = 1_000


def _retention_hours() -> int:
    """Return a safe, bounded replay window from application configuration."""
    try:
        configured = int(
            config.app.get(
                "reelforge_idempotency_retention_hours", _DEFAULT_RETENTION_HOURS
            )
        )
    except (TypeError, ValueError):
        return _DEFAULT_RETENTION_HOURS
    return max(1, min(configured, 24 * 31))


def sweep_expired_job_requests(
    *, now: datetime | None = None, limit: int = _DEFAULT_SWEEP_LIMIT
) -> dict[str, int]:
    """Delete at most ``limit`` idempotency rows older than the retry window."""
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(hours=_retention_hours())
    with get_session() as session:
        deleted = JobRequestRepository(session).delete_created_before(cutoff, limit)
    return {"deleted": deleted}
