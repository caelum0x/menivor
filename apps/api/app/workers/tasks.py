"""ReelForge Celery stage tasks (INTEGRATION_CONTRACT.md §6.3).

Each task is a thin, retry-aware wrapper around a pure stage function in
``app.services.reelforge``. A task:

  1. reports ``running`` (JobEvent + Job.stages),
  2. runs the stage function on the shared ``JobContext`` dict,
  3. reports ``complete`` and advances weighted progress,
  4. returns ``{**ctx, **stage_result}`` so the next task receives the union.

On terminal failure (after retries are exhausted) Celery calls ``on_failure``,
which records a ``failed`` JobEvent and invokes ``JobRepository.mark_failed``
(first-failure guard — earliest root cause wins).

All state-reporting side effects (telemetry + DB writes) are best-effort: they
are wrapped so a telemetry/DB hiccup can never crash the render pipeline. Only
the stage function's own exception drives retry/failure semantics.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from app.telemetry.events import record_event
from app.telemetry.progress import compute_progress
from app.workers.celery_app import celery_app
from app.workers.context import merge_partials

# In-app notification emit layer — the counterpart to the external webhook. A
# job reaching its terminal stage (or being marked failed) best-effort emits an
# in-app notification the client renders as a bell + unread badge. Guarded so
# importing this module (during Celery task registration or a ``py_compile``
# sanity check) never crashes when the notifications/DB layer is absent, and
# bound at module scope so tests can monkeypatch it. When unavailable every
# emit degrades to a logged no-op (best-effort contract, see ``_safe_notify_*``).
try:  # pragma: no cover - failure path is defensive
    from app.services import notifications
except Exception as _notify_exc:  # noqa: BLE001 - notifications layer optional
    notifications = None  # type: ignore[assignment]
    logger.warning(f"in-app notifications layer unavailable: {_notify_exc}")

# Scheduled-publishing due-runner service — the counterpart called by Celery
# beat every minute (see ``process_due_publishes_task`` + celery_app beat
# schedule). Guarded so importing this module (task registration / a
# ``py_compile`` sanity check) never crashes when the scheduler/DB layer is
# absent, and bound at module scope so tests can monkeypatch it. When
# unavailable the beat task degrades to a logged no-op (best-effort contract).
try:  # pragma: no cover - failure path is defensive
    from app.services import scheduler
except Exception as _scheduler_exc:  # noqa: BLE001 - scheduler layer optional
    scheduler = None  # type: ignore[assignment]
    logger.warning(f"scheduled-publishing layer unavailable: {_scheduler_exc}")

# OAuth token refresh sweep — runs from Celery beat so scheduled publishing
# encounters fresh tokens where a provider supports refresh. Guarded for the
# same import-safety reason as the scheduler and retention sweeps.
try:  # pragma: no cover - failure path is defensive
    from app.services import oauth_connect
except Exception as _oauth_exc:  # noqa: BLE001 - OAuth layer optional
    oauth_connect = None  # type: ignore[assignment]
    logger.warning(f"OAuth refresh sweep layer unavailable: {_oauth_exc}")

# Job-create idempotency retention sweep. The idempotency rows protect the
# money path during the retry window, then are safely removed in bounded
# batches so an active API cannot accumulate an unbounded request log.
try:  # pragma: no cover - failure path is defensive
    from app.services import job_idempotency
except Exception as _idempotency_exc:  # noqa: BLE001 - optional at import time
    job_idempotency = None  # type: ignore[assignment]
    logger.warning(f"job idempotency layer unavailable: {_idempotency_exc}")

# Compliance retention sweep — wired to Celery beat (see the beat schedule in
# ``celery_app.py``). Guarded so importing this module never crashes when the
# compliance/DB layer is absent, and bound at module scope so tests can
# monkeypatch it. When unavailable the beat task degrades to a logged no-op.
try:  # pragma: no cover - failure path is defensive
    from app.services.compliance import retention as compliance_retention
except Exception as _retention_exc:  # noqa: BLE001 - compliance layer optional
    compliance_retention = None  # type: ignore[assignment]
    logger.warning(f"compliance retention layer unavailable: {_retention_exc}")

# ---------------------------------------------------------------------------
# Constants (import-safe: fall back to the contract §4.0 defaults if the const
# module has not yet been extended with the REELFORGE_* symbols).
# ---------------------------------------------------------------------------
try:  # pragma: no cover - trivial import shim
    from app.models.const import (
        REELFORGE_DAG,
        REELFORGE_STAGE_COMPLETE,
        REELFORGE_STAGE_FAILED,
        REELFORGE_STAGE_RUNNING,
    )
except Exception:  # noqa: BLE001 - const may not yet carry these symbols
    REELFORGE_STAGE_RUNNING = "running"
    REELFORGE_STAGE_COMPLETE = "complete"
    REELFORGE_STAGE_FAILED = "failed"
    REELFORGE_DAG = {
        "script": (),
        "tts": ("script",),
        "avatar": ("tts",),
        "captions": ("tts",),
        "compose": ("avatar", "captions"),
        "upload": ("compose",),
    }


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _done_stages(stage: str) -> set[str]:
    """Transitive dependency closure of ``stage`` (inclusive).

    A stage can only run once all its DAG dependencies have completed, so when
    ``stage`` finishes the set of completed stages is ``{stage} ∪ deps*``. Used
    as a *floor* for weighted progress (see ``_completed_stages``).
    """
    seen: set[str] = set()
    stack: list[str] = [stage]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(REELFORGE_DAG.get(current, ()))
    return seen


def _completed_stages(job: Any, stage: str) -> set[str]:
    """Union of every completed stage (monotonic progress input, LOW #5).

    In the parallel ``avatar ∥ captions`` chord each completion would otherwise
    derive progress from only *its own* dependency closure — so finishing
    captions (closure ``{script, tts, captions}`` -> 45%) after avatar (closure
    ``{script, tts, avatar}`` -> 60%) would make progress regress. To keep
    progress monotonic we take the UNION of:

      * the just-completed stage's dependency closure (a floor that holds even
        if the ``Job.stages`` write is momentarily unobservable), and
      * every stage the ``Job`` row already records as ``complete``.

    The DB set is authoritative because ``_report_success`` marks the stage
    ``complete`` (committed) *before* recomputing progress, so a concurrent
    sibling's completion is reflected here.
    """
    done: set[str] = set(_done_stages(stage))
    stages_map = getattr(job, "stages", None) or {}
    if isinstance(stages_map, dict):
        for name, status in stages_map.items():
            if status == REELFORGE_STAGE_COMPLETE:
                done.add(str(name))
    return done


def _stage_from_task_name(name: str | None) -> str:
    """Derive the stage name from a task name (``...stage_<X>_task`` -> ``X``)."""
    if not name:
        return ""
    leaf = name.rsplit(".", 1)[-1]
    if leaf.startswith("stage_") and leaf.endswith("_task"):
        return leaf[len("stage_") : -len("_task")]
    return leaf


def _job_id_from_args(args: tuple[Any, ...] | None) -> str:
    """Extract ``job_id`` from a task's positional args.

    Handles both the normal single-``ctx`` shape and the chord-callback shape
    where ``args[0]`` is a list of partial contexts.
    """
    if not args:
        return ""
    first = args[0]
    if isinstance(first, dict):
        return str(first.get("job_id", ""))
    if isinstance(first, list):
        for item in first:
            if isinstance(item, dict) and item.get("job_id"):
                return str(item["job_id"])
    return ""


def _request_id_from_args(args: tuple[Any, ...] | None) -> str:
    """Extract the stable request correlation id from a task context."""
    if not args:
        return ""
    first = args[0]
    if isinstance(first, dict):
        return str(first.get("request_id", ""))
    if isinstance(first, list):
        for item in first:
            if isinstance(item, dict) and item.get("request_id"):
                return str(item["request_id"])
    return ""


def _build_params(params_dict: dict) -> Any:
    """Reconstruct a ``ReelForgeParams`` from its JSON dict form.

    Imported lazily so this module stays importable before the services layer
    exists. ``platforms`` is normalised back to a tuple (JSON round-trips it as
    a list) to preserve the frozen-dataclass contract.
    """
    from app.services.reelforge import ReelForgeParams

    data = dict(params_dict)
    platforms = data.get("platforms")
    if isinstance(platforms, list):
        data["platforms"] = tuple(platforms)
    effects = data.get("effects")
    if isinstance(effects, list):
        data["effects"] = tuple(effects)
    return ReelForgeParams(**data)


# ---------------------------------------------------------------------------
# Best-effort state reporting (never raises to the caller)
# ---------------------------------------------------------------------------
def _safe_update_stage(job_id: str, stage: str, status: str) -> None:
    """Atomically write the per-stage status onto the ``Job`` row (best-effort)."""
    if not job_id:
        return
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).update_stage(job_id, stage, status)
    except Exception as exc:  # noqa: BLE001 - state reporting must not crash render
        logger.warning(f"update_stage({job_id},{stage},{status}) failed: {exc}")


def _safe_set_progress(job_id: str, stage: str, has_platforms: bool) -> None:
    """Recompute and persist weighted progress after ``stage`` completes.

    Progress is computed from the UNION of all completed stages recorded on the
    ``Job`` row (not this stage's closure alone) and persisted with a single
    **guarded, atomic** ``UPDATE ... WHERE progress < :value`` so it can never
    regress — the monotonicity check lives inside the DB engine (LOW #5).

    The previous read-modify-write (unlocked ``get`` -> Python ``max`` ->
    ``set_progress``) clamped only against the value this session had already
    read: in the parallel ``avatar ∥ captions`` chord two independent sessions
    each open a READ COMMITTED snapshot of ``progress`` *before* the other
    commits, so the later writer would overwrite a higher, already-committed
    value with its own stale-snapshot-based lower one — defeating the documented
    "Never regress" invariant. Moving the ``progress < :value`` predicate into
    the UPDATE itself (mirroring the guarded-UPDATE pattern used by
    ``ScheduledPublishRepository.claim_due`` / ``cancel``) closes that window:
    the check is re-evaluated by the engine against the live row, so a lower
    value simply matches zero rows and the higher committed progress survives.
    """
    if not job_id:
        return
    try:
        from sqlalchemy import func, update

        from app.models.db.base import get_session
        from app.models.db.models import Job
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                return
            progress = compute_progress(_completed_stages(job, stage), has_platforms)
            progress = max(0, min(100, int(progress)))
            # Atomic anti-regression guard: write only when the new value strictly
            # exceeds the value currently persisted, so a concurrent sibling's
            # higher committed progress can never be clobbered by this session.
            session.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    func.coalesce(Job.progress, 0) < progress,
                )
                .values(progress=progress)
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"set_progress({job_id},{stage}) failed: {exc}")


def _safe_mark_failed(job_id: str, stage: str, error: str) -> bool | None:
    """Mark the job failed and report whether THIS call recorded the root cause.

    The first-failure guard lives in the repository: only the earliest failing
    stage actually writes the FAILED state (under a row lock), so a later
    parallel sibling — the ``avatar ∥ captions`` chord runs two independent
    tasks, each with its own ``on_failure`` — finds the job already failed and
    leaves the earlier root cause intact. ``mark_failed`` stamps ``failed_stage``
    with the winning stage, so when it matches ours this call won the race.

    Returns ``True`` when this call recorded the failure (emit the notification),
    ``False`` when an earlier stage already did (suppress the duplicate), and
    ``None`` when the outcome is unknown — an empty job id or a DB error — so the
    caller defaults to emitting rather than dropping a real failure notification.
    """
    if not job_id:
        return None
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            job = JobRepository(session).mark_failed(job_id, stage, error)
            if job is None:
                return None
            return getattr(job, "failed_stage", None) == stage
    except Exception as exc:  # noqa: BLE001
        logger.error(f"mark_failed({job_id},{stage}) failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Best-effort in-app notification emit (a notification failure must NEVER fail
# a job — every helper below swallows all errors and returns None).
# ---------------------------------------------------------------------------
def _resolve_user_id(job_id: str) -> str:
    """Best-effort lookup of the ``user_id`` owning ``job_id``.

    Opens a short-lived session and reads the ``Job`` row so a notification can
    be addressed to its owner. Returns ``""`` — never raises — when the job id
    is empty, the persistence layer is unavailable, the job is missing, or the
    read fails for any reason, so a lookup hiccup can never abort the render.
    """
    if not job_id:
        return ""
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                return ""
            return str(getattr(job, "user_id", "") or "")
    except Exception as exc:  # noqa: BLE001 - user lookup must not crash render
        logger.warning(f"resolve_user_id({job_id}) failed: {exc}")
        return ""


def _is_terminal_stage(stage: str, has_platforms: bool) -> bool:
    """Return whether completing ``stage`` means the whole job is done.

    Mirrors ``pipeline.build_chain`` exactly: ``upload`` is the terminal stage
    when platforms were requested; otherwise the chain omits upload and
    ``compose`` is the last stage. Any other stage is intermediate.
    """
    if has_platforms:
        return stage == "upload"
    return stage == "compose"


def _safe_notify_job_complete(job_id: str, ctx: dict) -> None:
    """Emit a ``job_complete`` in-app notification (best-effort, never raises).

    Resolves the owning ``user_id`` from the ``Job`` row and emits with only the
    ``job_id``. The ready-to-open download link is a **read-time** concern: the
    API layer presigns ``Job.result_key`` when the notification is viewed
    (mirroring ``jobs.py``). A short-lived presigned credential must NEVER be
    persisted in ``Notification.data`` (see the ``notifications`` module
    docstring) — it would expire while the row lives on indefinitely, leaving a
    dead 403 link and a stored credential. Any failure — an unavailable
    notifications layer, a missing user, an emit error — is logged and swallowed
    so it can never turn a finished render into a failure.
    """
    if notifications is None or not job_id:
        return
    try:
        user_id = _resolve_user_id(job_id)
        if not user_id:
            return
        notifications.notify_job_complete(user_id, job_id)
    except Exception as exc:  # noqa: BLE001 - notification must not crash render
        logger.warning(f"notify_job_complete({job_id}) failed: {exc}")


_TASK_STATE_COMPLETE = 1  # const.TASK_STATE_COMPLETE (import-safe literal)


def _notify_if_complete(job_id: str) -> None:
    """After a standalone generation task returns, notify its owner on success.

    Reads the terminal state the delegate service persisted; a job that did not
    reach COMPLETE (e.g. held or still settling) emits nothing. Failures are
    already notified by ``_report_failure``. Best-effort, never raises.
    """
    if notifications is None or not job_id:
        return
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            if job is None or job.state != _TASK_STATE_COMPLETE:
                return
            user_id = str(job.user_id or "")
            kind = str(getattr(job, "kind", "") or "")
        if user_id:
            notifications.notify_job_complete(user_id, job_id, kind=kind)
    except Exception as exc:  # noqa: BLE001 - notification must never fail the task
        logger.warning(f"completion notification for job {job_id} failed: {exc}")


def _safe_notify_job_failed(job_id: str, error: str) -> None:
    """Emit a ``job_failed`` in-app notification (best-effort, never raises).

    Resolves the owning ``user_id`` and forwards the (already-surfaced) job
    error string. Any failure is logged and swallowed so an emit hiccup can
    never mask or re-raise on the failure path.
    """
    if notifications is None or not job_id:
        return
    try:
        user_id = _resolve_user_id(job_id)
        if not user_id:
            return
        notifications.notify_job_failed(user_id, job_id, error)
    except Exception as exc:  # noqa: BLE001 - notification must not crash render
        logger.warning(f"notify_job_failed({job_id}) failed: {exc}")


def _report_start(job_id: str, stage: str) -> None:
    record_event(job_id, stage, REELFORGE_STAGE_RUNNING)
    _safe_update_stage(job_id, stage, REELFORGE_STAGE_RUNNING)


def _report_success(
    job_id: str, stage: str, has_platforms: bool, duration_ms: int = 0
) -> None:
    # The ``complete`` event carries the stage wall-clock ``duration_ms`` so
    # per-stage timing telemetry lands even for stages with no external cost.
    record_event(job_id, stage, REELFORGE_STAGE_COMPLETE, duration_ms=duration_ms)
    _safe_update_stage(job_id, stage, REELFORGE_STAGE_COMPLETE)
    _safe_set_progress(job_id, stage, has_platforms)


def _stage_cost_row(
    stage: str,
    params: Any,
    ctx: dict,
    result: dict,
    duration_ms: int,
    llm_calls: list | None,
) -> tuple[float, dict[str, Any]] | None:
    """``(cost_usd, meta)`` actuals for one stage, or ``None`` when it has none.

    * ``script``  - model and (estimated) prompt/completion tokens of every LLM
      call the stage made.
    * ``tts``     - voice characters and the engine actually used; only a
      premium (ElevenLabs) voice costs money.
    * ``avatar``  - presenter provider and provider seconds.
    * ``compose`` - render seconds on our own box (self-hosted compute).
    """
    from app.telemetry import cost as cost_mod

    if stage == "script":
        if not llm_calls:
            return None
        from app.telemetry import llm_usage

        usage = llm_usage.summarize(llm_calls)
        usd = cost_mod.estimate_llm_cost(
            usage["model"].split(",")[0], usage["prompt_tokens"], usage["completion_tokens"]
        )
        return usd, usage
    if stage == "tts":
        script_text = str(ctx.get("script") or getattr(params, "video_script", "") or "")
        chars = len(script_text)
        voice = str(result.get("tts_voice") or getattr(params, "voice_name", "") or "")
        premium = voice.startswith("elevenlabs:")
        usd = cost_mod.estimate_tts_cost(chars) if premium else 0.0
        return usd, {
            "chars": chars,
            "voice_chars": chars,
            "voice_engine": "elevenlabs" if premium else "free",
            "voice": voice[:80],
        }
    if stage == "avatar":
        if not (result.get("avatar_key") or result.get("avatar_video")):
            return None  # captions-only reel: no presenter call was made
        seconds = float(result.get("avatar_duration") or ctx.get("audio_duration") or 0.0)
        provider = str(getattr(params, "avatar_provider", "") or "heygen")
        usd = cost_mod.estimate_avatar_cost(seconds, provider)
        return usd, {"seconds": seconds, "provider_seconds": seconds, "provider": provider}
    if stage == "compose":
        from app.services.cost_guard import render_usd_per_min

        render_seconds = round(max(0, int(duration_ms)) / 1000.0, 3)
        usd = round(render_seconds / 60.0 * render_usd_per_min(), 6)
        return usd, {"render_seconds": render_seconds}
    return None


def _safe_record_cost(
    job_id: str,
    stage: str,
    params: Any,
    ctx: dict,
    result: dict,
    duration_ms: int,
    llm_calls: list | None = None,
) -> None:
    """Record this stage's per-job actuals and USD cost (best-effort).

    Never raises EXCEPT :class:`CostCapExceeded` when the measured spend pushes
    the job over its per-job cap — that must fail the stage.

    A dedicated ``"cost"`` ``JobEvent`` (via :func:`telemetry.cost.record_cost`)
    carries ``cost_usd``, ``duration_ms`` and the actuals in its payload (see
    :func:`_stage_cost_row`). Any other failure is logged and swallowed —
    telemetry must never break the render.
    """
    if not job_id:
        return
    try:
        from app.telemetry import cost as cost_mod

        row = _stage_cost_row(stage, params, ctx, result, duration_ms, llm_calls)
        if row is None:
            return
        cost_usd, meta = row
        cost_mod.record_cost(
            job_id, stage, cost_usd, duration_ms=duration_ms, meta=meta
        )
        from app.services.cost_guard import CostCapExceeded, enforce_runtime_cost_cap

        try:
            enforce_runtime_cost_cap(job_id)
        except CostCapExceeded as exc:
            record_event(
                job_id,
                "cost_guard",
                REELFORGE_STAGE_FAILED,
                message=str(exc),
                payload={"stage": stage, "trigger": "measured_cost"},
            )
            raise
    except Exception as exc:  # noqa: BLE001 - cost telemetry is best-effort
        from app.services.cost_guard import CostCapExceeded

        if isinstance(exc, CostCapExceeded):
            # A measured cap breach is NOT telemetry noise: it must fail the
            # stage so ``StageTask.on_failure`` stops the chain and refunds.
            raise
        logger.warning(f"record_cost({job_id},{stage}) failed: {exc}")


def _report_failure(job_id: str, stage: str, exc: BaseException) -> None:
    error = str(exc)
    record_event(job_id, stage, REELFORGE_STAGE_FAILED, message=error)
    first_failure = _safe_mark_failed(job_id, stage, error)
    # Best-effort in-app 'video failed' notification — emitted AFTER the failure
    # is recorded and fully swallowed so it can never mask the root cause. Gated
    # on the first-failure signal so the parallel avatar ∥ captions chord
    # siblings don't each emit a duplicate 'video failed' notification (mirrors
    # the repository's first-failure guard). ``None`` (unknown outcome — e.g. DB
    # unavailable) still emits so a real failure is never silently dropped.
    if first_failure is not False:
        _safe_notify_job_failed(job_id, error)


# ---------------------------------------------------------------------------
# Owner cancellation (DELETE /api/v1/tasks/{id} marks the job FAILED at the
# ``cancelled`` stage; every stage re-checks it and stops the chain).
# ---------------------------------------------------------------------------
_CANCELLED_STAGE = "cancelled"


def _is_cancelled(job_id: str) -> bool:
    """Whether the job's owner cancelled it (best-effort, never raises)."""
    if not job_id:
        return False
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            return bool(
                job is not None
                and (getattr(job, "failed_stage", "") or "") == _CANCELLED_STAGE
            )
    except Exception as exc:  # noqa: BLE001 - a lookup hiccup must not stop a render
        logger.warning(f"cancel check for job {job_id} failed: {exc}")
        return False


def _stop_if_cancelled(job_id: str, stage: str) -> None:
    """Stop the Celery chain quietly when the job was cancelled by its owner.

    Raises :class:`celery.exceptions.Ignore`, which ends this task without a
    success (so no downstream chain link runs) and without ``on_failure`` (so the
    owner's cancellation is not overwritten or re-notified as a failure).
    """
    if not _is_cancelled(job_id):
        return
    from celery.exceptions import Ignore

    logger.info(f"job {job_id} was cancelled by its owner; skipping stage '{stage}'")
    raise Ignore()


# ---------------------------------------------------------------------------
# Shared runner
# ---------------------------------------------------------------------------
def _run_stage(
    ctx: dict,
    stage: str,
    stage_fn: Callable[[str, Any, dict], dict],
) -> dict:
    """Execute one stage function with start/success reporting.

    The stage function's exception is allowed to propagate so Celery's
    ``autoretry_for`` / ``on_failure`` machinery handles retry and terminal
    failure. Only the reporting side effects are swallowed.
    """
    job_id = str(ctx.get("job_id", ""))
    request_id = str(ctx.get("request_id", ""))
    params_dict = ctx.get("params", {}) or {}
    has_platforms = bool(params_dict.get("platforms"))
    params = _build_params(params_dict)

    logger.info(
        f"stage '{stage}' starting for job {job_id}, "
        f"correlation_id={request_id or 'n/a'}"
    )
    _stop_if_cancelled(job_id, stage)
    _report_start(job_id, stage)
    started = time.monotonic()
    from app.telemetry import llm_usage

    usage_token = llm_usage.begin()
    try:
        result = stage_fn(job_id, params, ctx)
    finally:
        llm_calls = llm_usage.end(usage_token)
    duration_ms = int((time.monotonic() - started) * 1000)
    # A cancel that landed while this stage was running wins over its result.
    _stop_if_cancelled(job_id, stage)
    if not isinstance(result, dict):
        result = {}
    new_ctx = {**ctx, **result}
    # Record measured cost BEFORE reporting success: a runtime cost-cap breach
    # raises here and must fail the stage rather than follow a 'complete' event.
    _safe_record_cost(job_id, stage, params, ctx, result, duration_ms, llm_calls)
    _report_success(job_id, stage, has_platforms, duration_ms=duration_ms)
    # A job reaches DONE when its terminal stage (upload with platforms, else
    # compose) completes — persist the terminal state + artifact keys first so
    # a polling client sees COMPLETE with a presentable result, then emit the
    # best-effort 'video ready' notification.
    if _is_terminal_stage(stage, has_platforms):
        _safe_mark_complete(job_id, new_ctx)
        _safe_notify_job_complete(job_id, new_ctx)
        # Settle a wallet-funded job's reservation on success (no-op for classic
        # credit jobs). Best-effort: a settle failure never breaks the pipeline.
        _safe_settle_wallet(job_id)
        # Keep 3x the measured AI-video cost of a presenter reel and return the
        # rest of its reservation (no-op for jobs without AI-video credits).
        _safe_settle_premium(job_id)
        _safe_record_dodo_usage(job_id, new_ctx)
        _safe_queue_autopublish(job_id)
        _safe_rally_render_completed(job_id)
    return new_ctx


def _safe_rally_render_completed(job_id: str) -> None:
    """Rally ``first_reel_rendered`` (no-op unless RALLY_EVENTS_KEY; never raises)."""
    try:
        from app.integrations.rally import track_render_completed

        track_render_completed(job_id)
    except Exception as exc:  # noqa: BLE001 - lifecycle events never break a render
        logger.debug(f"rally render event skipped for job {job_id}: {exc}")


def _safe_queue_autopublish(job_id: str) -> None:
    """Queue the owner-requested auto-publish for a just-finished job.

    ``POST /jobs`` stores requested platforms as ``_autopublish_platforms``; on
    completion they become a due-now scheduled publish, which the minute
    due-runner posts through the owner's native OAuth connections (with the
    entitlement re-check and pre-publish content gate). Best-effort, never raises.
    """
    if not job_id:
        return
    try:
        from datetime import datetime, timezone

        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository, ScheduledPublishRepository

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                return
            params = job.params if isinstance(job.params, dict) else {}
            platforms = [
                str(p) for p in (params.get("_autopublish_platforms") or []) if str(p).strip()
            ]
            if not platforms:
                return
            ScheduledPublishRepository(session).create(
                user_id=str(job.user_id),
                job_id=job_id,
                platforms=platforms,
                scheduled_at=datetime.now(timezone.utc),
                youtube_privacy_status=str(params.get("youtube_privacy_status") or "private"),
            )
        logger.info(f"job {job_id} queued for auto-publish to {platforms}")
    except Exception as exc:  # noqa: BLE001 - publishing must never fail a finished render
        logger.error(f"auto-publish queue failed for job {job_id}: {exc}")


def _safe_mark_complete(job_id: str, ctx: dict) -> None:
    """Persist the terminal COMPLETE state + artifact keys (best-effort).

    The compose stage returns ``final_key`` / ``poster_key`` / ``preview_key``
    in the chain context but nothing previously wrote them (or the terminal
    ``TASK_STATE_COMPLETE``) onto the ``Job`` row, so ``GET /jobs/{id}`` kept
    reporting PROCESSING with no result even after a successful render. Mirrors
    ``mark_failed``'s best-effort contract: a persistence hiccup is logged and
    swallowed so it can never turn a finished render into a failure.
    """
    if not job_id:
        return
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        final_key = str(ctx.get("final_key") or "").strip()
        poster_key = str(ctx.get("poster_key") or "").strip()
        preview_key = str(ctx.get("preview_key") or "").strip()
        with get_session() as session:
            repo = JobRepository(session)
            repo.set_artifacts(
                job_id,
                poster_key=poster_key or None,
                preview_key=preview_key or None,
            )
            repo.mark_complete(job_id, final_key)
    except Exception as exc:  # noqa: BLE001 - completion reporting must not crash render
        logger.error(f"mark_complete({job_id}) failed: {exc}")


def _safe_record_dodo_usage(job_id: str, ctx: dict) -> None:
    """Queue a Dodo ``reel.rendered`` usage event for a metered plan (never raises)."""
    try:
        from app.services.billing import dodo_usage

        seconds = ctx.get("duration_s") or ctx.get("duration")
        dodo_usage.record_render(job_id, seconds=seconds if seconds else None)
    except Exception as exc:  # noqa: BLE001 - metering must never fail a render
        logger.error(f"dodo usage metering failed for job {job_id}: {exc}")


def _safe_settle_premium(job_id: str) -> None:
    """Best-effort AI-video settlement for a completed job (never raises)."""
    try:
        from app.domains.reels.premium import settle_job

        settle_job(job_id)
    except Exception as exc:  # noqa: BLE001 - settlement must never break the pipeline
        logger.error(f"premium settle hook failed for job {job_id}: {exc}")


def _safe_settle_wallet(job_id: str) -> None:
    """Best-effort wallet settlement for a completed job (never raises)."""
    try:
        from app.domains.reels.wallet_bridge import safe_settle_job_by_id

        safe_settle_job_by_id(job_id)
    except Exception as exc:  # noqa: BLE001 - settlement must never break the pipeline
        logger.error(f"wallet settle hook failed for job {job_id}: {exc}")


class StageTask(celery_app.Task):
    """Base task that reports terminal failure via the repository layer.

    ``on_failure`` fires only after retries are exhausted, so ``mark_failed``
    records the true root cause exactly once (repository enforces the guard).
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        stage = _stage_from_task_name(self.name)
        job_id = _job_id_from_args(args)
        request_id = _request_id_from_args(args)
        logger.error(
            f"stage '{stage}' failed for job {job_id}, "
            f"correlation_id={request_id or 'n/a'}: {exc}"
        )
        _report_failure(job_id, stage, exc)
        # Release a wallet-funded job's reservation on terminal failure (no-op for
        # classic credit jobs, which are refunded by the cost-guard path below).
        # Best-effort so it can never mask the terminal failure.
        try:
            from app.domains.reels.wallet_bridge import safe_release_job_by_id

            safe_release_job_by_id(job_id)
        except Exception as release_exc:  # noqa: BLE001 - preserve terminal failure
            logger.error(f"wallet release hook failed for job {job_id}: {release_exc}")
        # Premium voice / AI-video credits come back on terminal failure
        # (success-only billing; idempotent, never raises).
        try:
            from app.domains.reels.premium import refund_job as refund_premium

            refund_premium(job_id)
        except Exception as premium_exc:  # noqa: BLE001 - preserve terminal failure
            logger.error(f"premium refund hook failed for job {job_id}: {premium_exc}")
        try:
            from app.services.cost_guard import (
                CostCapExceeded,
                refund_cost_capped_job_once,
            )

            if isinstance(exc, CostCapExceeded):
                refunded = refund_cost_capped_job_once(job_id)
                logger.warning(
                    f"cost cap failure for job {job_id}: refund_issued={refunded}"
                )
            else:
                # Success-only billing for credit-funded reels: a terminal stage
                # failure returns the cycle's debit exactly once (keyed on the
                # newest ledger debit of the job), so a retry never double-bills.
                from app.domains.reels.refunds import refund_failed_reel_once

                refunded_credits = refund_failed_reel_once(job_id)
                if refunded_credits:
                    logger.info(
                        f"failed reel {job_id} refunded {refunded_credits} credit(s)"
                    )
        except Exception as refund_exc:  # noqa: BLE001 - preserve terminal failure
            logger.error(f"failure refund failed for job {job_id}: {refund_exc}")


# ---------------------------------------------------------------------------
# Stage tasks (§6.3 — retry/timeout policy per contract)
# ---------------------------------------------------------------------------
@celery_app.task(
    base=StageTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=120,
    time_limit=150,
)
def stage_script_task(self, ctx: dict) -> dict:
    """Generate (or accept) the UGC script. Returns ``{**ctx, script}``."""
    from app.services.reelforge import stage_script

    return _run_stage(ctx, "script", stage_script)


@celery_app.task(
    base=StageTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=180,
    time_limit=210,
)
def stage_tts_task(self, ctx: dict) -> dict:
    """Synthesise audio + word timings (timing authority). Returns merged ctx."""
    from app.services.reelforge import stage_tts

    return _run_stage(ctx, "tts", stage_tts)


@celery_app.task(
    base=StageTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=2,
    retry_backoff=True,
    soft_time_limit=1800,
    time_limit=1860,
)
def stage_avatar_task(self, ctx: dict) -> dict:
    """Render the talking-head avatar (HeyGen is slow). Runs parallel to captions."""
    from app.services.reelforge import stage_avatar

    return _run_stage(ctx, "avatar", stage_avatar)


@celery_app.task(
    base=StageTask,
    bind=True,
    soft_time_limit=120,
    time_limit=150,
)
def stage_captions_task(self, ctx: dict) -> dict:
    """Build the ASS karaoke captions. Runs parallel to the avatar stage."""
    from app.services.reelforge import stage_captions

    return _run_stage(ctx, "captions", stage_captions)


@celery_app.task(
    base=StageTask,
    bind=True,
    soft_time_limit=600,
    time_limit=660,
)
def stage_compose_task(self, results: list[dict]) -> dict:
    """Chord callback: fan-in avatar + captions partials, then compose.

    ``results`` is ``[avatar_ctx, captions_ctx]`` (order not guaranteed). Both
    carry the same base keys and differ only in ``avatar_*`` vs ``ass_*``; they
    are unioned into a single context before the compose stage runs.
    """
    from app.services.reelforge import stage_compose

    merged = merge_partials(results)
    return _run_stage(merged, "compose", stage_compose)


@celery_app.task(
    base=StageTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=5,
    retry_backoff=True,
    soft_time_limit=120,
    time_limit=150,
)
def stage_upload_task(self, ctx: dict) -> dict:
    """Cross-post the final video to the requested platforms. Returns merged ctx."""
    from app.services.reelforge import stage_upload

    return _run_stage(ctx, "upload", stage_upload)


# ---------------------------------------------------------------------------
# Standalone AI B-roll generation (studio). A single ComfyUI/Wan clip is
# 30-120s of GPU, so it runs as its own ``Job(kind="broll_gen")`` on the
# ``render`` queue rather than blocking the request. On terminal failure the
# job is marked failed AND its credit debit is refunded (studio generations are
# paid up front, exactly like a reel job).
# ---------------------------------------------------------------------------
class BrollGenTask(StageTask):
    """``StageTask`` that also refunds the credit debit on terminal failure."""

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        job_id = _job_id_from_args(args)
        logger.error(f"broll_gen failed for job {job_id}: {exc}")
        _report_failure(job_id, "broll_gen", exc)
        try:
            from app.domains.broll.service import refund_broll_generation

            refund_broll_generation(job_id)
        except Exception as refund_exc:  # noqa: BLE001 - refund must not crash the worker
            logger.error(f"broll_gen refund failed for job {job_id}: {refund_exc}")


@celery_app.task(
    base=BrollGenTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=1,
    retry_backoff=True,
    soft_time_limit=1800,
    time_limit=1860,
)
def generate_broll_clip_task(self, ctx: dict) -> dict:
    """Generate one AI B-roll clip for a ``broll_gen`` job. ``ctx = {job_id}``.

    Delegates to :func:`app.domains.broll.service.run_broll_generation`, which
    calls the provider, re-hosts the clip to R2, persists an ``Asset`` row, and
    marks the job complete. A raise here triggers :meth:`BrollGenTask.on_failure`
    (mark-failed + refund) after retries are exhausted.
    """
    from app.domains.broll.service import run_broll_generation

    job_id = str((ctx or {}).get("job_id", ""))
    request_id = str((ctx or {}).get("request_id", ""))
    logger.info(
        f"broll_gen: starting job={job_id!r}, correlation_id={request_id or 'n/a'}"
    )
    result = run_broll_generation(job_id)
    _notify_if_complete(job_id)
    return result


# ---------------------------------------------------------------------------
# Standalone speak (lipsync) generation (studio). A single lipsync render is tens
# of seconds of GPU, so it runs as its own ``Job(kind="speak_lipsync")`` on the
# ``generation`` queue rather than blocking the request. On terminal failure the
# job is marked failed AND its credit debit is refunded (studio generations are
# paid up front, exactly like a reel/B-roll job).
# ---------------------------------------------------------------------------
class SpeakLipsyncTask(StageTask):
    """``StageTask`` that also refunds the credit debit on terminal failure."""

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        job_id = _job_id_from_args(args)
        logger.error(f"speak_lipsync failed for job {job_id}: {exc}")
        _report_failure(job_id, "speak_lipsync", exc)
        try:
            from app.domains.speak.service import refund_speak_generation

            refund_speak_generation(job_id)
        except Exception as refund_exc:  # noqa: BLE001 - refund must not crash the worker
            logger.error(f"speak_lipsync refund failed for job {job_id}: {refund_exc}")


@celery_app.task(
    base=SpeakLipsyncTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=1,
    retry_backoff=True,
    soft_time_limit=1800,
    time_limit=1860,
)
def generate_speak_lipsync_task(self, ctx: dict) -> dict:
    """Generate one talking video for a ``speak_lipsync`` job. ``ctx = {job_id}``.

    Delegates to :func:`app.domains.speak.service.run_speak_generation`, which
    presigns the owned image + audio, drives the lipsync adapter submit->poll,
    re-hosts the mp4 to R2, persists an ``Asset`` row, and marks the job complete.
    A raise here triggers :meth:`SpeakLipsyncTask.on_failure` (mark-failed +
    refund) after retries are exhausted.
    """
    from app.domains.speak.service import run_speak_generation

    job_id = str((ctx or {}).get("job_id", ""))
    request_id = str((ctx or {}).get("request_id", ""))
    logger.info(
        f"speak_lipsync: starting job={job_id!r}, correlation_id={request_id or 'n/a'}"
    )
    result = run_speak_generation(job_id)
    _notify_if_complete(job_id)
    return result


# ---------------------------------------------------------------------------
# Standalone character LoRA training (Wave 4 identity lock). Training a
# per-character LoRA is minutes of GPU, so it runs as its own
# ``Job(kind="character_lora")`` on the ``generation`` queue. On terminal failure
# the job is marked failed AND its credit debit is refunded (training is paid up
# front, exactly like a B-roll / reel job).
# ---------------------------------------------------------------------------
class TrainLoraTask(StageTask):
    """``StageTask`` that also refunds the credit debit on terminal failure."""

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        job_id = _job_id_from_args(args)
        logger.error(f"character_lora failed for job {job_id}: {exc}")
        _report_failure(job_id, "character_lora", exc)
        try:
            from app.domains.characters.training_service import (
                refund_character_lora_training,
            )

            refund_character_lora_training(job_id)
        except Exception as refund_exc:  # noqa: BLE001 - refund must not crash the worker
            logger.error(f"character_lora refund failed for job {job_id}: {refund_exc}")


@celery_app.task(
    base=TrainLoraTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=1,
    retry_backoff=True,
    soft_time_limit=1800,
    time_limit=1860,
)
def train_character_lora_task(self, ctx: dict) -> dict:
    """Train one character LoRA for a ``character_lora`` job. ``ctx = {job_id}``.

    Delegates to
    :func:`app.domains.characters.training_service.run_character_lora_training`,
    which presigns the owned reference keys, drives the ``lora_train`` provider
    (submit->poll), rehosts the trained ``.safetensors`` to R2, writes the key
    onto ``Character.lora_ref``, and marks the job complete. A raise here triggers
    :meth:`TrainLoraTask.on_failure` (mark-failed + refund) after retries.
    """
    from app.domains.characters.training_service import run_character_lora_training

    job_id = str((ctx or {}).get("job_id", ""))
    request_id = str((ctx or {}).get("request_id", ""))
    logger.info(
        f"character_lora: starting job={job_id!r}, correlation_id={request_id or 'n/a'}"
    )
    result = run_character_lora_training(job_id)
    _notify_if_complete(job_id)
    return result


# ---------------------------------------------------------------------------
# Trend ingestion (pull). Scraping a third-party platform runs as its own
# ``Job(kind="trends_pull")`` so a slow/failing scrape never blocks a request or
# crashes a reel job. On terminal failure the job is marked failed AND its credit
# debit is refunded (pulls are paid up front at enqueue, exactly like B-roll).
# The pull is ToS-gated (consent + allowlist) inside the delegate service.
# ---------------------------------------------------------------------------
class TrendsPullTask(StageTask):
    """``StageTask`` that also refunds the credit debit on terminal failure."""

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        job_id = _job_id_from_args(args)
        logger.error(f"trends_pull failed for job {job_id}: {exc}")
        _report_failure(job_id, "trends_pull", exc)
        try:
            from app.domains.trends.service import refund_trends_pull

            refund_trends_pull(job_id)
        except Exception as refund_exc:  # noqa: BLE001 - refund must not crash the worker
            logger.error(f"trends_pull refund failed for job {job_id}: {refund_exc}")


@celery_app.task(
    base=TrendsPullTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=1,
    retry_backoff=True,
    soft_time_limit=600,
    time_limit=660,
)
def run_trends_pull(self, ctx: dict) -> dict:
    """Pull + score one trend for a ``trends_pull`` job. ``ctx = {job_id}``.

    Thin wrapper delegating to :func:`app.domains.trends.service.run_trends_pull`,
    which enforces the consent/allowlist gate, pulls raw posts via the configured
    provider, folds them into a daily-count series, and records a scored
    ``TrendObservation`` (scoring UNCHANGED). A raise here triggers
    :meth:`TrendsPullTask.on_failure` (mark-failed + refund) after retries.
    Import-safe: a scraper failure never crashes other jobs.
    """
    from app.domains.trends.service import run_trends_pull as _run

    job_id = str((ctx or {}).get("job_id", ""))
    request_id = str((ctx or {}).get("request_id", ""))
    logger.info(
        f"trends_pull: starting job={job_id!r}, correlation_id={request_id or 'n/a'}"
    )
    return _run(job_id)


# ---------------------------------------------------------------------------
# Long->short auto-clipping. Transcribing + reframing + stitching a long
# recording is heavy, so it runs as its own ``Job(kind="clipping")``. On terminal
# failure the job is marked failed AND any wallet reservation is released
# idempotently (mirrors the reels terminal hook). Thin wrapper only — all
# business logic lives in ``domains.clipping.service.ClippingService``.
# ---------------------------------------------------------------------------
class ClippingTask(StageTask):
    """``StageTask`` that also releases the wallet reservation on terminal failure."""

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        job_id = _job_id_from_args(args)
        logger.error(f"clipping failed for job {job_id}: {exc}")
        _report_failure(job_id, "clipping", exc)
        try:
            from app.domains.clipping.wallet_bridge import safe_release_job_by_id

            safe_release_job_by_id(job_id)
        except Exception as release_exc:  # noqa: BLE001 - release must not crash the worker
            logger.error(
                f"clipping wallet release failed for job {job_id}: {release_exc}"
            )


@celery_app.task(
    base=ClippingTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=1,
    retry_backoff=True,
    soft_time_limit=1800,
    time_limit=1860,
)
def run_clipping(self, ctx: dict) -> dict:
    """Run one long->short auto-clipping job. ``ctx = {job_id[, request_id]}``.

    Delegates to :meth:`app.domains.clipping.service.ClippingService.run`, then
    settles a wallet-funded job's reservation on success (no-op for classic
    jobs). A raise here triggers :meth:`ClippingTask.on_failure` (mark-failed +
    wallet release) after retries are exhausted.
    """
    from app.domains.clipping.service import ClippingService

    job_id = str((ctx or {}).get("job_id", ""))
    request_id = str((ctx or {}).get("request_id", ""))
    logger.info(
        f"clipping: starting job={job_id!r}, correlation_id={request_id or 'n/a'}"
    )
    result = ClippingService.run(job_id)
    _notify_if_complete(job_id)
    try:
        from app.domains.clipping.wallet_bridge import safe_settle_job_by_id

        safe_settle_job_by_id(job_id)
    except Exception as settle_exc:  # noqa: BLE001 - settle must never break the pipeline
        logger.error(f"clipping wallet settle failed for job {job_id}: {settle_exc}")
    return result


@celery_app.task(
    bind=True,
    soft_time_limit=1800,
    time_limit=1860,
)
def run_repurpose_task(self, ctx: dict) -> dict:
    """Transcribe + rank one repurpose job into highlight clips.

    ``ctx = {job_id, request_id, max_clips, min_len_s, max_len_s, min_score}``.
    Delegates to :func:`app.domains.repurpose.service.run_auto_repurpose`, which
    records any failure on the job itself (never leaves it ``transcribing``).
    """
    from app.domains.repurpose.service import _fail, run_auto_repurpose

    ctx = ctx or {}
    job_id = str(ctx.get("job_id", ""))
    try:
        return run_auto_repurpose(
            job_id,
            max_clips=int(ctx.get("max_clips") or 5),
            min_len_s=int(ctx.get("min_len_s") or 15),
            max_len_s=int(ctx.get("max_len_s") or 60),
            min_score=int(ctx.get("min_score") or 50),
        )
    except Exception as exc:  # noqa: BLE001 - includes soft time limit
        logger.error(f"repurpose task failed for {job_id}: {exc}")
        _fail(job_id, "processing failed; try again")
        return {"job_id": job_id, "status": "failed"}


@celery_app.task(bind=True, soft_time_limit=900, time_limit=960)
def autopull_trends_task(self) -> dict[str, int]:
    """Refresh the shared trends feed from operator-configured targets (beat).

    No-op unless ``TREND_AUTOPULL_TARGETS`` (and the matching allowlist) is set.
    Never raises.
    """
    try:
        from app.domains.trends.service import autopull_trends

        return autopull_trends()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"autopull_trends_task failed: {exc}")
        return {"targets": 0, "recorded": 0, "skipped": 0}


class EditorExportTask(StageTask):
    """Record a stable editor stage name when FFmpeg export terminates."""

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        job_id = _job_id_from_args(args)
        logger.error(f"editor export failed for job {job_id}: {exc}")
        _report_failure(job_id, "export", exc)
        # A failed export gives its credit back now, not on the next export.
        # Idempotent: the refund is keyed to the job's debit (once only).
        from app.domains.reels.charge import refund_failed_job_once

        refund_failed_job_once(job_id)


@celery_app.task(
    base=EditorExportTask,
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=2,
    retry_backoff=True,
    soft_time_limit=900,
    time_limit=960,
)
def export_editor_cut_task(self, ctx: dict) -> dict:
    """Render one persisted editor export job (single-trim OR multi-segment EDL).

    Both the ``editor_export`` (single in/out range) and the
    ``editor_timeline_export`` (multi-segment EDL: trims + reorder + per-segment
    speed + captions + overlays) job kinds share this entrypoint; ``run_export``
    dispatches to the correct renderer by the job's persisted kind.
    """
    from app.domains.editor.workflows import run_export

    job_id = str((ctx or {}).get("job_id", ""))
    request_id = str((ctx or {}).get("request_id", ""))
    logger.info(
        f"editor export: starting job={job_id!r}, correlation_id={request_id or 'n/a'}"
    )
    result = run_export(job_id)
    _notify_if_complete(job_id)
    return result


# ---------------------------------------------------------------------------
# Scheduled-publishing due-runner (wired to Celery beat every 60s in
# ``celery_app.py``). Delegates to :func:`app.services.scheduler.process_due_publishes`
# which itself is best-effort/idempotent and NEVER raises out of its per-item
# loop; this wrapper adds a second guard so a beat tick can never crash the
# worker even if the scheduler layer is missing or its entrypoint raises.
# ---------------------------------------------------------------------------
_EMPTY_PUBLISH_SUMMARY: dict[str, int] = {"claimed": 0, "published": 0, "failed": 0}


@celery_app.task(bind=True)
def reconcile_mint_settlements_task(self) -> dict[str, int]:
    """Recover Mint holds missed by a worker's normal terminal hook."""
    empty = {"scanned": 0, "captured": 0, "released": 0, "errored": 0}
    try:
        from app.domains.reels.wallet_bridge import run_mint_settlement_reconciliation

        return run_mint_settlement_reconciliation(limit=100)
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash worker
        logger.error(f"reconcile_mint_settlements_task failed: {exc}")
        return empty


@celery_app.task(bind=True)
def reconcile_wallet_transfers_task(self) -> dict[str, int]:
    """Lease and replay pending person-to-person Mint transfer commands."""
    empty = {
        "claimed": 0,
        "completed": 0,
        "rejected": 0,
        "pending": 0,
        "errored": 0,
        "lost_lease": 0,
    }
    try:
        from app.domains.wallet.transfer_reconciliation import (
            reconcile_pending_transfers,
        )

        return reconcile_pending_transfers(limit=100)
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash worker
        logger.error(f"reconcile_wallet_transfers_task failed: {exc}")
        return empty


@celery_app.task(bind=True)
def sweep_render_jobs_task(self) -> dict[str, int]:
    """Advance every active async-GPU render job one poll-step (beat entrypoint).

    Called by Celery beat: delegates to
    :func:`app.services.render.poller.run_poll_sweep`, which polls each non-terminal
    ``render_jobs`` row and settles/refunds the owner's wallet on a terminal
    result (success-only billing). NEVER raises — a missing render/DB layer or an
    unexpected error degrades to a logged zeroed summary so a beat tick cannot
    crash the worker.
    """
    try:
        from app.services.render.poller import run_poll_sweep

        result = run_poll_sweep()
        return {
            "scanned": result.scanned,
            "advanced": result.advanced,
            "completed": result.completed,
            "failed": result.failed,
            "errored": result.errored,
        }
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"sweep_render_jobs_task failed: {exc}")
        return {"scanned": 0, "advanced": 0, "completed": 0, "failed": 0, "errored": 0}


@celery_app.task(bind=True)
def sweep_media_gateway_jobs_task(self) -> dict[str, int]:
    """Recover unfinished image/video/audio gateway jobs and their Mint holds."""
    empty = {
        "scanned": 0,
        "advanced": 0,
        "completed": 0,
        "failed": 0,
        "errored": 0,
    }
    try:
        from app.domains.gateway.media_gateway import run_pending_reconciliation

        return run_pending_reconciliation(limit=100)
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash worker
        logger.error(f"sweep_media_gateway_jobs_task failed: {exc}")
        return empty


@celery_app.task(bind=True)
def flush_dodo_usage_task(self) -> dict[str, int]:
    """Flush pending Dodo usage events in ≤1,000-event batches (beat entrypoint)."""
    try:
        from app.services.billing import dodo_usage

        return dodo_usage.flush_pending()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash worker
        logger.error(f"flush_dodo_usage_task failed: {exc}")
        return {"sent": 0, "retry": 0, "failed": 0}


@celery_app.task(bind=True)
def process_due_publishes_task(self) -> dict[str, int]:
    """Publish every scheduled reel whose UTC time has arrived (beat entrypoint).

    Called by Celery beat once a minute. Delegates to
    :func:`app.services.scheduler.process_due_publishes` (real UTC ``now``) and
    returns its ``{"claimed", "published", "failed"}`` summary. This task NEVER
    raises: a missing scheduler layer or an unexpected error degrades to a logged
    no-op returning a zeroed summary, so a transient failure can neither crash
    the beat scheduler nor poison the periodic tick.
    """
    if scheduler is None:
        logger.warning(
            "process_due_publishes_task: scheduler layer unavailable; skipping tick"
        )
        return dict(_EMPTY_PUBLISH_SUMMARY)
    try:
        summary = scheduler.process_due_publishes()
        return summary if isinstance(summary, dict) else dict(_EMPTY_PUBLISH_SUMMARY)
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"process_due_publishes_task failed: {exc}")
        return dict(_EMPTY_PUBLISH_SUMMARY)


@celery_app.task(bind=True)
def sweep_processing_publishes_task(self) -> dict[str, int]:
    """Finish publishes Instagram/TikTok are still ingesting (beat entrypoint).

    Delegates to :func:`app.services.scheduler.resume_processing_publishes`,
    which re-polls each ``processing`` post, runs Instagram's ``media_publish``
    once the container is ready, resolves TikTok ``publish_id``s to live posts,
    and flips the row to ``published``/``failed``. Never raises.
    """
    empty = {"claimed": 0, "published": 0, "failed": 0, "processing": 0}
    if scheduler is None:
        logger.warning(
            "sweep_processing_publishes_task: scheduler layer unavailable; skipping tick"
        )
        return dict(empty)
    try:
        summary = scheduler.resume_processing_publishes()
        return summary if isinstance(summary, dict) else dict(empty)
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"sweep_processing_publishes_task failed: {exc}")
        return dict(empty)


# --------------------------------------------------------------------------- #
# OAuth token refresh sweep (wired to Celery beat every five minutes). The
# service isolates each account failure; this wrapper keeps the beat process
# safe even if importing or invoking the service fails unexpectedly.
# --------------------------------------------------------------------------- #
_EMPTY_OAUTH_REFRESH_SUMMARY: dict[str, int] = {
    "considered": 0,
    "refreshed": 0,
    "failed": 0,
}


@celery_app.task(bind=True)
def sweep_oauth_token_refresh_task(self) -> dict[str, int]:
    """Proactively refresh soon-expiring social OAuth tokens (beat entrypoint)."""
    if oauth_connect is None:
        logger.warning(
            "sweep_oauth_token_refresh_task: OAuth layer unavailable; skipping tick"
        )
        return dict(_EMPTY_OAUTH_REFRESH_SUMMARY)
    try:
        summary = oauth_connect.sweep_expiring_accounts()
        return (
            summary if isinstance(summary, dict) else dict(_EMPTY_OAUTH_REFRESH_SUMMARY)
        )
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash worker
        logger.error(f"sweep_oauth_token_refresh_task failed: {exc}")
        return dict(_EMPTY_OAUTH_REFRESH_SUMMARY)


_EMPTY_JOB_IDEMPOTENCY_SUMMARY: dict[str, int] = {"deleted": 0}


@celery_app.task(bind=True)
def sweep_job_idempotency_task(self) -> dict[str, int]:
    """Remove expired job-create idempotency records (daily beat entrypoint)."""
    if job_idempotency is None:
        logger.warning(
            "sweep_job_idempotency_task: idempotency layer unavailable; skipping tick"
        )
        return dict(_EMPTY_JOB_IDEMPOTENCY_SUMMARY)
    try:
        summary = job_idempotency.sweep_expired_job_requests()
        return (
            summary
            if isinstance(summary, dict)
            else dict(_EMPTY_JOB_IDEMPOTENCY_SUMMARY)
        )
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash worker
        logger.error(f"sweep_job_idempotency_task failed: {exc}")
        return dict(_EMPTY_JOB_IDEMPOTENCY_SUMMARY)


# ---------------------------------------------------------------------------
# Compliance retention sweep (wired to Celery beat daily in ``celery_app.py``).
# Delegates to :func:`app.services.compliance.retention.run_sweep`, which opens
# its own committed session and NEVER raises; this wrapper adds a second guard
# so a beat tick can never crash the worker even if the compliance layer is
# missing or its entrypoint raises.
# ---------------------------------------------------------------------------
_EMPTY_RETENTION_SUMMARY: dict[str, int] = {
    "workspaces": 0,
    "jobs_purged": 0,
    "assets_purged": 0,
}


@celery_app.task(bind=True)
def sweep_retention_task(self) -> dict[str, int]:
    """Enforce every workspace's data-retention window (beat entrypoint).

    Called by Celery beat once a day. Delegates to
    :func:`app.services.compliance.retention.run_sweep` (real UTC ``now``) and
    returns its ``{"workspaces", "jobs_purged", "assets_purged"}`` summary. This
    task NEVER raises: a missing compliance layer or an unexpected error degrades
    to a logged no-op returning a zeroed summary, so a transient failure can
    neither crash the beat scheduler nor poison the periodic tick.
    """
    if compliance_retention is None:
        logger.warning(
            "sweep_retention_task: compliance layer unavailable; skipping tick"
        )
        return dict(_EMPTY_RETENTION_SUMMARY)
    try:
        summary = compliance_retention.run_sweep()
        return summary if isinstance(summary, dict) else dict(_EMPTY_RETENTION_SUMMARY)
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"sweep_retention_task failed: {exc}")
        return dict(_EMPTY_RETENTION_SUMMARY)


@celery_app.task(
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=600,
    time_limit=660,
)
def run_marketplace_generation_task(
    self,
    job_id: str,
    capability: str,
    model_id: str,
    request: dict,
    request_id: str = "",
) -> dict:
    """Run one pay-as-you-go provider generation via the routing engine.

    Resolves the caller-selected model to a route, drives the provider adapter
    (submit -> poll), prices + records the measured usage, and stamps the actual
    cost onto the job's wallet marker so the job's terminal settlement charges the
    real amount. Runs on the isolated ``generation`` queue. A ``RoutingError``
    propagates so Celery's retry / terminal-failure machinery applies (and the
    wallet reservation is released on terminal failure by the existing hook).
    """
    from app.domains.routing.runtime import run_generation_job

    return run_generation_job(
        job_id,
        capability=capability,
        model_id=model_id,
        request=request or {},
        correlation_id=request_id,
    )


@celery_app.task(
    bind=True,
    autoretry_for=(ConnectionError,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=900,
    time_limit=960,
)
def run_marketplace_reel_task(
    self,
    job_id: str,
    stages: dict,
    requests: dict | None = None,
    user_id: str = "",
    use_byok: bool = False,
) -> dict:
    """Run a full pay-as-you-go reel: every profile stage through the engine.

    Resolves each ``capability -> model_id`` stage, drives its provider adapter,
    prices + records usage, and stamps the AGGREGATE actual cost onto the job's
    wallet marker for terminal settlement. Honors BYOK per stage. Runs on the
    isolated ``generation`` queue; ``RoutingError`` propagates for Celery retry.
    """
    from app.domains.routing.runtime import run_marketplace_reel_job

    return run_marketplace_reel_job(
        job_id,
        stages=stages or {},
        requests=requests,
        user_id=user_id,
        use_byok=use_byok,
    )
