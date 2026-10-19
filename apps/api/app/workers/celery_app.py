"""ReelForge Celery application (INTEGRATION_CONTRACT.md §6.1).

Broker and result backend both point at the existing MPT Redis instance. The
URL is composed from the ``[app]`` redis keys (``redis_host`` / ``redis_port`` /
``redis_db`` / ``redis_password``), honouring the optional ``celery_broker_url``
/ ``celery_result_backend`` overrides. No separate ``[redis]`` config section is
introduced (§3.3).

The slow, GPU/render-heavy stages (``avatar`` and ``compose``) are routed to a
dedicated ``render`` queue so a separate worker pool can service them without
starving the fast text/audio stages.
"""

from __future__ import annotations

import importlib
import importlib.util

from celery import Celery

from app.bootstrap import ensure_runtime_directories
from app.config import config

ensure_runtime_directories()

# Task modules owned by packages that may land after this file (M1.5 registers
# them for their owners). A module that is not in the tree yet is skipped, never
# imported, so a worker can always start.
_OPTIONAL_TASK_MODULES: tuple[str, ...] = (
    # MG1: delete means delete (erasure follow-ups: Dodo, R2, Clerk).
    "app.workers.tasks_erasure",
    # MN8: webhook delivery retries (backoff, then dead) and job.failed events.
    "app.workers.tasks_webhooks",
    # Multi-account publishing: paced queue runner, status sweep, token refresh.
    "app.domains.multipost.tasks",
    # MN5: content reports left open for 24 h are soft-blocked.
    "app.workers.tasks_takedown",
    # MH0: weekly media-catalog price drift check (owner alert over 10%).
    "app.services.loops.price_drift",
    # Wave P PM1.3: count kept gallery Recreate remixes (remix_count, idempotent).
    "app.domains.gallery.tasks",
    # Wave P PM1.4: refund AI-video credits of failed My-characters trainings (once per job).
    "app.domains.characters.hub_tasks",
    # Wave P PM1.5: Railyard meter outbox retry (Rago usage events, idempotent).
    "app.integrations.railyard.tasks",
    # Wave P PM2.1: story-in-8-frames renders and upscale jobs (worker tasks, no beat).
    "app.domains.film.story8_tasks",
    # Ad Clone: approved paid renders (Kling + lip-sync, re-scheduled ticks, settled credits).
    "app.domains.adclone.render_tasks",
    "app.services.enhance.tasks",
    # Wave P PM2.2: apps shelf runs and talking-scene steps (worker tasks, no beat).
    "app.domains.apps_shelf.tasks",
    # Wave P PM2.3: OTT publish sweep (takedown-blocked titles hidden, idempotent).
    "app.domains.ott.tasks",
    # Wave P PM2.4: OTT transcode and packaging jobs; stale Mac-node claims requeued.
    "app.workers.tasks_ott",
    # Wave P PM3.0 (MH9): the weekly preset drop (Mondays; publishes only with 3+ ready previews).
    "app.services.loops.preset_drop_tasks",
    # Wave P PM3.1 (MV7): hourly OTT usage (GB stored, minutes delivered, encode and AI minutes).
    "app.services.billing.ott_usage_tasks",
    # Wave P PM3.2 (MV13): Mint entitlement reconcile (a missed webhook is caught up, idempotent).
    "app.domains.ott_commerce.tasks",
    # Wave P PM3.4 (MV10): live recordings become VOD titles; stale live streams closed.
    "app.domains.ott_live.tasks",
    # Wave P PM3.5 (MV12, MV16, MV19): QoE hourly rollup, AI panel jobs, discovery index.
    "app.domains.ott_analytics.tasks",
    "app.domains.ott_ai.tasks",
    "app.domains.ott_discovery.tasks",
    # Wave Q QM1.5 (U39): ott.title.published / ott.purchase.granted / ott.live.started, sent after commit.
    "app.domains.ott.events",
    # Brand Agent: due routines become pending approval actions (never spend on their own).
    "app.domains.brand_agent.tasks",
    # Wave 2: daily competitor refresh (official ad libraries), workflow schedules (pending actions only)
    # and the approved studio-render worker (actor shots, lip-sync translations).
    "app.domains.competitors.tasks",
    "app.domains.workflows.tasks",
    "app.domains.studio_render.tasks",
    # Menivor Growth phase 2: daily top-50 App Store keyword rank refresh.
    "app.domains.keyword_tracker.tasks",
)


def _present(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


OPTIONAL_TASK_MODULES: list[str] = [m for m in _OPTIONAL_TASK_MODULES if _present(m)]


def _redis_url() -> str:
    """Compose the Redis connection URL from the ``[app]`` config keys.

    Prefers an explicit ``celery_broker_url`` override; otherwise builds
    ``redis://[:password@]host:port/db`` from the existing MPT redis keys.
    """
    pw = config.app.get("redis_password", "")
    auth = f":{pw}@" if pw else ""
    return (
        config.app.get("celery_broker_url")
        or f"redis://{auth}{config.app.get('redis_host', 'localhost')}:"
        f"{config.app.get('redis_port', 6379)}/{config.app.get('redis_db', 0)}"
    )


celery_app = Celery(
    "reelforge",
    broker=_redis_url(),
    backend=config.app.get("celery_result_backend") or _redis_url(),
    include=[
        "app.workers.tasks",
        "app.workers.tasks_series",
        "app.workers.tasks_film",
        "app.workers.tasks_insights",
        "app.domains.adstudio.tasks",
        "app.domains.social_inbox.tasks",
        "app.domains.capture.tasks",
        # Content Month: carousel slideshow MP4 (FFmpeg) on the render queue.
        "app.domains.content_month.tasks",
        "app.domains.ads.allocator.tasks",
        "app.domains.dub.tasks",
        "app.workers.tasks_funnel",
        "app.domains.performance.tasks",
        "app.workers.tasks_reaper",
        # M1.5: canary reel, render alerts, daily economics email.
        "app.workers.tasks_canary",
        # MN5: compose stage that tags the final MP4 as AI-generated.
        "app.workers.tasks_provenance",
        # Wave E M-5 (MR3): onboarding mail Day 0/1/3/7, stops after payment.
        "app.workers.tasks_lifecycle",
        *OPTIONAL_TASK_MODULES,
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_routes={
        "app.workers.tasks.stage_avatar_task": {"queue": "render"},
        "app.workers.tasks.stage_compose_task": {"queue": "render"},
        # MN5: compose + provenance tag (the callback pipeline.py enqueues).
        "app.workers.tasks_provenance.stage_compose_task": {"queue": "render"},
        "app.workers.tasks.export_editor_cut_task": {"queue": "render"},
        # AI B-roll generation is GPU work isolated from standard render tasks.
        "app.workers.tasks.generate_broll_clip_task": {"queue": "generation"},
        # Pay-as-you-go marketplace generation (routing engine -> provider adapter).
        "app.workers.tasks.run_marketplace_generation_task": {"queue": "generation"},
        "app.workers.tasks.run_marketplace_reel_task": {"queue": "generation"},
        # Dub any video: one-shot pyvideotrans container (CPU heavy, one per host).
        "app.domains.dub.tasks.run_dub_video_task": {"queue": "generation"},
        # Licensed Pixelle engine tasks run only on the separately scalable GPU
        # worker; the API process never executes generation work.
        "app.generation.tasks.*": {"queue": "generation"},
        # Unattended channel runner: the hourly render pass is light matrix
        # expansion + enqueue (generation queue); the publish-scheduling pass
        # only writes calendar rows (render queue, alongside the DAG it feeds).
        "app.workers.tasks_series.run_series_task": {"queue": "generation"},
        "app.workers.tasks_series.schedule_series_publishes_task": {"queue": "render"},
        # Film final export: download shot outputs + FFmpeg concat + R2 upload.
        "app.workers.tasks_film.export_film_task": {"queue": "render"},
        # Winner loop tick: DB + platform-metrics HTTP only (no GPU).
        "app.workers.tasks_insights.winner_loop_tick_task": {"queue": "render"},
        # Results tick: DB + platform-metrics HTTP only (no GPU).
        "app.domains.performance.tasks.performance_tick_task": {"queue": "render"},
        # Ad Studio FFmpeg renders (only when adstudio_render_executor="celery").
        "app.domains.adstudio.tasks.render_ad_variant_task": {"queue": "render"},
        # URL capture (headless browser / store slideshow; only when capture_executor="celery").
        "app.domains.capture.tasks.run_capture_task": {"queue": "render"},
        "app.domains.content_month.tasks.render_month_video_task": {"queue": "render"},
        # Daily cross-network budget proposals: DB + ad-platform HTTP only.
        "app.domains.ads.allocator.tasks.allocator_daily_task": {"queue": "render"},
        "app.domains.ads.allocator.tasks.allocator_apply_approved_task": {"queue": "render"},
    },
)

# Periodic (Celery beat) schedule. The scheduled-publishing due-runner fires
# once a minute: it claims every ``pending`` schedule whose UTC time has arrived
# and publishes it (see ``app.services.scheduler.process_due_publishes``). Run a
# single beat process alongside the worker(s) — ``celery -A app.workers.celery_app
# beat`` (the ``beat`` service in docker-compose.reelforge.yml). The runner is
# idempotent (claimed rows are not re-claimed), so a duplicate tick is safe.
celery_app.conf.beat_schedule = {
    # Dodo Payments usage events (metered monthly plans): retry the outbox.
    "menivor-flush-dodo-usage": {
        "task": "app.workers.tasks.flush_dodo_usage_task",
        "schedule": 60.0,
    },
    "reelforge-process-due-publishes": {
        "task": "app.workers.tasks.process_due_publishes_task",
        "schedule": 60.0,
    },
    # Instagram containers / TikTok publish_ids finish ingesting asynchronously;
    # re-poll "processing" publishes until they are live (or fail).
    "reelforge-sweep-processing-publishes": {
        "task": "app.workers.tasks.sweep_processing_publishes_task",
        "schedule": 60.0,
    },
    "reelforge-sweep-oauth-token-refresh": {
        "task": "app.workers.tasks.sweep_oauth_token_refresh_task",
        "schedule": 5 * 60.0,
    },
    # Advance active async-GPU render jobs to terminal + settle/refund the wallet.
    "reelforge-sweep-render-jobs": {
        "task": "app.workers.tasks.sweep_render_jobs_task",
        "schedule": 20.0,
    },
    # Recover unified media-gateway provider jobs even when no client is open.
    # The sweep reuses the same idempotent success-only settlement path as GET
    # /media/videos/{id}; transient failures retain the hold for the next pass.
    "reelforge-sweep-media-gateway-jobs": {
        "task": "app.workers.tasks.sweep_media_gateway_jobs_task",
        "schedule": 20.0,
    },
    # Recover a Mint capture/release missed when a worker died between marking a
    # job terminal and running its money hook. Operations replay idempotently.
    "reelforge-reconcile-mint-settlements": {
        "task": "app.workers.tasks.reconcile_mint_settlements_task",
        "schedule": 60.0,
    },
    # Replay durable person-to-person transfer commands whose Mint response or
    # local result commit was interrupted.  Short DB leases coordinate workers;
    # Mint's stable operation and the attestation-gated finalizer make replay
    # safe even when an API retry races this sweep.
    "reelforge-reconcile-wallet-transfers": {
        "task": "app.workers.tasks.reconcile_wallet_transfers_task",
        "schedule": 30.0,
    },
    # Stuck-reel reaper: a reel with no progress for 2x its stage limit (plus
    # its fair wait for a render slot) is retried once, then stopped with every
    # credit returned and the owner told (app/workers/tasks_reaper.py).
    "menivor-reap-stalled-reels": {
        "task": "app.workers.tasks_reaper.reap_stalled_reels_task",
        "schedule": 60.0,
    },
    "reelforge-sweep-job-idempotency": {
        "task": "app.workers.tasks.sweep_job_idempotency_task",
        "schedule": 24 * 60 * 60.0,
    },
    # Compliance data-retention sweep (Epic 5). Fires once a day: for each
    # workspace RetentionPolicy it soft-purges/anonymizes that workspace's
    # members' jobs + assets older than the configured window (see
    # ``app.services.compliance.retention.sweep_retention``). Scoped strictly to
    # each target workspace and idempotent (re-anonymizing blanked rows is a
    # no-op), so a duplicate daily tick is safe.
    "reelforge-sweep-retention": {
        "task": "app.workers.tasks.sweep_retention_task",
        "schedule": 24 * 60 * 60.0,
    },
    # Unattended channel runner (mirrors the process-due-publishes pair). The
    # hourly pass expands each channel's source list into de-duplicated render
    # jobs; the 5-minute pass paces every COMPLETE-but-unpublished clip onto the
    # publish calendar (then the existing process-due-publishes beat cross-posts
    # them). Both tasks NEVER raise and are idempotent (spec_hash dedupe / the
    # pending-clip filter), so a duplicate tick is safe.
    # Shared trends feed refresh from operator-configured targets
    # (TREND_AUTOPULL_TARGETS + TREND_PULL_ALLOWLIST); a no-op when unset.
    "reelforge-autopull-trends": {
        "task": "app.workers.tasks.autopull_trends_task",
        "schedule": 6 * 60 * 60.0,
    },
    "reelforge-run-channels": {
        "task": "app.workers.tasks_series.run_series_task",
        "schedule": 60 * 60.0,
    },
    "reelforge-schedule-series-publishes": {
        "task": "app.workers.tasks_series.schedule_series_publishes_task",
        "schedule": 5 * 60.0,
    },
    # Publish -> measure -> rank -> remake loop over opted-in batches.
    "reelforge-winner-loop-tick": {
        "task": "app.workers.tasks_insights.winner_loop_tick_task",
        "schedule": 15 * 60.0,
    },
    # Results: read each posted reel's numbers on a schedule (connected accounts + pasted links).
    "menivor-performance-tick": {
        "task": "app.domains.performance.tasks.performance_tick_task",
        "schedule": 10 * 60.0,
    },
    # Social inbox: discover Menivor-published posts + poll due comments/DMs.
    "reelforge-social-inbox-poll": {
        "task": "app.domains.social_inbox.tasks.social_inbox_poll_task",
        "schedule": 5 * 60.0,
    },
    # Cross-network ad budget split: one proposal per opted-in user per day,
    # queued in the approvals feed (never applied without approval by default).
    "menivor-ads-allocator-daily": {
        "task": "app.domains.ads.allocator.tasks.allocator_daily_task",
        "schedule": 24 * 60 * 60.0,
    },
    # Apply budget splits approved in the approvals feed (it only records the decision).
    "menivor-ads-allocator-apply-approved": {
        "task": "app.domains.ads.allocator.tasks.allocator_apply_approved_task",
        "schedule": 5 * 60.0,
    },
}

# Activation funnel: daily sync of first-time steps (07:00 UTC) and the weekly
# owner funnel email, sent once per week from Monday 07:00 UTC (the Monday
# retries resend only if the first send failed). Declared here, not only in the
# task module, so beat always has it. See app/workers/tasks_funnel.py.
from celery.schedules import crontab  # noqa: E402

celery_app.conf.beat_schedule.update(
    {
        "menivor-funnel-daily": {
            "task": "app.workers.tasks_funnel.funnel_tick_task",
            "schedule": crontab(minute=0, hour=7),
        },
        "menivor-funnel-monday-retry": {
            "task": "app.workers.tasks_funnel.funnel_tick_task",
            "schedule": crontab(minute=30, hour="7-11", day_of_week="mon"),
        },
    }
)
celery_app.conf.task_routes["app.workers.tasks_funnel.funnel_tick_task"] = {"queue": "render"}

# M1.5 stage metrics and canary (app/workers/tasks_canary.py). All four are
# light DB/HTTP ticks; housekeeping_beat below moves them to that queue. The
# canary's own render goes through the normal pipeline like any other reel.
celery_app.conf.beat_schedule.update(
    {
        "menivor-canary-reel": {
            "task": "app.workers.tasks_canary.canary_reel_task",
            "schedule": 6 * 60 * 60.0,
        },
        "menivor-canary-check": {
            "task": "app.workers.tasks_canary.canary_check_task",
            "schedule": 5 * 60.0,
        },
        "menivor-render-alerts": {
            "task": "app.workers.tasks_canary.render_alerts_task",
            "schedule": 5 * 60.0,
        },
        "menivor-economics-daily": {
            "task": "app.workers.tasks_canary.economics_daily_task",
            "schedule": crontab(minute=15, hour=7),
        },
    }
)


# Wave E M-5 (MR3): hourly onboarding mail tick (idempotent; each step once).
celery_app.conf.beat_schedule.update(
    {
        "menivor-onboarding-mail": {
            "task": "app.workers.tasks_lifecycle.onboarding_mail_tick_task",
            "schedule": 60 * 60.0,
        },
    }
)


def _optional_beat_entries() -> dict[str, dict]:
    """Beat entries an optional task module exposes as ``BEAT_SCHEDULE``."""
    entries: dict[str, dict] = {}
    for module in OPTIONAL_TASK_MODULES:
        try:
            mod = importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - a broken optional module never blocks the app
            from loguru import logger

            logger.error(f"optional task module {module} failed to import: {exc}")
            continue
        schedule = getattr(mod, "BEAT_SCHEDULE", None)
        if isinstance(schedule, dict):
            entries.update(schedule)
    return entries

# Housekeeping isolation. Every beat-scheduled task (sweeps, reconcilers, the
# publish due-runner, funnel/allocator/winner ticks) runs on its own lightweight
# ``housekeeping`` queue served by a dedicated small worker, so a long reel
# render never delays a sweep and a pile of sweeps never delays a render (on
# box 1, 254 sweeps once queued behind a single render). Each tick also carries
# an ``expires`` equal to its period: a tick nobody picked up before the next
# one is due is dropped instead of piling up, because every beat task is an
# idempotent "process whatever is due now" pass. Workers that must consume it:
# the box stack's ``housekeeping`` service, and the single dev worker
# (``-Q celery,render,generation,housekeeping``).
HOUSEKEEPING_QUEUE = "housekeeping"
# Upper bound for a crontab / long-period tick waiting in the queue.
_MAX_TICK_EXPIRES_S = 3600.0


def _tick_expires(schedule: object) -> float:
    seconds = float(schedule) if isinstance(schedule, (int, float)) else _MAX_TICK_EXPIRES_S
    return max(15.0, min(seconds, _MAX_TICK_EXPIRES_S))


def housekeeping_beat(entries: dict[str, dict]) -> dict[str, dict]:
    """Return ``entries`` routed to the housekeeping queue with a tick expiry.

    Also registers each task's route so a manual ``.delay()`` of the same task
    lands on the housekeeping worker too. Modules that add beat entries after
    this one (``tasks_engagement``) must pass them through here.
    """
    routed: dict[str, dict] = {}
    for name, entry in entries.items():
        celery_app.conf.task_routes[entry["task"]] = {"queue": HOUSEKEEPING_QUEUE}
        routed[name] = {
            **entry,
            "options": {
                **entry.get("options", {}),
                "queue": HOUSEKEEPING_QUEUE,
                "expires": _tick_expires(entry["schedule"]),
            },
        }
    return routed


celery_app.conf.beat_schedule.update(_optional_beat_entries())
celery_app.conf.beat_schedule = housekeeping_beat(celery_app.conf.beat_schedule)

# Render lanes (M1.3, app/domains/reels/policy.py). With the Redis broker a
# worker listening on several queues takes them round-robin; lanes need strict
# order (paid, first reel, free, variants, bulk), so the broker polls queues in
# the order the worker's ``-Q`` lists them. Only switched on with the lanes, so
# today's workers keep their current behaviour. Start render workers with
# ``-Q $(python -c 'from app.domains.reels.policy import worker_queue_order as w; print(w())')``.
from app.domains.reels.policy import lanes_enabled  # noqa: E402

if lanes_enabled():
    celery_app.conf.broker_transport_options = {
        **(celery_app.conf.broker_transport_options or {}),
        "queue_order_strategy": "priority",
    }

# Wire Sentry for the worker process. NO-OP when [sentry].dsn is unset and
# idempotent (init_sentry guards against double-init), so importing this module
# in the API process or in tests never double-registers integrations or raises.
from app.telemetry.sentry import init_sentry  # noqa: E402

init_sentry("worker")


# Register credential-backed provider adapters once per worker process (Phase
# M3). Connected as a signal so it runs only when a real worker forks — never on
# module import (API process / tests). Credential-gated + guarded so an
# unconfigured provider is skipped and a failure never blocks the worker.
from celery.signals import worker_process_init  # noqa: E402


@worker_process_init.connect
def _register_provider_adapters(**_kwargs) -> None:  # pragma: no cover - worker only
    try:
        from app.domains.routing.runtime import ensure_adapters_registered

        ensure_adapters_registered()
    except Exception as exc:  # noqa: BLE001 - never block worker startup
        from loguru import logger

        logger.warning(f"provider adapter registration skipped: {exc}")
