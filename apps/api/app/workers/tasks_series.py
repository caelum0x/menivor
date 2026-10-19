"""Celery tasks for the unattended channel runner (beat entrypoints).

A separate module from :mod:`app.workers.tasks` so it never overlaps the render
DAG. Two periodic tasks, both wired in ``celery_app.py`` beat:

* :func:`run_series_task` (hourly) — expand each channel's source list into
  de-duplicated render jobs (``runner.run_channel``).
* :func:`schedule_series_publishes_task` (every few minutes) — pace every
  COMPLETE-but-unpublished clip onto the publish calendar (``runner.schedule_due``).

Both honor the sweep never-raise contract (mirrors ``tasks.py`` sweeps): a task
NEVER raises out of its body — any failure degrades to a logged ZEROED summary
dict so a single bad tick can't crash the shared beat scheduler. They are
idempotent via ``fanout.spec_hash`` dedupe / the ``pending`` clip filter, so a
duplicate tick is safe. Only a transient ``ConnectionError`` is allowed to
propagate (Celery ``autoretry_for``); everything else is swallowed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.workers.celery_app import celery_app

_EMPTY_RUN_SUMMARY: dict[str, int] = {
    "channels": 0,
    "rendered": 0,
    "skipped_duplicates": 0,
    "paced_out": 0,
    "enqueue_failures": 0,
}

_EMPTY_SCHEDULE_SUMMARY: dict[str, int] = {
    "channels": 0,
    "considered": 0,
    "scheduled": 0,
}


# --------------------------------------------------------------------------- #
# Wiring impls (patchable seams — the tasks delegate here inside a guard).
# --------------------------------------------------------------------------- #
def _build_config(channel: dict) -> Any:
    """Build a :class:`ChannelRunConfig` from a beat payload channel dict."""
    from app.domains.series.runner import ChannelRunConfig

    return ChannelRunConfig(
        channel_id=str(channel.get("channel_id") or ""),
        user_id=str(channel.get("user_id") or ""),
        hooks=tuple(channel.get("hooks") or ("",)),
        aspects=tuple(channel.get("aspects") or ("9:16",)),
        accounts=tuple(channel.get("accounts") or ("",)),
        max_per_account=channel.get("max_per_account"),
        platforms=tuple(channel.get("platforms") or ()),
        voice_id=channel.get("voice_id"),
        subject=str(channel.get("subject") or ""),
        template_slug=str(channel.get("template_slug") or "minecraft-reddit-split"),
        max_words=int(channel.get("max_words") or 130),
    )


def _make_deps(session: Any) -> Any:
    """Assemble the real :class:`RunnerDeps` for a live session."""
    from app.domains.series.repository import ChannelClipRepository
    from app.domains.series.runner import RunnerDeps
    from app.models.db.repositories import JobRepository
    from app.services import scheduler as scheduler_service
    from app.workers.pipeline import start_pipeline

    return RunnerDeps(
        job_repo=JobRepository(session),
        clip_repo=ChannelClipRepository(session),
        start_pipeline=start_pipeline,
        schedule_publish=scheduler_service.schedule_publish,
        session=session,
    )


def _payload_channels(payload: dict) -> list[dict]:
    """Channels to process: the explicit payload, else every autorun channel.

    Beat ticks carry no payload, so they drive the creator-defined channels
    (``POST /series/channels`` with ``autorun`` on) straight from the DB.
    """
    explicit = list((payload or {}).get("channels") or [])
    if explicit:
        return explicit
    from app.domains.series.channels import autorun_payload
    from app.models.db import base as db_base

    with db_base.get_session() as session:
        return autorun_payload(session)


def _run_series_impl(payload: dict) -> dict[str, int]:
    """Render every channel in ``payload['channels']`` (one committed txn each)."""
    from app.domains.series.runner import items_from_list, run_channel
    from app.models.db import base as db_base

    channels = _payload_channels(payload)
    summary = dict(_EMPTY_RUN_SUMMARY)
    for channel in channels:
        config = _build_config(channel)
        source_items = items_from_list(channel.get("source_items") or [])
        if not source_items:
            continue
        try:
            with db_base.get_session() as session:
                deps = _make_deps(session)
                result = run_channel(config, source_items=source_items, deps=deps)
        except ConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad channel must not stop the rest
            logger.error(f"series run failed for channel {config.channel_id}: {exc}")
            continue
        summary["channels"] += 1
        summary["rendered"] += result.rendered
        summary["skipped_duplicates"] += result.skipped_duplicates
        summary["paced_out"] += result.paced_out
        summary["enqueue_failures"] += result.enqueue_failures
    return summary


def _schedule_series_impl(payload: dict) -> dict[str, int]:
    """Schedule due clips for every channel in ``payload['channels']``."""
    from app.domains.series.runner import schedule_due
    from app.models.db import base as db_base

    channels = _payload_channels(payload)
    now = datetime.now(timezone.utc)
    summary = dict(_EMPTY_SCHEDULE_SUMMARY)
    for channel in channels:
        config = _build_config(channel)
        with db_base.get_session() as session:
            deps = _make_deps(session)
            result = schedule_due(config, now=now, deps=deps)
        summary["channels"] += 1
        summary["considered"] += result.considered
        summary["scheduled"] += result.scheduled
    return summary


# --------------------------------------------------------------------------- #
# Beat tasks (never raise; zeroed summary on any failure).
# --------------------------------------------------------------------------- #
@celery_app.task(
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=600,
    time_limit=660,
)
def run_series_task(self, payload: dict | None = None) -> dict[str, int]:
    """Expand each channel's source list into de-duplicated render jobs.

    NEVER raises (beat-safety): any error other than a transient
    ``ConnectionError`` (which Celery auto-retries) degrades to a logged zeroed
    summary. Idempotent via ``spec_hash`` dedupe, so a duplicate tick is safe.
    """
    try:
        return _run_series_impl(payload or {})
    except ConnectionError:  # transient broker/DB — let Celery autoretry
        raise
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"run_series_task failed: {exc}")
        return dict(_EMPTY_RUN_SUMMARY)


@celery_app.task(
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=120,
    time_limit=180,
)
def schedule_series_publishes_task(self, payload: dict | None = None) -> dict[str, int]:
    """Pace every COMPLETE-but-unpublished clip onto the publish calendar.

    NEVER raises (beat-safety): any error other than a transient
    ``ConnectionError`` degrades to a logged zeroed summary. Idempotent — an
    already-scheduled clip leaves the ``pending`` set, so a duplicate tick is safe.
    """
    try:
        return _schedule_series_impl(payload or {})
    except ConnectionError:  # transient broker/DB — let Celery autoretry
        raise
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"schedule_series_publishes_task failed: {exc}")
        return dict(_EMPTY_SCHEDULE_SUMMARY)


__all__ = [
    "run_series_task",
    "schedule_series_publishes_task",
]
