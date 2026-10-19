"""Render execution service — the money-metered async render lifecycle.

Ties three subsystems into one production path, each behind an injectable seam so
the whole lifecycle is deterministically testable without live infra:

* **wallet** (``WalletGateway``) — reserve the max cost up front, settle the
  ACTUAL on success, RELEASE (full refund) on failure. This encodes the
  success-only-billing invariant: a failed render never costs the creator.
* **backend** (``app.services.render`` client) — submit + poll the async-GPU job
  through the unified envelope.
* **events** (``app.events`` Outbox) — stage ``render.state_changed`` +
  ``job.completed`` so the flywheel (publish → measure → regenerate) reacts.

Pure orchestration: no DB/HTTP here — the router/worker wires the real
``WalletService`` + transport + outbox in.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol, runtime_checkable

from app.events.bus import JOB_COMPLETED, RENDER_STATE_CHANGED, Event, Outbox
from app.services.render import job_client
from app.services.render.backends.base import BackendError, Transport
from app.services.render.envelope import CANCELLED, COMPLETED, FAILED, RenderJob


def _metric_render_state(state: str) -> None:
    from app.telemetry.metrics import record_render_state

    record_render_state(state)


def _metric_wallet_debit(reason: str, micros: int) -> None:
    from app.telemetry.metrics import record_wallet_debit

    record_wallet_debit(reason, micros)


@runtime_checkable
class WalletGateway(Protocol):
    """The wallet operations the executor needs (satisfied by WalletService)."""

    def reserve(self, amount_micros: int, *, job_id: str) -> None: ...

    def settle(self, reserved_micros: int, actual_micros: int, *, job_id: str) -> None: ...

    def release(self, reserved_micros: int, *, job_id: str) -> None: ...


class ExecutionError(RuntimeError):
    """A render could not be started or advanced (wallet or backend)."""


class RenderExecutor:
    """Runs one async render job's money-metered lifecycle."""

    def __init__(
        self,
        wallet: WalletGateway,
        *,
        outbox: Outbox | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._wallet = wallet
        self._outbox = outbox or Outbox()
        self._transport = transport

    @property
    def outbox(self) -> Outbox:
        return self._outbox

    # -- start -------------------------------------------------------------- #
    def start(self, backend: str, spec: dict, *, max_cost_micros: int) -> RenderJob:
        """Reserve the max cost, submit the job, and return the queued envelope.

        A submit failure releases the reservation before re-raising, so a job that
        never started can never leave money held.
        """
        job_id = str(spec.get("job_id") or "")
        if max_cost_micros <= 0:
            raise ExecutionError("max_cost_micros must be positive")
        self._wallet.reserve(max_cost_micros, job_id=job_id)
        try:
            job = job_client.submit(backend, spec, transport=self._transport)
        except BackendError as exc:
            self._wallet.release(max_cost_micros, job_id=job_id)
            raise ExecutionError(f"submit failed, reservation released: {exc}") from exc
        self._stage_state(job, held_micros=max_cost_micros)
        return job

    # -- advance ------------------------------------------------------------ #
    def advance(self, job: RenderJob, *, held_micros: int) -> RenderJob:
        """Poll ``job`` once and settle/refund the wallet on a terminal result.

        * COMPLETED → settle actual (``job.cost_micros`` if reported, else the full
          hold), stage ``render.state_changed`` + ``job.completed``.
        * FAILED/CANCELLED → release the whole hold (full refund; success-only
          billing), stage ``render.state_changed``.
        A non-terminal poll just stages the progress event.
        """
        if job.is_terminal:
            return job
        try:
            advanced = job_client.poll(job, transport=self._transport)
        except BackendError as exc:
            raise ExecutionError(f"poll failed: {exc}") from exc

        if advanced.state == COMPLETED:
            cost_reported = bool(advanced.meta.get("actual_cost_reported"))
            actual = advanced.cost_micros if cost_reported or advanced.cost_micros > 0 else held_micros
            if actual > held_micros:
                self._wallet.release(held_micros, job_id=advanced.id)
                advanced = replace(
                    advanced,
                    state=FAILED,
                    progress=job.progress,
                    output_refs=(),
                    cost_micros=0,
                    error="reported render cost exceeded the reserved maximum",
                )
                self._stage_state(advanced, held_micros=held_micros, refunded=True)
                _metric_render_state(FAILED)
                return advanced
            self._wallet.settle(held_micros, actual, job_id=advanced.id)
            self._stage_state(advanced, held_micros=held_micros, actual_micros=actual)
            # Observability: emit the two series the success-only-billing invariant
            # correlates — a paid debit MUST be paired with a completed render.
            _metric_render_state(COMPLETED)
            _metric_wallet_debit("generation", actual)
            self._outbox.stage(Event(
                type=JOB_COMPLETED, key=advanced.id,
                payload={"output_refs": list(advanced.output_refs), "cost_micros": actual},
            ))
        elif advanced.state in {FAILED, CANCELLED}:
            self._wallet.release(held_micros, job_id=advanced.id)
            self._stage_state(advanced, held_micros=held_micros, refunded=True)
            _metric_render_state(advanced.state)  # no debit — terminal non-success is free
        else:
            self._stage_state(advanced, held_micros=held_micros)
        return advanced

    def cancel(self, job: RenderJob, *, held_micros: int) -> RenderJob:
        """Cancel an active backend task and release the complete wallet hold."""
        if job.is_terminal:
            return job
        try:
            cancelled = job_client.cancel(job, transport=self._transport)
        except BackendError as exc:
            raise ExecutionError(f"cancel failed: {exc}") from exc
        self._wallet.release(held_micros, job_id=cancelled.id)
        self._stage_state(cancelled, held_micros=held_micros, refunded=True)
        _metric_render_state(CANCELLED)
        return cancelled

    def run_to_completion(
        self, job: RenderJob, *, held_micros: int, max_polls: int = 100
    ) -> RenderJob:
        """Poll until terminal (or ``max_polls`` exhausted). Deterministic in tests
        because the injected transport controls how fast the job advances."""
        current = job
        for _ in range(max_polls):
            if current.is_terminal:
                break
            current = self.advance(current, held_micros=held_micros)
        return current

    # -- events ------------------------------------------------------------- #
    def _stage_state(self, job: RenderJob, **extra) -> None:
        self._outbox.stage(Event(
            type=RENDER_STATE_CHANGED,
            key=job.id,
            payload={"state": job.state, "progress": job.progress, "backend": job.backend, **extra},
        ))
