"""Append-only job telemetry.

`record_event` writes a single ``JobEvent`` row per call (§6 state-reporting).
It is deliberately import-safe and failure-tolerant: the persistence layer
(``app.models.db``) may not be importable in every context (e.g. tests, tooling,
or before the DB module is wired up), and telemetry must NEVER crash the
pipeline. On any error the function logs and returns ``None``.

The table is append-only: rows are only ever inserted, never mutated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids hard import at runtime
    from app.models.db.models import JobEvent


def record_event(
    job_id: str,
    stage: str,
    status: str,
    message: str = "",
    payload: dict[str, Any] | None = None,
    cost_usd: float = 0.0,
    duration_ms: int = 0,
) -> JobEvent | None:
    """Append a single ``JobEvent`` audit/telemetry row.

    Args:
        job_id: Owning ``Job.id``. Required.
        stage: Pipeline stage name (e.g. ``"tts"``, ``"avatar"``).
        status: One of the ``REELFORGE_STAGE_*`` statuses (``pending`` /
            ``running`` / ``complete`` / ``failed``) or an ad-hoc status such
            as ``"warning"`` (see §8 avatar duration check) or ``"cost"`` (per
            :func:`app.telemetry.cost.record_cost`).
        message: Optional human-readable detail.
        payload: Optional JSON-serialisable metadata dict.
        cost_usd: Estimated USD spend attributed to this event (CTO plan §0
            unit economics). Defaults to ``0.0``; coerced to a non-negative
            float so a bad estimate can never corrupt the row.
        duration_ms: Wall-clock duration of the stage in milliseconds. Defaults
            to ``0``; coerced to a non-negative int.

    Returns:
        The persisted ``JobEvent`` instance, or ``None`` if the event could not
        be recorded (invalid input, DB layer unavailable, or write failure).
        The caller MUST tolerate ``None`` — telemetry is best-effort and must
        not break the pipeline.
    """
    if not job_id or not stage or not status:
        logger.warning(
            "telemetry.record_event: missing required field "
            f"(job_id={job_id!r}, stage={stage!r}, status={status!r}); skipping"
        )
        return None

    # Lazy, guarded import so this module stays import-safe even when the
    # persistence layer is absent or misconfigured.
    try:
        from app.models.db.base import SessionLocal
        from app.models.db.models import Job, JobEvent
    except Exception as exc:  # noqa: BLE001 - broad on purpose: never crash pipeline
        logger.warning(
            f"telemetry.record_event: db layer unavailable, "
            f"skipping event ({stage}/{status}) for job {job_id}: {exc}"
        )
        return None

    safe_payload: dict[str, Any] = dict(payload) if payload else {}
    # Coerce cost/timing at the boundary: never let a bad estimate (NaN, a
    # string, a negative number) reach the DB. Fall back to 0 on any error.
    try:
        safe_cost = max(0.0, float(cost_usd))
    except (TypeError, ValueError):
        safe_cost = 0.0
    try:
        safe_duration = max(0, int(duration_ms))
    except (TypeError, ValueError):
        safe_duration = 0

    session = None
    try:
        session = SessionLocal()
        if stage in {"compose", "render", "publish"}:
            job = session.get(Job, job_id)
            params = job.params if job is not None and isinstance(job.params, dict) else {}
            source = params.get("source_context")
            if isinstance(source, dict):
                forecast_id = str(source.get("forecast_id") or "").strip()
                if forecast_id:
                    # Bounded server-stamped provenance only. Do not copy the
                    # full params blob into telemetry (it may contain creator
                    # text or webhook configuration).
                    safe_payload.setdefault("forecast_id", forecast_id[:32])
        event = JobEvent(
            job_id=job_id,
            stage=stage,
            status=status,
            message=message or "",
            payload=safe_payload,
            cost_usd=safe_cost,
            duration_ms=safe_duration,
        )
        session.add(event)
        session.commit()
        # SessionLocal is configured with expire_on_commit=False (see §4.1),
        # so attributes (id, created_at) stay loaded after the session closes.
        session.refresh(event)
        return event
    except Exception as exc:  # noqa: BLE001 - telemetry must not raise to caller
        if session is not None:
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        logger.error(
            f"telemetry.record_event: failed to persist event "
            f"({stage}/{status}) for job {job_id}: {exc}"
        )
        return None
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass
