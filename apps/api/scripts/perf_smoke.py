#!/usr/bin/env python3
"""Deterministic perf smoke for hot, pure code paths (no I/O, CI-safe).

Guards against accidental algorithmic regressions (e.g. an O(n^2) creeping into
catalog resolution or the money math) by timing tight loops and asserting a
per-op budget. Budgets are generous — this catches order-of-magnitude slips, not
micro-jitter. Exits non-zero on a breach so `perf.yml` fails the build.

Run: ``python scripts/perf_smoke.py`` (from ``apps/api``).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

# Make ``app`` importable when run as a script from apps/api.
_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

# Budgets in microseconds per operation (wall clock). Deliberately loose —
# this catches order-of-magnitude slips, not micro-jitter.
#
# CI for this job moved from a dedicated ubuntu-latest runner to a shared
# self-hosted box (recoder-micro: 2 vCPUs, 956Mi RAM, time-sliced with two
# other repos' runners) to route around a billing block. That box is simply
# slower and noisier, so the original ubuntu-latest-era budgets broke on
# every run. Re-measured live on that runner (12 consecutive samples):
# catalog.get_model 2.9-7.5us, catalog.list_models 65-176us,
# gateway.cost_math 3.1-6.5us, envelope.parse 7.8-22.1us. Budgets below give
# ~2-3x headroom over the worst observed sample on that hardware.
_BUDGETS_US = {
    "catalog.get_model": 20.0,
    "catalog.list_models": 350.0,
    "gateway.cost_math": 20.0,
    "envelope.parse": 60.0,
}


def _bench(name: str, fn: Callable[[], object], iters: int) -> float:
    fn()  # warm
    start = time.perf_counter()
    for _ in range(iters):
        fn()
    elapsed = time.perf_counter() - start
    per_op_us = (elapsed / iters) * 1_000_000
    return per_op_us


def main() -> int:
    from app.domains.gateway.media_catalog import get_model, list_models

    results: dict[str, float] = {}

    results["catalog.get_model"] = _bench(
        "catalog.get_model", lambda: get_model("kwaivgi/kling-v1.6"), 200_000
    )
    results["catalog.list_models"] = _bench(
        "catalog.list_models", lambda: list_models("image"), 20_000
    )

    def _cost() -> int:
        m = get_model("kwaivgi/kling-v1.6")
        return 5 * m.price_micros if m else 0

    results["gateway.cost_math"] = _bench("gateway.cost_math", _cost, 200_000)

    # Envelope parse (mirrors the desktop rf-gateway parser shape).
    import json

    raw = '{"status":200,"data":{"id":"v1","status":"completed","url":"u","cost_micros":420000}}'

    def _parse() -> object:
        env = json.loads(raw)
        return env.get("data") if 200 <= int(env.get("status", 0)) < 300 else None

    results["envelope.parse"] = _bench("envelope.parse", _parse, 100_000)

    ok = True
    print(f"{'path':24} {'us/op':>10} {'budget':>10}  status")
    for name, budget in _BUDGETS_US.items():
        us = results[name]
        breached = us > budget
        ok = ok and not breached
        print(f"{name:24} {us:10.3f} {budget:10.3f}  {'BREACH' if breached else 'ok'}")

    if not ok:
        print("\nperf smoke FAILED — a hot path exceeded its budget", file=sys.stderr)
        return 1
    print("\nperf smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
