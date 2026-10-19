"""Experiment repository — persist variants, ingest retention, resolve the winner.

Bridges the pure ``experiments.select_winner`` to the DB: create an experiment
with its hook variants, ingest retention metrics per variant (from the publishing
analytics pull), and evaluate — persisting the winner + status when the sample is
conclusive so the flywheel can regenerate biased toward the winning hook.
"""

from __future__ import annotations

from typing import Any

from app.domains.publishing.experiments import VariantMetrics, select_winner
from app.models.db.experiments import Experiment, ExperimentVariant


class ExperimentError(ValueError):
    """An invalid experiment operation (unknown experiment/variant)."""


class ExperimentRepository:
    """CRUD + evaluation for A/B experiments."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def create(self, *, user_id: str, experiment_key: str, hook_refs: list[str], body_ref: str = "") -> Experiment:
        if len(hook_refs) < 2:
            raise ExperimentError("an experiment needs at least 2 hook variants")
        exp = Experiment(user_id=user_id, experiment_key=experiment_key, body_ref=body_ref)
        self._s.add(exp)
        self._s.flush()
        for hook in hook_refs:
            self._s.add(ExperimentVariant(experiment_id=exp.id, hook_ref=hook))
        self._s.flush()
        return exp

    def get_by_key(self, experiment_key: str) -> Experiment | None:
        return (
            self._s.query(Experiment)
            .filter(Experiment.experiment_key == experiment_key)
            .one_or_none()
        )

    def variants(self, experiment_id: str) -> list[ExperimentVariant]:
        return (
            self._s.query(ExperimentVariant)
            .filter(ExperimentVariant.experiment_id == experiment_id)
            .order_by(ExperimentVariant.hook_ref.asc())
            .all()
        )

    def ingest_metrics(
        self, *, experiment_key: str, variant_id: str, views: int,
        completion_rate: float | None, avg_watch_frac: float,
        rewatch_rate: float | None = None, engagement_rate: float = 0.0,
    ) -> ExperimentVariant:
        """Overwrite a variant's accumulated retention metrics (latest snapshot).

        ``completion_rate`` / ``rewatch_rate`` of ``None`` mean "not measured"
        and are stored as NULL, never as a measured 0%.
        """
        exp = self.get_by_key(experiment_key)
        if exp is None:
            raise ExperimentError(f"unknown experiment {experiment_key!r}")
        variant = self._s.get(ExperimentVariant, variant_id)
        if variant is None or variant.experiment_id != exp.id:
            raise ExperimentError(f"unknown variant {variant_id!r} for {experiment_key!r}")
        variant.views = int(views)
        variant.completion_rate = None if completion_rate is None else float(completion_rate)
        variant.avg_watch_frac = float(avg_watch_frac)
        variant.rewatch_rate = None if rewatch_rate is None else float(rewatch_rate)
        variant.engagement_rate = float(engagement_rate)
        self._s.flush()
        return variant

    def evaluate(self, experiment_key: str) -> Experiment:
        """Run winner selection over the persisted variants; persist the verdict."""
        exp = self.get_by_key(experiment_key)
        if exp is None:
            raise ExperimentError(f"unknown experiment {experiment_key!r}")
        metrics = [
            VariantMetrics(
                variant_id=v.id, hook_ref=v.hook_ref, views=v.views,
                completion_rate=v.completion_rate, avg_watch_frac=v.avg_watch_frac,
                rewatch_rate=v.rewatch_rate, engagement_rate=v.engagement_rate,
            )
            for v in self.variants(exp.id)
        ]
        result = select_winner(metrics)
        if result.conclusive:
            exp.status = "conclusive"
            exp.winner_variant_id = result.winner_id
            exp.winner_hook_ref = result.winner_hook_ref
        else:
            exp.status = "running"  # not yet conclusive — keep gathering data
        self._s.flush()
        return exp
