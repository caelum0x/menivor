"""P7 flywheel — JobCompleted→publish, RetentionIngested→winner→regenerate cascade."""

from __future__ import annotations

from app.domains.publishing.experiments import VariantMetrics
from app.events.bus import (
    JOB_COMPLETED,
    REGENERATE_REQUESTED,
    RETENTION_INGESTED,
    Event,
    EventBus,
)
from app.events.handlers import register_flywheel


class FakeExperiments:
    def __init__(self, metrics):
        self._m = metrics

    def variant_metrics(self, experiment_key):
        return self._m


def _conclusive_metrics():
    return [
        VariantMetrics("a", "hookA", views=1000, completion_rate=0.8, avg_watch_frac=0.7, rewatch_rate=0.2),
        VariantMetrics("b", "hookB", views=1000, completion_rate=0.4, avg_watch_frac=0.3, rewatch_rate=0.05),
    ]


def _wire(metrics):
    bus = EventBus()
    published, regenerated = [], []
    regen_events = []
    register_flywheel(
        bus,
        on_publish=lambda key, payload: published.append((key, payload)),
        on_regenerate=lambda exp, hook: regenerated.append((exp, hook)),
        experiments=FakeExperiments(metrics),
    )
    bus.subscribe(REGENERATE_REQUESTED, lambda e: regen_events.append(e.payload))
    return bus, published, regenerated, regen_events


def test_job_completed_triggers_publish():
    bus, published, _, _ = _wire(_conclusive_metrics())
    bus.emit(Event(type=JOB_COMPLETED, key="reel-1", payload={"output_refs": ["u"]}))
    assert published == [("reel-1", {"output_refs": ["u"]})]


def test_retention_cascades_to_regenerate_when_conclusive():
    bus, _, regenerated, regen_events = _wire(_conclusive_metrics())
    bus.emit(Event(type=RETENTION_INGESTED, key="exp-1", payload={"experiment_key": "exp-1"}))
    # Winner 'a'/hookA cascades: on_regenerate called + REGENERATE_REQUESTED emitted.
    assert regenerated == [("exp-1", "hookA")]
    assert regen_events and regen_events[0]["bias_hook_ref"] == "hookA"


def test_inconclusive_retention_does_not_regenerate():
    # Underpowered variants -> no winner -> no cascade.
    weak = [
        VariantMetrics("a", "hookA", views=10, completion_rate=0.8),
        VariantMetrics("b", "hookB", views=10, completion_rate=0.4),
    ]
    bus, _, regenerated, regen_events = _wire(weak)
    bus.emit(Event(type=RETENTION_INGESTED, key="exp-1"))
    assert regenerated == [] and regen_events == []
