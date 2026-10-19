"""Provider health service — record run outcomes, derive uptime, feed routing.

Aggregates append-only ``provider_health_events`` over a recent window into an
uptime %, average latency, and a normalized ``health_state`` (healthy | degraded
| down | unknown). The routing layer reads the current ``provider_catalogs.health_state``
to health-weight selection; a status view exposes the summary publicly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from app.models.db.marketplace import ProviderCatalog, ProviderHealthEvent

# Uptime thresholds for the derived state.
_HEALTHY_MIN = 0.95
_DEGRADED_MIN = 0.75
# Minimum samples before a summary overrides 'unknown'.
_MIN_SAMPLES = 3
_DEFAULT_WINDOW_H = 24


def _since_hours(hours: int) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=max(1, hours))


def _state_from_uptime(uptime: float, samples: int) -> str:
    if samples < _MIN_SAMPLES:
        return "unknown"
    if uptime >= _HEALTHY_MIN:
        return "healthy"
    if uptime >= _DEGRADED_MIN:
        return "degraded"
    return "down"


class ProviderHealthService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self, provider_key: str, *, ok: bool, latency_ms: int = 0, capability: str = ""
    ) -> None:
        """Append one provider run observation (best-effort; never raises)."""
        if not provider_key:
            return
        self._session.add(
            ProviderHealthEvent(
                provider_key=provider_key,
                capability=capability or "",
                ok=bool(ok),
                latency_ms=max(0, int(latency_ms or 0)),
            )
        )
        self._session.flush()

    def summary(self, provider_key: str, *, window_h: int = _DEFAULT_WINDOW_H) -> dict:
        """Uptime %, avg latency, sample count, and derived state for a provider."""
        since = _since_hours(window_h)
        row = self._session.execute(
            select(
                func.count().label("n"),
                func.coalesce(func.sum(cast(ProviderHealthEvent.ok, Integer)), 0).label("oks"),
                func.coalesce(func.avg(ProviderHealthEvent.latency_ms), 0).label("lat"),
            ).where(
                ProviderHealthEvent.provider_key == provider_key,
                ProviderHealthEvent.created_at >= since,
            )
        ).one()
        n = int(row.n or 0)
        oks = int(row.oks or 0)
        uptime = (oks / n) if n else 0.0
        return {
            "provider_key": provider_key,
            "window_h": max(1, window_h),
            "samples": n,
            "uptime": round(uptime, 4),
            "avg_latency_ms": int(row.lat or 0),
            "state": _state_from_uptime(uptime, n),
        }

    def refresh_state(self, provider_key: str, *, window_h: int = _DEFAULT_WINDOW_H) -> str:
        """Recompute + persist ``provider_catalogs.health_state``. Returns the state."""
        summary = self.summary(provider_key, window_h=window_h)
        provider = self._session.execute(
            select(ProviderCatalog).where(ProviderCatalog.provider_key == provider_key)
        ).scalars().first()
        if provider is not None:
            provider.health_state = summary["state"]
            provider.updated_at = datetime.now(timezone.utc)
            self._session.flush()
        return summary["state"]

    def status(self, *, window_h: int = _DEFAULT_WINDOW_H) -> list[dict]:
        """Health summary for every provider that has an observation in-window."""
        since = _since_hours(window_h)
        keys = [
            str(k)
            for (k,) in self._session.execute(
                select(ProviderHealthEvent.provider_key)
                .where(ProviderHealthEvent.created_at >= since)
                .distinct()
            ).all()
        ]
        return [self.summary(k, window_h=window_h) for k in sorted(keys)]
