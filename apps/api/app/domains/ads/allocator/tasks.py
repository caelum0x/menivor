"""Daily allocator proposals (Celery beat).

Opt-in: only users who created at least one proposal in the last
``OPT_IN_DAYS`` get a fresh one each day. A user whose proposal for today
already exists (any status) is skipped, so a duplicate tick is safe. The task
never raises except for transient ``ConnectionError`` (Celery retries it).

:func:`allocator_apply_approved_task` applies proposals approved in the
shared approvals feed (which only records the decision). Each proposal is
applied at most once: :func:`service.apply` moves it to ``applied``/``failed``.

Wiring (celery_app.py): ``include`` ``"app.domains.ads.allocator.tasks"`` and
beat entries for both tasks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

from app.workers.celery_app import celery_app

OPT_IN_DAYS = 30
DAILY_SCHEDULE_S = 24 * 60 * 60.0
APPLY_SCHEDULE_S = 5 * 60.0


def run_daily(now: datetime | None = None) -> dict[str, int]:
    from app.domains.ads.allocation_models import AdAllocationProposal
    from app.domains.ads.allocator import service
    from app.models.db.base import get_session

    now = now or datetime.now(timezone.utc)
    summary = {"users": 0, "proposed": 0, "skipped": 0, "errors": 0}
    with get_session() as session:
        users = service.daily_users(session, now.date() - timedelta(days=OPT_IN_DAYS))
    summary["users"] = len(users)
    for user_id in users:
        try:
            with get_session() as session:
                exists = session.execute(select(AdAllocationProposal.id).where(
                    AdAllocationProposal.user_id == user_id, AdAllocationProposal.run_date == now.date(),
                )).first()
                if exists:
                    summary["skipped"] += 1
                    continue
                service.propose(session, user_id, now=now)
                summary["proposed"] += 1
        except service.AllocatorError as exc:
            summary["skipped"] += 1
            logger.info(f"allocator daily: user {user_id} skipped ({exc.status_code}): {exc.message}")
        except ConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - one user's failure must not stop the others
            summary["errors"] += 1
            logger.error(f"allocator daily: user {user_id} failed: {exc}")
    return summary


@celery_app.task(bind=True, autoretry_for=(ConnectionError,), max_retries=3, retry_backoff=True,
                 soft_time_limit=1800, time_limit=1860)
def allocator_daily_task(self) -> dict[str, int]:
    """Create today's budget-split proposal for every opted-in user. Beat-safe."""
    try:
        summary = run_daily()
        if summary["users"]:
            logger.info(f"allocator daily: {summary}")
        return summary
    except ConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"allocator_daily_task failed: {exc}")
        return {"users": 0, "proposed": 0, "skipped": 0, "errors": 1}


def run_apply_approved(now: datetime | None = None) -> dict[str, int]:
    from app.domains.ads.allocator import service
    from app.models.db.base import get_session

    summary = {"applied": 0, "failed": 0, "errors": 0}
    with get_session() as session:
        waiting = service.approved_waiting(session)
    for user_id, proposal_id in waiting:
        try:
            with get_session() as session:
                view = service.apply_approved(session, user_id, proposal_id, now=now)
            summary["applied" if view["status"] == "applied" else "failed"] += 1
        except service.AllocatorError:
            continue  # decided or applied concurrently
        except ConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - one proposal must not stop the rest
            summary["errors"] += 1
            logger.error(f"allocator apply: proposal {proposal_id} failed: {exc}")
    return summary


@celery_app.task(bind=True, autoretry_for=(ConnectionError,), max_retries=3, retry_backoff=True,
                 soft_time_limit=240, time_limit=270)
def allocator_apply_approved_task(self) -> dict[str, int]:
    """Apply budget splits approved in the approvals feed. Beat-safe."""
    try:
        summary = run_apply_approved()
        if any(summary.values()):
            logger.info(f"allocator apply: {summary}")
        return summary
    except ConnectionError:
        raise
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"allocator_apply_approved_task failed: {exc}")
        return {"applied": 0, "failed": 0, "errors": 1}


__all__ = ["APPLY_SCHEDULE_S", "DAILY_SCHEDULE_S", "allocator_apply_approved_task", "allocator_daily_task",
           "run_apply_approved", "run_daily"]
