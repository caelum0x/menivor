"""Which lane encodes an OTT source (MV2, ADR-0004 default).

* ``box1``: sources of 3 min or less **and** 1080p or less only (short side).
  A 60-minute 1080p upload never lands here.
* ``mac``: long-form, only while a Mac node's heartbeat is under 60 s old and it
  has more than 10 GB free.
* ``burst``: long-form for paying plans only, while this month's burst spend
  plus the estimate stays under the MD6 cap (EUR 20 a month by default).
* Otherwise the job waits for the Mac (``mac``, queued); it is never moved to box 1.
The Bunny pass-through lane stays off (``OTT_BUNNY_LANE``, owner decision OD-MV4).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .models import LANE_BOX1, LANE_BURST, LANE_MAC

BOX1_MAX_SECONDS = 180.0
BOX1_MAX_SHORT_SIDE = 1080
DEFAULT_BURST_CAP_EUR = 20.0
DEFAULT_EUR_USD = 1.08
#: CPU-hours a 4-rung ladder needs per source hour on a burst box (est., ADR-0004: 2-4 on box 1).
BURST_CPU_HOURS_PER_SOURCE_HOUR = 3.0
DEFAULT_BURST_USD_PER_CPU_HOUR = 0.05


@dataclass(frozen=True)
class Choice:
    lane: str
    reason: str
    estimate_usd: float = 0.0


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def burst_cap_usd() -> float:
    return _float_env("OTT_BURST_MONTHLY_CAP_EUR", DEFAULT_BURST_CAP_EUR) * _float_env("OTT_EUR_USD", DEFAULT_EUR_USD)


def burst_estimate_usd(seconds: float) -> float:
    rate = _float_env("OTT_BURST_USD_PER_CPU_HOUR", DEFAULT_BURST_USD_PER_CPU_HOUR)
    return round(seconds / 3600.0 * BURST_CPU_HOURS_PER_SOURCE_HOUR * rate, 4)


def box1_allowed(seconds: float, short_side: int) -> bool:
    return seconds <= BOX1_MAX_SECONDS and short_side <= BOX1_MAX_SHORT_SIDE


def pick(*, seconds: float, short_side: int, paid_plan: bool, mac_live: bool, burst_live: bool,
         burst_spent_usd: float) -> Choice:
    if box1_allowed(seconds, short_side):
        return Choice(LANE_BOX1, "short source: box 1, tier 3")
    if mac_live:
        return Choice(LANE_MAC, "long-form: the Mac node is online")
    estimate = burst_estimate_usd(seconds)
    if paid_plan and burst_live and burst_spent_usd + estimate <= burst_cap_usd():
        return Choice(LANE_BURST, "long-form on a paid plan: burst under the monthly cap", estimate)
    return Choice(LANE_MAC, "long-form: waiting for the Mac node")


__all__ = ["BOX1_MAX_SECONDS", "BOX1_MAX_SHORT_SIDE", "Choice", "box1_allowed", "burst_cap_usd",
           "burst_estimate_usd", "pick"]
