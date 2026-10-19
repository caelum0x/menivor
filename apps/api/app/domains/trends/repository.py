"""TrendObservation repository — record scored trends + surface recommendations.

Scores a :class:`TrendSignal` via the pure ``trends.scoring`` core and persists the
observation, then answers the trends feed's "what should I build to now?" with the
latest recommended (rising, not-peaked) trends.
"""

from __future__ import annotations

from typing import Any

from app.domains.trends.scoring import TrendSignal, score_trend
from app.models.db.trends import TrendObservation


class TrendRepository:
    """Append + query scored trend observations."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def record(self, signal: TrendSignal) -> TrendObservation:
        score = score_trend(signal)
        row = TrendObservation(
            trend_id=signal.trend_id, kind=signal.kind, label=signal.label,
            counts=list(signal.counts),
            opportunity_bps=int(round(score.opportunity * 10000)),
            saturation_bps=int(round(score.saturation * 10000)),
            phase=score.phase, recommend=score.recommend,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def recommended(self, *, limit: int = 20) -> list[TrendObservation]:
        """Latest recommended trends, highest opportunity first."""
        return (
            self._s.query(TrendObservation)
            .filter(TrendObservation.recommend.is_(True))
            .order_by(TrendObservation.opportunity_bps.desc(), TrendObservation.observed_at.desc())
            .limit(limit)
            .all()
        )
