"""Dependency-free Prometheus-compatible metrics registry.

The observability plane (``infra/observability/slo.yaml`` + the OTel collector +
the Grafana alert rules) references specific series — most importantly the wallet
**success-only-billing invariant** (``wallet_debit_micros`` vs. ``render_jobs``).
This module emits those series in the Prometheus text-exposition format from an
in-process registry, so ``GET /metrics`` is scrapeable without adding a
third-party dependency. Thread-safe via a simple lock; fully unit-testable.

Named helpers wrap the exact label sets the SLO/alert rules query, so a rename is
caught in one place. Emission is best-effort (never raises into a hot path).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

_DEFAULT_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)


def _labels_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _fmt_labels(key: tuple[tuple[str, str], ...], extra: dict[str, str] | None = None) -> str:
    pairs = list(key)
    if extra:
        pairs = sorted([*pairs, *[(k, v) for k, v in extra.items()]])
    if not pairs:
        return ""
    inner = ",".join(f'{k}="{_escape(v)}"' for k, v in pairs)
    return "{" + inner + "}"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass
class _Counter:
    name: str
    help: str
    values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)

    def inc(self, labels: dict[str, str], amount: float = 1.0) -> None:
        key = _labels_key(labels)
        self.values[key] = self.values.get(key, 0.0) + amount

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        for key, val in sorted(self.values.items()):
            out.append(f"{self.name}{_fmt_labels(key)} {_num(val)}")
        return out


@dataclass
class _Histogram:
    name: str
    help: str
    buckets: tuple[float, ...] = _DEFAULT_BUCKETS
    # per-labelset: (bucket_counts, sum, count)
    series: dict[tuple[tuple[str, str], ...], tuple[list[int], float, int]] = field(default_factory=dict)

    def observe(self, labels: dict[str, str], value: float) -> None:
        # ``counts[i]`` is the CUMULATIVE number of observations <= buckets[i]
        # (Prometheus bucket semantics), so ``render`` emits them directly.
        key = _labels_key(labels)
        counts, total, n = self.series.get(key, ([0] * len(self.buckets), 0.0, 0))
        counts = list(counts)
        for i, edge in enumerate(self.buckets):
            if value <= edge:
                counts[i] += 1
        self.series[key] = (counts, total + value, n + 1)

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key, (counts, total, n) in sorted(self.series.items()):
            for i, edge in enumerate(self.buckets):
                out.append(f"{self.name}_bucket{_fmt_labels(key, {'le': _num(edge)})} {counts[i]}")
            out.append(f"{self.name}_bucket{_fmt_labels(key, {'le': '+Inf'})} {n}")
            out.append(f"{self.name}_sum{_fmt_labels(key)} {_num(total)}")
            out.append(f"{self.name}_count{_fmt_labels(key)} {n}")
        return out


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


class Registry:
    """A tiny metrics registry rendering the Prometheus text format."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, _Counter] = {}
        self._histograms: dict[str, _Histogram] = {}

    def counter(self, name: str, help: str = "") -> _Counter:
        with self._lock:
            c = self._counters.get(name)
            if c is None:
                c = _Counter(name, help or name)
                self._counters[name] = c
            return c

    def histogram(self, name: str, help: str = "", buckets: tuple[float, ...] = _DEFAULT_BUCKETS) -> _Histogram:
        with self._lock:
            h = self._histograms.get(name)
            if h is None:
                h = _Histogram(name, help or name, buckets)
                self._histograms[name] = h
            return h

    def render(self) -> str:
        with self._lock:
            lines: list[str] = []
            for c in self._counters.values():
                lines.extend(c.render())
            for h in self._histograms.values():
                lines.extend(h.render())
        return "\n".join(lines) + ("\n" if lines else "")


# Process-wide registry.
REGISTRY = Registry()


# --------------------------------------------------------------------------- #
# Named emitters — the exact series the SLO/alert rules reference.
# --------------------------------------------------------------------------- #
def record_render_state(state: str) -> None:
    """``render_jobs{state=...}`` — a job reached a terminal/observed state."""
    try:
        REGISTRY.counter("render_jobs", "async render jobs by state").inc({"state": str(state)})
    except Exception:  # pragma: no cover - metrics are best-effort
        pass


def record_wallet_debit(reason: str, micros: int) -> None:
    """``wallet_debit_micros{reason=...}`` — micro-USD actually charged."""
    try:
        REGISTRY.counter("wallet_debit_micros", "wallet debit micros by reason").inc(
            {"reason": str(reason)}, float(max(0, int(micros)))
        )
    except Exception:  # pragma: no cover
        pass


def record_media_gateway_job(modality: str, provider: str, status: str) -> None:
    """``media_gateway_jobs{modality,provider,status}`` — a unified-gateway
    image/video generation reached a terminal outcome. Paired with
    ``wallet_debit_micros{reason=gateway}`` on success only (success-only billing)."""
    try:
        REGISTRY.counter("media_gateway_jobs", "media gateway jobs by modality/provider/status").inc(
            {"modality": str(modality), "provider": str(provider), "status": str(status)}
        )
    except Exception:  # pragma: no cover
        pass


def record_native_publish(status: str) -> None:
    """``native_publish{status=...}`` — a native publish outcome."""
    try:
        REGISTRY.counter("native_publish", "native publish outcomes").inc({"status": str(status)})
    except Exception:  # pragma: no cover
        pass


def record_license_block(tier: str, license_class: str) -> None:
    """``route_license_block_total{tier,class}`` — a route blocked by the license gate."""
    try:
        REGISTRY.counter("route_license_block_total", "routes blocked by the license gate").inc(
            {"tier": str(tier), "class": str(license_class)}
        )
    except Exception:  # pragma: no cover
        pass


def observe_hook_score_duration(seconds: float) -> None:
    """``hook_score_duration_seconds`` — hook-scoring latency."""
    try:
        REGISTRY.histogram("hook_score_duration_seconds", "hook scoring latency").observe({}, float(seconds))
    except Exception:  # pragma: no cover
        pass


def record_moderation_hop(hop: str, outcome: str, seconds: float | None = None) -> None:
    """``moderation_hop_total{hop,outcome}`` (+ ``moderation_hop_seconds{hop}``) —
    one prompt-moderation provider hop: allow/flag/deny, rate_limited, error or
    cooldown_skip. Only labels; never prompt text."""
    try:
        REGISTRY.counter("moderation_hop_total", "moderation provider hops by outcome").inc(
            {"hop": str(hop), "outcome": str(outcome)}
        )
        if seconds is not None:
            REGISTRY.histogram("moderation_hop_seconds", "moderation provider hop latency").observe(
                {"hop": str(hop)}, float(seconds)
            )
    except Exception:  # pragma: no cover
        pass


def render_metrics() -> str:
    """The full ``/metrics`` exposition body."""
    return REGISTRY.render()
