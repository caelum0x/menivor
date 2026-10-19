"""Render poll worker — advance every active async-GPU job to terminal.

The counterpart to ``POST /render/jobs/{id}/advance``: a background sweep that
loads all non-terminal ``render_jobs`` and advances each one poll-step through the
:class:`RenderExecutor` (bound to that job's owner wallet), settling on success
and refunding on failure. Idempotent — a job already terminal is skipped; a
transient backend error on one job never blocks the others.

Session is injected so it runs both under Celery (real DB) and in tests (sqlite).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.models.db.render_repo import RenderJobRepository, row_to_envelope
from app.services.render.backends.base import Transport
from app.services.render.execution import ExecutionError, RenderExecutor


@dataclass(frozen=True)
class PollSweepResult:
    """Outcome of one sweep."""

    scanned: int
    advanced: int
    completed: int
    failed: int
    errored: int
    # (user_id, render_job_id, state, error, source, label, film_project_id) for
    # every job that reached a terminal state in this sweep — notified post-commit.
    terminal: tuple = ()


def _make_wallet(session: Any, row: Any):
    from app.domains.wallet.service import WalletService
    from app.services.render.wallet_gateway import WalletServiceGateway

    return WalletServiceGateway(
        WalletService(session),
        user_id=row.user_id,
        workspace_id=row.workspace_id or None,
        correlation_id=f"poll:{row.id}",
    )


def poll_active_jobs(
    session: Any,
    *,
    transport: Transport | None = None,
    limit: int = 50,
) -> PollSweepResult:
    """Advance up to ``limit`` active render jobs one poll-step each.

    Each job is advanced with its OWN owner-bound wallet so settle/refund hits the
    right ledger. Per-job failures are logged + counted, never raised, so one bad
    job cannot stall the sweep.
    """
    repo = RenderJobRepository(session)
    rows = repo.list_active(limit=limit)
    scanned = len(rows)
    advanced = completed = failed = errored = 0
    terminal: list[tuple] = []

    for row in rows:
        env = row_to_envelope(row)
        if env.is_terminal:
            continue
        wallet = _make_wallet(session, row)
        executor = RenderExecutor(wallet, transport=transport)
        try:
            new_env = executor.advance(env, held_micros=row.held_cost_micros)
        except ExecutionError as exc:
            errored += 1
            logger.warning(f"[poll] job {row.id} advance failed: {exc}")
            # Surface to Sentry with triage context (best-effort, never raises).
            from app.telemetry.sentry import capture_exception

            capture_exception(
                exc, stage="render.poll",
                context={"job_id": row.id, "backend": row.backend, "provider_ref": row.provider_ref},
            )
            continue
        repo.save_envelope(new_env)
        if new_env.state != env.state:
            advanced += 1
        if new_env.state == "COMPLETED":
            completed += 1
        elif new_env.state == "FAILED":
            failed += 1
        if new_env.is_terminal and not env.is_terminal:
            project_id = _sync_film_shot(session, row.id, new_env.state)
            terminal.append((
                str(row.user_id), row.id, new_env.state, new_env.error or "",
                str(getattr(row, "source", "") or "render"),
                str(getattr(row, "label", "") or ""), project_id,
            ))

    if scanned:
        logger.info(
            f"[poll] swept {scanned} active jobs: advanced={advanced} "
            f"completed={completed} failed={failed} errored={errored}"
        )
    return PollSweepResult(scanned, advanced, completed, failed, errored, tuple(terminal))


def _sync_film_shot(session: Any, render_job_id: str, state: str) -> str:
    """Fold a terminal render state onto its film shot; return the project id."""
    try:
        from app.domains.film.repository import FilmRepository
        from app.models.db.film import FilmShot

        shot = (
            session.query(FilmShot)
            .filter(FilmShot.render_job_id == render_job_id)
            .first()
        )
        if shot is None:
            return ""
        if state == "COMPLETED" and shot.status != "done":
            FilmRepository(session).mark_shot(shot.id, status="done")
        elif state in ("FAILED", "CANCELLED") and shot.status != "failed":
            FilmRepository(session).mark_shot(shot.id, status="failed")
        return str(shot.project_id)
    except Exception as exc:  # noqa: BLE001 - film sync is best-effort in the sweep
        logger.warning(f"[poll] film shot sync failed for render {render_job_id}: {exc}")
        return ""


def notify_terminal(result: PollSweepResult) -> None:
    """Best-effort bell + push for every render that finished in a sweep."""
    try:
        from app.services import notifications
    except Exception:  # noqa: BLE001 - notifications layer optional
        return
    for user_id, job_id, state, error, source, label, project_id in result.terminal:
        try:
            if state == "COMPLETED":
                notifications.notify_render_complete(
                    user_id, job_id, source=source, label=label, film_project_id=project_id,
                )
            elif state == "FAILED":
                notifications.notify_render_failed(
                    user_id, job_id, error, source=source, film_project_id=project_id,
                )
        except Exception as exc:  # noqa: BLE001 - never break the sweep
            logger.warning(f"[poll] notify failed for render {job_id}: {exc}")


def run_poll_sweep(*, limit: int = 50) -> PollSweepResult:
    """Production entrypoint (Celery beat): open a real session + sweep once."""
    from app.models.db.base import get_session

    with get_session() as session:  # type: ignore[misc]
        result = poll_active_jobs(session, limit=limit)
    # Notify only after the sweep's transaction committed (so a notification can
    # never announce a state that was rolled back).
    notify_terminal(result)
    return result
