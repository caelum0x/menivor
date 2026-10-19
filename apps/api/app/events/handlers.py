"""Flywheel event handlers — create → publish → measure → regenerate.

Wires the domain reactions onto the :class:`EventBus` so the loop runs itself:

    JOB_COMPLETED      → publish the reel (+ any A/B hook variants)
    RETENTION_INGESTED → score the experiment; if conclusive → WINNER_SELECTED
    WINNER_SELECTED    → REGENERATE_REQUESTED biased toward the winning hook

The side effects (actual publish / regenerate) are injected callbacks and the
experiment metrics come from an injected store, so the wiring is pure and
testable; production passes the real publish service + experiment repository.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from app.domains.publishing.experiments import VariantMetrics, select_winner
from app.events.bus import (
    JOB_COMPLETED,
    REGENERATE_REQUESTED,
    RETENTION_INGESTED,
    WINNER_SELECTED,
    Event,
    EventBus,
)


@runtime_checkable
class ExperimentStore(Protocol):
    """Supplies the accumulated variant metrics for an experiment key."""

    def variant_metrics(self, experiment_key: str) -> list[VariantMetrics]: ...


PublishFn = Callable[[str, dict], None]      # (reel_key, payload) -> publish it
RegenerateFn = Callable[[str, str], None]    # (experiment_key, winning_hook) -> regen


def register_flywheel(
    bus: EventBus,
    *,
    on_publish: PublishFn,
    on_regenerate: RegenerateFn,
    experiments: ExperimentStore,
    min_views: int = 200,
) -> None:
    """Register the four flywheel handlers on ``bus`` (idempotent per bus).

    Handlers RE-EMIT downstream events on the same bus, so a single
    ``RETENTION_INGESTED`` can cascade to ``WINNER_SELECTED`` →
    ``REGENERATE_REQUESTED`` in one synchronous pass.
    """

    def _on_job_completed(ev: Event) -> None:
        on_publish(ev.key, ev.payload)

    def _on_retention(ev: Event) -> None:
        experiment_key = str(ev.payload.get("experiment_key") or ev.key)
        metrics = experiments.variant_metrics(experiment_key)
        result = select_winner(metrics, min_views=min_views)
        if result.conclusive:
            bus.emit(Event(
                type=WINNER_SELECTED,
                key=experiment_key,
                payload={"winner_id": result.winner_id, "winner_hook_ref": result.winner_hook_ref},
            ))

    def _on_winner(ev: Event) -> None:
        hook = str(ev.payload.get("winner_hook_ref") or "")
        on_regenerate(ev.key, hook)
        bus.emit(Event(
            type=REGENERATE_REQUESTED,
            key=ev.key,
            payload={"bias_hook_ref": hook, "source_winner": ev.payload.get("winner_id")},
        ))

    bus.subscribe(JOB_COMPLETED, _on_job_completed)
    bus.subscribe(RETENTION_INGESTED, _on_retention)
    bus.subscribe(WINNER_SELECTED, _on_winner)
