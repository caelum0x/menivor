"""Speak (image + narration audio → talking video) as an async ``Job``.

A single lipsync render is tens of seconds of GPU, so a *speak* generation runs
as its own Celery ``Job(kind="speak_lipsync")`` on the ``generation`` queue,
exactly like the standalone B-roll studio (``domains/broll/service.py``):

    POST /generation/speak/generate -> Job(kind="speak_lipsync") -> generate_speak_lipsync_task
                                                                 │
                                        run_speak_generation ────┘  (this module)
                                        submit->poll -> R2 -> Asset -> done

This module is the **service delegate** the Celery task calls, so the task stays
a thin wrapper and the real work is unit-testable without a broker.

Two entry points:

* :func:`run_speak_generation` — load the job's stored params, presign the OWNED
  ``image_key`` + ``audio_key`` (short-lived signed GETs against our OWN bucket —
  never a raw client URL, SSRF §8), resolve the selected lipsync
  ``ProviderAdapter`` from the routing registry, drive ``submit``→``poll`` to a
  terminal state, re-host the result mp4 to R2 under
  ``jobs/<job_id>/speak/<uuid>.mp4``, persist an ``Asset`` provenance row, and
  mark the job complete (``result_key`` = the talking-video key). Raises on any
  hard failure so the task's ``on_failure`` records the root cause + refunds.
* :func:`refund_speak_generation` — idempotently return the debited credits when a
  generation fails (called from the task's terminal-failure hook).

Params persisted on the ``Job`` row::

    {"image_key", "audio_key", "provider", "license_class", "credits_cost",
     "workspace_id"?, "_correlation_id"?, "refunded"?}
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from loguru import logger

from app.domains.routing.base import (
    RUN_COMPLETED,
    ProviderRun,
    TERMINAL_STATES,
)

_SPEAK_ASSET_KIND: str = "speak"
_SPEAK_CONTENT_TYPE: str = "video/mp4"

# Presign TTL for the owned image + audio handed to the (remote) GPU worker. Both
# are our OWN R2 objects (ownership validated at the controller) exposed via a
# short-lived signed GET — never an arbitrary client URL (SSRF guard, §8).
_INPUT_PRESIGN_TTL_S: int = 900

# Bounded poll loop so a stuck provider run can never hang the worker forever.
_POLL_INTERVAL_S: float = 3.0
_MAX_POLLS: int = 400


def _load_job_context(job_id: str) -> tuple[str, dict[str, Any]] | None:
    """Return ``(user_id, params)`` for a job, or ``None`` if it is gone."""
    from app.models.db.base import get_session
    from app.models.db.repositories import JobRepository

    with get_session() as session:
        job = JobRepository(session).get(job_id)
        if job is None:
            return None
        return job.user_id, dict(job.params or {})


def _presign_owned(key: str) -> str:
    """Mint a short-lived signed GET for an OWNED R2 key (SSRF-safe, §8).

    ``key`` was ownership-checked by the controller (the authorization boundary)
    before the job was created, so here we only sign a GET against our OWN bucket
    — never an arbitrary client URL.
    """
    from app.platform.storage.r2 import get_r2_client

    return get_r2_client().presign_get(key, expires=_INPUT_PRESIGN_TTL_S)


def _resolve_adapter(provider_key: str):
    """Resolve the lipsync :class:`ProviderAdapter` for ``provider_key``.

    Prefers an adapter already registered in the routing registry (credentials
    present at startup); falls back to building a seeded lipsync adapter so the
    delegate stays runnable even before the registry is populated.
    """
    from app.domains.routing.base import registry

    adapter = registry.get(provider_key)
    if adapter is not None:
        return adapter
    from app.domains.routing.providers._lipsync import build_lipsync_adapter

    return build_lipsync_adapter(provider_key)


def _drive_to_terminal(adapter: Any, request: dict, correlation_id: str) -> ProviderRun:
    """Submit the request then poll to a terminal state; return the final run.

    Raises ``RuntimeError`` if the run ends non-completed or never terminalizes.
    """
    run = adapter.submit(request, {}, correlation_id)
    polls = 0
    while run.state not in TERMINAL_STATES and polls < _MAX_POLLS:
        time.sleep(_POLL_INTERVAL_S)
        run = adapter.poll(run)
        polls += 1
    if run.state != RUN_COMPLETED:
        raise RuntimeError(
            f"speak_lipsync: run ended in state {run.state!r} (run_id={run.run_id!r})"
        )
    if not run.result_ref:
        raise RuntimeError("speak_lipsync: completed run has no result url")
    return run


def run_speak_generation(job_id: str) -> dict[str, Any]:
    """Generate one talking video for ``Job(kind="speak_lipsync")`` ``job_id``.

    Raises ``RuntimeError`` on any hard failure (missing inputs, provider failure,
    empty output, upload failure) so the Celery task's ``on_failure`` marks the
    job failed and refunds the debit. Returns a small summary dict on success.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        raise RuntimeError("speak_lipsync: run called without a job_id")

    ctx = _load_job_context(job_id)
    if ctx is None:
        raise RuntimeError(f"speak_lipsync: job {job_id!r} not found")
    user_id, params = ctx
    correlation_id = str(params.get("_correlation_id") or "")
    logger.info(
        f"speak_lipsync: executing job={job_id!r}, "
        f"correlation_id={correlation_id or 'n/a'}"
    )

    image_key = str(params.get("image_key") or "").strip()
    audio_key = str(params.get("audio_key") or "").strip()
    if not image_key or not audio_key:
        raise RuntimeError("speak_lipsync: job requires both image_key and audio_key")

    provider_key = str(params.get("provider") or "").strip()
    if not provider_key:
        raise RuntimeError("speak_lipsync: job has no resolved provider")

    _set_progress(job_id, 10)

    # Presign BOTH owned inputs as short-lived signed GETs (never a raw URL, §8).
    image_url = _presign_owned(image_key)
    audio_url = _presign_owned(audio_key)
    if not image_url or not audio_url:
        raise RuntimeError("speak_lipsync: could not presign owned inputs")

    adapter = _resolve_adapter(provider_key)

    _set_progress(job_id, 30)
    run = _drive_to_terminal(
        adapter,
        {"image_url": image_url, "audio_url": audio_url},
        correlation_id,
    )

    _set_progress(job_id, 80)
    talking_video_key = _rehost_result(job_id, run.result_ref)

    seconds = float(run.usage.quantity_units) if run.usage else 0.0
    _persist_and_complete(
        job_id=job_id,
        user_id=user_id,
        talking_video_key=talking_video_key,
        duration=seconds,
        meta={
            "correlation_id": correlation_id,
            "provider": provider_key,
            "license_class": params.get("license_class") or "",
            "image_key": image_key,
            "audio_key": audio_key,
            "provider_run_id": run.run_id,
        },
    )
    logger.success(
        f"speak_lipsync: completed job={job_id!r} -> {talking_video_key} "
        f"({seconds:.1f}s), correlation_id={correlation_id or 'n/a'}"
    )
    return {
        "job_id": job_id,
        "talking_video_key": talking_video_key,
        "duration": seconds,
    }


def _rehost_result(job_id: str, result_url: str) -> str:
    """Download the provider's result mp4 and re-host it under this job's prefix.

    The object key is generated server-side (never provider/client-supplied) so a
    completed talking video is always scoped to *this* job. Returns the R2 key.
    """
    data = _download_bytes(result_url)
    if not data:
        raise RuntimeError("speak_lipsync: result download produced no bytes")
    from app.platform.storage.r2 import get_r2_client

    key = f"jobs/{job_id}/speak/{uuid4().hex}.mp4"
    get_r2_client().upload_bytes(key, data, _SPEAK_CONTENT_TYPE)
    return key


def _download_bytes(url: str) -> bytes:
    """Fetch ``url`` and return its raw bytes (network seam; monkeypatched in tests)."""
    try:
        import httpx

        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # noqa: BLE001 - normalized to a hard failure upstream
        raise RuntimeError(f"speak_lipsync: could not download result: {exc}") from exc


def _persist_and_complete(
    *,
    job_id: str,
    user_id: str,
    talking_video_key: str,
    duration: float,
    meta: dict[str, Any],
) -> None:
    """Persist the ``Asset`` provenance row and mark the job complete atomically."""
    from app.models.db.base import get_session
    from app.models.db.repositories import AssetRepository, JobRepository

    with get_session() as session:
        AssetRepository(session).create(
            user_id=user_id,
            kind=_SPEAK_ASSET_KIND,
            r2_key=talking_video_key,
            job_id=job_id,
            content_type=_SPEAK_CONTENT_TYPE,
            duration_s=duration,
            meta=meta,
        )
        # ``result_key`` = the talking-video key, so the existing ``GET /jobs/{id}``
        # poll + presign-download flow serves a completed speak job for free.
        JobRepository(session).mark_complete(job_id, talking_video_key)


def refund_speak_generation(job_id: str) -> None:
    """Idempotently refund a failed generation's credit debit (best-effort).

    Reads ``credits_cost`` / ``workspace_id`` from the job's stored params and
    grants the credits back to the pool they were debited from, setting a
    ``refunded`` flag so a retry/duplicate failure hook cannot double-refund.
    Never raises — a reconciliation failure must not crash the worker.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        return
    # AI-video credits held by the render go back (idempotent, never raises).
    from app.services.billing.premium_credits import refund_job_once

    refund_job_once(job_id)
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import CreditRepository, JobRepository

        with get_session() as session:
            job = JobRepository(session)._locked_job(job_id)
            if job is None:
                return
            params = dict(job.params or {})
            if params.get("refunded"):
                return  # already refunded — idempotent
            cost = int(params.get("credits_cost") or 0)
            if cost <= 0:
                return  # nothing was charged
            workspace_id = params.get("workspace_id") or None
            user_id = job.user_id

            credits = CreditRepository(session)
            if workspace_id:
                credits.workspace_grant(
                    workspace_id, cost, "speak_lipsync_refund", user_id
                )
            else:
                credits.grant(user_id, cost, "speak_lipsync_refund")

            job.params = {**params, "refunded": True}
            session.flush()
        logger.info(
            f"speak_lipsync: refunded {cost} credit(s) for failed job={job_id!r}"
        )
    except Exception as exc:  # noqa: BLE001 - refund is best-effort
        logger.error(f"speak_lipsync: refund failed for job={job_id!r}: {exc}")


def _set_progress(job_id: str, progress: int) -> None:
    """Best-effort coarse progress update; never crashes the generation."""
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).set_progress(job_id, progress)
    except Exception as exc:  # noqa: BLE001 - progress is cosmetic
        logger.debug(f"speak_lipsync: progress update failed for {job_id!r}: {exc}")
