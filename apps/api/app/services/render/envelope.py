"""Unified async-GPU render job envelope + state machine.

Every async generation backend (RunPod / worker-comfyui / comfyui-deploy /
Replicate / Fal / ViewComfy) reports progress in its own vocabulary. This module
normalizes them into ONE envelope with a small, explicit state machine so the
rest of the platform (routing, wallet settle, event bus, pollers) speaks a single
language:

    IN_QUEUE ──▶ IN_PROGRESS ──▶ COMPLETED
        │             │
        └─────────────┴────────▶ FAILED  (terminal)
                      └────────▶ CANCELLED (terminal)

Pure + deterministic (no network, no DB): the backends (``backends/``) do the I/O
and hand raw provider payloads to :func:`normalize_state`; :func:`transition`
enforces the legal edges so a late/duplicate poll can never move a terminal job.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# Canonical envelope states.
IN_QUEUE = "IN_QUEUE"
IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

TERMINAL_STATES: frozenset[str] = frozenset({COMPLETED, FAILED, CANCELLED})
ALL_STATES: frozenset[str] = frozenset({IN_QUEUE, IN_PROGRESS, COMPLETED, FAILED, CANCELLED})

# Legal forward transitions. A terminal state has no outgoing edges (idempotent).
_EDGES: dict[str, frozenset[str]] = {
    IN_QUEUE: frozenset({IN_QUEUE, IN_PROGRESS, COMPLETED, FAILED, CANCELLED}),
    IN_PROGRESS: frozenset({IN_PROGRESS, COMPLETED, FAILED, CANCELLED}),
    COMPLETED: frozenset({COMPLETED}),
    FAILED: frozenset({FAILED}),
    CANCELLED: frozenset({CANCELLED}),
}


class EnvelopeError(ValueError):
    """An illegal envelope state or transition."""


@dataclass(frozen=True)
class RenderJob:
    """The normalized async render job the whole platform reads.

    Immutable — :func:`transition` returns a new copy, mirroring the codebase's
    immutability rule. ``provider_ref`` is the backend's own job id; ``poll_cursor``
    carries backend-specific paging/opaque state between polls.
    """

    id: str
    backend: str
    workflow_version: str = ""
    state: str = IN_QUEUE
    progress: float = 0.0            # 0..1
    provider_ref: str = ""
    poll_cursor: str = ""
    output_refs: tuple[str, ...] = ()
    cost_micros: int = 0
    error: str = ""
    attempts: int = 0
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in ALL_STATES:
            raise EnvelopeError(f"unknown envelope state {self.state!r}")
        if not (0.0 <= self.progress <= 1.0):
            raise EnvelopeError(f"progress must be in [0,1], got {self.progress}")

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_done(self) -> bool:
        return self.state == COMPLETED


def can_transition(current: str, target: str) -> bool:
    """True when ``current → target`` is a legal envelope edge."""
    if current not in ALL_STATES or target not in ALL_STATES:
        return False
    return target in _EDGES[current]


def transition(
    job: RenderJob,
    target: str,
    *,
    progress: float | None = None,
    output_refs: tuple[str, ...] | None = None,
    cost_micros: int | None = None,
    error: str = "",
    provider_ref: str | None = None,
    poll_cursor: str | None = None,
) -> RenderJob:
    """Return a NEW job advanced to ``target`` (or unchanged if already there).

    A no-op re-entry into the SAME terminal state is allowed (idempotent poll);
    any other move out of a terminal state raises. Terminal targets set a sensible
    progress (1.0 for COMPLETED) unless one is supplied.
    """
    if job.state == target and target in TERMINAL_STATES:
        return job  # idempotent terminal re-entry (duplicate webhook/poll)
    if not can_transition(job.state, target):
        raise EnvelopeError(f"illegal transition {job.state} → {target} (job {job.id})")

    new_progress = job.progress
    if progress is not None:
        new_progress = max(0.0, min(1.0, float(progress)))
    elif target == COMPLETED:
        new_progress = 1.0
    # Progress is monotonic while non-terminal (never regress a poll).
    if target not in TERMINAL_STATES:
        new_progress = max(job.progress, new_progress)

    return replace(
        job,
        state=target,
        progress=new_progress,
        output_refs=output_refs if output_refs is not None else job.output_refs,
        cost_micros=cost_micros if cost_micros is not None else job.cost_micros,
        error=error or (job.error if target != FAILED else job.error),
        provider_ref=provider_ref if provider_ref is not None else job.provider_ref,
        poll_cursor=poll_cursor if poll_cursor is not None else job.poll_cursor,
    )


def normalize_state(raw: str, state_map: dict[str, str] | None = None) -> str:
    """Map a backend's raw status string to a canonical envelope state.

    ``state_map`` overrides/extends the built-in aliases (each backend passes its
    own). Unknown values default to ``IN_PROGRESS`` (a live job we don't yet
    understand is safer treated as running than as done/failed).
    """
    key = str(raw or "").strip().upper()
    merged = {**_DEFAULT_ALIASES, **{k.upper(): v for k, v in (state_map or {}).items()}}
    return merged.get(key, IN_PROGRESS)


# Common provider vocabularies → canonical states (RunPod, ComfyUI, Replicate…).
_DEFAULT_ALIASES: dict[str, str] = {
    # queue
    "IN_QUEUE": IN_QUEUE, "QUEUED": IN_QUEUE, "STARTING": IN_QUEUE, "PENDING": IN_QUEUE,
    "CREATED": IN_QUEUE, "NOT_STARTED": IN_QUEUE,
    # running
    "IN_PROGRESS": IN_PROGRESS, "RUNNING": IN_PROGRESS, "PROCESSING": IN_PROGRESS,
    "EXECUTING": IN_PROGRESS, "UPLOADING": IN_PROGRESS,
    # done
    "COMPLETED": COMPLETED, "COMPLETE": COMPLETED, "SUCCEEDED": COMPLETED,
    "SUCCESS": COMPLETED, "FINISHED": COMPLETED, "DONE": COMPLETED,
    # failed
    "FAILED": FAILED, "FAILURE": FAILED, "ERROR": FAILED, "TIMED_OUT": FAILED,
    "TIMEOUT": FAILED, "CRASHED": FAILED,
    # cancelled
    "CANCELLED": CANCELLED, "CANCELED": CANCELLED, "ABORTED": CANCELLED,
}
