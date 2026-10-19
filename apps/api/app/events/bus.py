"""In-process event bus + transactional outbox for the reel flywheel.

The create→publish→measure→regenerate loop is event-driven. This module gives a
small, dependency-free core:

* :class:`Event` — an immutable, JSON-serializable domain event (type, key,
  payload, idempotency key).
* :class:`EventBus` — subscribe handlers by event type and emit synchronously;
  handler exceptions are isolated (one bad handler never blocks the others) and
  collected so the caller can react.
* :class:`Outbox` — the transactional-outbox pattern: domain code *stages* events
  in the same unit of work as its state change; a separate dispatch step drains
  the outbox to the bus with at-least-once + idempotent delivery (a delivered
  idempotency key is never re-dispatched).

Pure and deterministic — no DB, no Celery here (the worker layer wires the outbox
to real persistence + Celery). Fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# Canonical event types for the flywheel (extend as domains land).
JOB_COMPLETED = "job.completed"
REEL_PUBLISHED = "reel.published"
RETENTION_INGESTED = "retention.ingested"
WINNER_SELECTED = "experiment.winner_selected"
REGENERATE_REQUESTED = "reel.regenerate_requested"
RENDER_STATE_CHANGED = "render.state_changed"


@dataclass(frozen=True)
class Event:
    """An immutable domain event.

    ``key`` is the aggregate id (job/reel/experiment) the event is about;
    ``idempotency_key`` dedupes delivery (defaults to ``{type}:{key}:{seq}`` set by
    the outbox). ``payload`` must be JSON-serializable.
    """

    type: str
    key: str
    payload: dict = field(default_factory=dict)
    idempotency_key: str = ""

    def with_idempotency(self, value: str) -> "Event":
        from dataclasses import replace

        return replace(self, idempotency_key=value)


Handler = Callable[[Event], None]


@dataclass(frozen=True)
class HandlerFailure:
    """A handler that raised while processing an event (isolated, not fatal)."""

    event_type: str
    handler: str
    error: str


class EventBus:
    """Synchronous, type-routed pub/sub with isolated handler failures."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def on(self, event_type: str) -> Callable[[Handler], Handler]:
        """Decorator form: ``@bus.on(JOB_COMPLETED)``."""

        def _register(handler: Handler) -> Handler:
            self.subscribe(event_type, handler)
            return handler

        return _register

    def handlers_for(self, event_type: str) -> tuple[Handler, ...]:
        return tuple(self._handlers.get(event_type, ()))

    def emit(self, event: Event) -> list[HandlerFailure]:
        """Deliver ``event`` to every subscribed handler; collect failures.

        One handler raising never prevents the others from running (the loop is
        the reliability boundary). Returns the list of failures for the caller to
        log/retry.
        """
        failures: list[HandlerFailure] = []
        for handler in self._handlers.get(event.type, []):
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - isolation is the whole point
                failures.append(
                    HandlerFailure(
                        event_type=event.type,
                        handler=getattr(handler, "__name__", repr(handler)),
                        error=str(exc),
                    )
                )
        return failures


class Outbox:
    """Transactional outbox: stage events, then drain to a bus once committed.

    ``stage`` records events (assigning a deterministic idempotency key); ``drain``
    delivers only not-yet-delivered events and remembers delivered keys so a retry
    (at-least-once) never double-delivers. In production the staged list lives in
    the same DB transaction as the domain write; here it is an in-memory list with
    the exact same semantics for testing + the pure core.
    """

    def __init__(self) -> None:
        self._pending: list[Event] = []
        self._delivered: set[str] = set()
        self._seq: int = 0

    def stage(self, event: Event) -> Event:
        self._seq += 1
        key = event.idempotency_key or f"{event.type}:{event.key}:{self._seq}"
        staged = event.with_idempotency(key)
        self._pending.append(staged)
        return staged

    @property
    def pending(self) -> tuple[Event, ...]:
        return tuple(self._pending)

    def drain(self, bus: EventBus) -> list[HandlerFailure]:
        """Deliver all pending, not-yet-delivered events to ``bus`` (idempotent).

        An event whose handlers all succeed is marked delivered and removed. An
        event with a handler failure is KEPT pending (at-least-once retry) and its
        failures returned. A previously-delivered idempotency key is dropped
        without redelivery.
        """
        failures: list[HandlerFailure] = []
        still_pending: list[Event] = []
        for event in self._pending:
            if event.idempotency_key in self._delivered:
                continue  # already delivered — never redeliver
            event_failures = bus.emit(event)
            if event_failures:
                failures.extend(event_failures)
                still_pending.append(event)  # retry on next drain
            else:
                self._delivered.add(event.idempotency_key)
        self._pending = still_pending
        return failures
