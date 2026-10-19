"""ReelForge pipeline assembly + enqueue (INTEGRATION_CONTRACT.md §6.3).

The canonical DAG is ``script → tts → {avatar ∥ captions} → compose → upload``.
The fan-out/fan-in middle (avatar and captions both depend only on tts and run
concurrently, then compose merges them) is expressed as a Celery ``chord``:
``group(avatar, captions)`` with ``compose`` as the callback. That chord is
embedded in a linear ``chain`` after script and tts, with upload appended only
when the job requests at least one publish platform.

``start_pipeline`` enqueues the chain and returns the root ``AsyncResult.id``,
which the caller persists to ``Job.celery_task_id``.

Render lanes (M1.3): ``start_pipeline`` resolves the job's lane (paid > first
reel > free > variants 2-3 > bulk), stamps it on the job for the queue ETA and
routes the render stages (avatar, compose) to that lane's queue. With
``MENIVOR_RENDER_LANES`` off every lane maps to the historical ``render`` queue.
Before enqueueing it runs the host preflight (``workers.preflight``, MG8) when
that module is present.

Provenance (MN5): the compose callback is
``app.workers.tasks_provenance.stage_compose_task``, which writes the
AI-generated tag into the final MP4 (metadata remux, no re-encode) before the
job is marked complete, on first runs and on retries alike.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from celery import chain, chord, group
from loguru import logger

from app.workers.context import new_context
from app.workers.tasks import (
    stage_avatar_task,
    stage_captions_task,
    stage_script_task,
    stage_tts_task,
    stage_upload_task,
)

# MN5: compose then mark the final MP4 as AI-generated (provenance tag) before
# the job completes. Same stage name, runner and refund path as the classic
# ``app.workers.tasks.stage_compose_task``, which stays registered.
from app.workers.tasks_provenance import stage_compose_task

if TYPE_CHECKING:  # pragma: no cover - typing only; avoids hard services import
    from app.services.reelforge import ReelForgeParams

# Import-safe: fall back to the contract §4.0 DAG if const has not yet been
# extended with the REELFORGE_* symbols (mirrors app.workers.tasks).
try:  # pragma: no cover - trivial import shim
    from app.models.const import REELFORGE_DAG
except Exception:  # noqa: BLE001
    REELFORGE_DAG = {
        "script": (),
        "tts": ("script",),
        "avatar": ("tts",),
        "captions": ("tts",),
        "compose": ("avatar", "captions"),
        "upload": ("compose",),
    }

# The parallel middle of the DAG (avatar ∥ captions). A retry that resumes at
# either of these stages restarts the whole chord so the fan-in stays intact.
_PARALLEL_STAGES: frozenset[str] = frozenset({"avatar", "captions"})

# JobContext keys a resumed sub-chain needs *pre-seeded* (produced by an
# already-completed upstream stage) before it can start at ``failed_stage``.
# If reconstruction cannot supply all of them the retry falls back to a full
# re-run (§6.3). ``avatar``/``captions`` share requirements because resuming
# either restarts the parallel pair (and compose downstream needs audio_key).
_SEED_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "tts": ("script",),
    "avatar": ("audio_key", "audio_url", "audio_duration", "words"),
    "captions": ("audio_key", "audio_url", "audio_duration", "words"),
    "compose": ("audio_key", "avatar_key", "ass_key"),
    "upload": ("final_key",),
}


def _job_correlation_id(job_id: str) -> str:
    """Best-effort lookup of the correlation persisted at the API edge."""
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            values = (
                job.params if job is not None and isinstance(job.params, dict) else {}
            )
            return str(values.get("_correlation_id") or "")
    except Exception as exc:  # noqa: BLE001 - dispatch remains available if DB is down
        logger.warning(f"correlation lookup failed for job {job_id}: {exc}")
        return ""


def _apply_chain(task_chain: chain, correlation_id: str):
    """Enqueue a chain with correlation headers when one is available."""
    if correlation_id:
        return task_chain.apply_async(headers={"correlation_id": correlation_id})
    return task_chain.apply_async()


def _render_queue(lane: str) -> str | None:
    """The queue for ``lane``'s render stages; ``None`` keeps the static route."""
    if not lane:
        return None
    from app.domains.reels.policy import lane_queue

    return lane_queue(lane)


def _render_sig(task, lane: str, *args):
    """A render-stage signature routed to ``lane``'s queue when one is set."""
    sig = task.s(*args)
    queue = _render_queue(lane)
    return sig.set(queue=queue) if queue else sig


def build_chain(
    job_id: str, params: ReelForgeParams, correlation_id: str = "", lane: str = ""
) -> chain:
    """Assemble the Celery ``chain`` for a full pipeline run.

    Args:
        job_id: Owning ``Job.id``; seeded into the initial ``JobContext``.
        params: The validated ``ReelForgeParams`` for this run. When
            ``params.platforms`` is empty the upload stage is omitted.
        lane: Render lane; routes avatar and compose to the lane's queue.

    Returns:
        An un-applied Celery ``chain`` signature ready for ``apply_async()``.
    """
    parallel = chord(
        group(_render_sig(stage_avatar_task, lane), stage_captions_task.s()),
        _render_sig(stage_compose_task, lane),
    )

    steps = [
        stage_script_task.s(new_context(job_id, params.__dict__, correlation_id)),
        stage_tts_task.s(),
        parallel,
    ]
    if params.platforms:
        steps.append(stage_upload_task.s())

    return chain(*steps)


def _run_preflight(job_id: str) -> None:
    """Host preflight (disk, etc.) from MG8's ``workers.preflight`` when present.

    A refusal raises, so the caller's enqueue-failure path refunds the debit.
    """
    try:
        from app.workers import preflight  # type: ignore[attr-defined]
    except ImportError:
        return
    # MG8 exposes ``require_capacity()`` (raises PreflightError) and ``check()``
    # (returns a result, never raises). Only a raising entry point can stop the
    # enqueue, so ``check`` is never used here: calling it would be a silent no-op.
    guard = getattr(preflight, "require_capacity", None) or getattr(preflight, "preflight", None)
    if callable(guard):
        guard()


def assign_lane(job_id: str) -> str:
    """Resolve and stamp ``job_id``'s render lane; ``""`` when unknown.

    Best-effort: a DB problem never blocks the render, it only loses the lane
    (the render then uses the historical ``render`` queue).
    """
    try:
        from app.domains.reels.queue_eta import LANE_PARAM, resolve_lane
        from app.models.db.base import get_session
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            if job is None:
                return ""
            lane = resolve_lane(session, job)
            job.params = {**(job.params or {}), LANE_PARAM: lane}
            return lane
    except Exception as exc:  # noqa: BLE001 - lanes are an optimisation
        logger.warning(f"lane assignment failed for job {job_id}: {exc}")
        return ""


def start_pipeline(job_id: str, params: ReelForgeParams, lane: str | None = None) -> str:
    """Enqueue the pipeline and return the root task id.

    Args:
        job_id: Owning ``Job.id``.
        params: Validated ``ReelForgeParams`` for the run.
        lane: Render lane; resolved from the job row when ``None``.

    Returns:
        The root ``AsyncResult.id`` — persist it to ``Job.celery_task_id`` so
        the job can be tracked and (later) retried from its failed stage.
    """
    _run_preflight(job_id)
    if lane is None:
        from app.domains.reels.policy import lanes_enabled

        lane = assign_lane(job_id) if lanes_enabled() else ""
    correlation_id = _job_correlation_id(job_id)
    async_result = _apply_chain(
        build_chain(job_id, params, correlation_id, lane), correlation_id
    )
    return async_result.id


def build_retry_chain(
    job_id: str,
    params: ReelForgeParams,
    failed_stage: str,
    seed_ctx: dict | None = None,
    correlation_id: str = "",
) -> chain:
    """Assemble a resume ``chain`` starting at ``failed_stage`` (§6.3).

    Stages upstream of ``failed_stage`` are assumed complete; ``seed_ctx`` (the
    reconstructed ``JobContext``) carries their artifacts so the resumed stage
    can run. The remaining stages follow ``REELFORGE_DAG`` order
    (``script → tts → {avatar ∥ captions} → compose → upload``), with the
    upload stage appended only when the job requests at least one platform.

    An unknown or ``"script"`` ``failed_stage`` resumes from the top and is
    therefore identical to :func:`build_chain`.

    Args:
        job_id: Owning ``Job.id``; seeded into the initial ``JobContext``.
        params: The validated ``ReelForgeParams`` for this run.
        failed_stage: The stage to resume from.
        seed_ctx: The reconstructed last-good context. ``job_id``/``params`` are
            backfilled if absent so the resumed stage always sees them.

    Returns:
        An un-applied Celery ``chain`` signature ready for ``apply_async()``.
    """
    stage = failed_stage if failed_stage in REELFORGE_DAG else "script"

    seed: dict = dict(seed_ctx) if seed_ctx else {}
    seed.setdefault("job_id", job_id)
    seed.setdefault("params", params.__dict__)
    if correlation_id:
        seed["request_id"] = correlation_id

    parallel = chord(
        group(stage_avatar_task.s(), stage_captions_task.s()),
        stage_compose_task.s(),
    )

    if stage == "script":
        steps: list = [
            stage_script_task.s(seed),
            stage_tts_task.s(),
            parallel,
        ]
    elif stage == "tts":
        steps = [stage_tts_task.s(seed), parallel]
    elif stage in _PARALLEL_STAGES:
        # Resume the whole fan-out/fan-in chord seeded from the tts output.
        steps = [
            chord(
                group(
                    stage_avatar_task.s(seed),
                    stage_captions_task.s(seed),
                ),
                stage_compose_task.s(),
            )
        ]
    elif stage == "compose":
        # compose is the chord callback: it expects a *list* of partial contexts,
        # so wrap the single reconstructed context to satisfy ``merge_partials``.
        steps = [stage_compose_task.s([seed])]
    else:  # stage == "upload"
        steps = [stage_upload_task.s(seed)]

    if stage != "upload" and params.platforms:
        steps.append(stage_upload_task.s())

    return chain(*steps)


def _reconstruct_context(job_id: str, params: ReelForgeParams) -> dict | None:
    """Rebuild the last-good ``JobContext`` from the job's ``Asset`` rows (§6.3).

    Maps persisted artifacts back onto context keys by asset kind:

      * ``audio``  -> ``audio_key`` / ``audio_duration`` / ``audio_url`` (presigned)
        / ``words`` (from the asset ``meta``),
      * ``avatar`` -> ``avatar_key`` / ``avatar_duration``,
      * ``ass``    -> ``ass_key``,
      * ``final``  -> ``final_key``.

    A manually-supplied ``params.video_script`` is used as the ``script`` seed
    (an LLM-generated script is not persisted as an asset and is not
    recoverable). Returns ``None`` when the persistence layer is unavailable so
    the caller can fall back to a full re-run.
    """
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import AssetRepository
    except Exception as exc:  # noqa: BLE001 - DB layer optional
        logger.warning(f"retry: db layer unavailable for {job_id}: {exc}")
        return None

    seed: dict = new_context(job_id, params.__dict__, _job_correlation_id(job_id))
    manual_script = (params.video_script or "").strip()
    if manual_script:
        seed["script"] = manual_script

    try:
        with get_session() as session:
            assets = AssetRepository(session).list_for_job(job_id)
            # list_for_job returns oldest-first, so the last write of each kind
            # (the newest) wins.
            by_kind: dict = {}
            for asset in assets:
                by_kind[asset.kind] = asset

            audio = by_kind.get("audio")
            if audio is not None:
                seed["audio_key"] = audio.r2_key
                seed["audio_duration"] = float(audio.duration_s or 0.0)
                meta = audio.meta or {}
                words = meta.get("words") if isinstance(meta, dict) else None
                if isinstance(words, list) and words:
                    seed["words"] = words
                url = _presign_get(audio.r2_key)
                if url:
                    seed["audio_url"] = url

            avatar = by_kind.get("avatar")
            if avatar is not None:
                seed["avatar_key"] = avatar.r2_key
                seed["avatar_duration"] = float(avatar.duration_s or 0.0)

            ass = by_kind.get("ass")
            if ass is not None:
                seed["ass_key"] = ass.r2_key

            final = by_kind.get("final")
            if final is not None:
                seed["final_key"] = final.r2_key
    except Exception as exc:  # noqa: BLE001 - reconstruction is best-effort
        logger.warning(f"retry: asset reconstruction failed for {job_id}: {exc}")
        return None

    return seed


def _presign_get(key: str) -> str:
    """Best-effort presigned GET URL for an R2 key (empty string on failure)."""
    try:
        from app.platform.storage.r2 import get_r2_client

        return get_r2_client().presign_get(key) or ""
    except Exception as exc:  # noqa: BLE001 - R2 optional / offline in tests
        logger.warning(f"retry: could not presign {key!r}: {exc}")
        return ""


def _seed_satisfies(stage: str, seed: dict) -> bool:
    """Return True when ``seed`` carries every key required to resume ``stage``."""
    for key in _SEED_REQUIREMENTS.get(stage, ()):
        value = seed.get(key)
        if value is None or value == "" or value == [] or value == {}:
            return False
    return True


def retry_pipeline(job_id: str, params: ReelForgeParams, failed_stage: str) -> str:
    """Re-enqueue a failed job, resuming from ``failed_stage`` (§6.3).

    Reconstructs the last-good ``JobContext`` from the job's ``Asset`` rows and
    builds a sub-chain that starts at ``failed_stage``. When ``failed_stage`` is
    unknown/``"script"``, or the context cannot be reconstructed (missing
    artifacts, DB/R2 unavailable), it falls back to a full
    :func:`start_pipeline` re-run.

    Args:
        job_id: Owning ``Job.id``.
        params: Validated ``ReelForgeParams`` for the run.
        failed_stage: The stage the job failed at (from ``Job.failed_stage``).

    Returns:
        The new root ``AsyncResult.id`` — persist it to ``Job.celery_task_id``.
    """
    stage = failed_stage if failed_stage in REELFORGE_DAG else ""

    # Top-of-DAG failures, or an upload stage that no longer applies, have
    # nothing to resume from — start over.
    if not stage or stage == "script":
        return start_pipeline(job_id, params)
    if stage == "upload" and not params.platforms:
        logger.info(
            f"retry: job {job_id} failed at upload but has no platforms; "
            "falling back to a full re-run"
        )
        return start_pipeline(job_id, params)

    seed = _reconstruct_context(job_id, params)
    if seed is None or not _seed_satisfies(stage, seed):
        logger.info(
            f"retry: cannot reconstruct context to resume job {job_id} at "
            f"{stage!r}; falling back to a full re-run"
        )
        return start_pipeline(job_id, params)

    logger.info(f"retry: resuming job {job_id} from stage {stage!r}")
    correlation_id = _job_correlation_id(job_id)
    async_result = _apply_chain(
        build_retry_chain(job_id, params, stage, seed, correlation_id),
        correlation_id,
    )
    return async_result.id
