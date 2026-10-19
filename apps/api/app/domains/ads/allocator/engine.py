"""Cross-network budget split by Thompson sampling on cost per result (pure).

Each network is an arm whose unknown parameter is its *result rate*: results
per one unit of account currency spent (the inverse of cost per result).
Results arrive roughly as a Poisson process in spend, so the conjugate
posterior is a Gamma::

    rate ~ Gamma(shape = a0 + results, rate = b0 + spend)

The prior is pooled across networks (``a0 = PRIOR_RESULTS`` pseudo-results at
the account's blended rate), so a network with little spend starts near the
average instead of at an arbitrary guess, and a network with lots of evidence
dominates its own prior.

P(network has the best rate) is estimated by Monte Carlo with a seeded RNG, so
a given day's proposal is reproducible. The proposed split is::

    target_i   = min_share + (1 - n * min_share) * P(best_i)
    proposed   = current + k * (target - current)

where ``k <= 1`` scales every move so no network changes by more than
``max_step`` of the total in one proposal (the deltas sum to zero, so the
proposed split still sums to 1).

No DB, clock or network.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

DEFAULT_DRAWS = 4000
PRIOR_RESULTS = 2.0
NO_CHANGE_BELOW = 0.005  # moves under half a point are reported as "hold"

METHOD_THOMPSON = "thompson"
METHOD_RULES = "rules"


@dataclass(frozen=True)
class NetworkStats:
    """Evidence for one network. Spend in account-currency minor units."""

    network: str
    spend_minor: int = 0
    results: int = 0
    impressions: int = 0
    clicks: int = 0
    leads: int | None = None
    current_daily_minor: int = 0
    campaigns: int = 0
    source: str = "measured"  # measured (platform API) | manual (entered by the user)

    def to_record(self) -> dict:
        return {
            "network": self.network,
            "spend_minor": int(self.spend_minor),
            "results": int(self.results),
            "impressions": int(self.impressions),
            "clicks": int(self.clicks),
            "leads": self.leads,
            "current_daily_minor": int(self.current_daily_minor),
            "campaigns": int(self.campaigns),
            "source": self.source,
        }


@dataclass(frozen=True)
class SplitPlan:
    proposed: dict[str, float]
    current: dict[str, float]
    p_best: dict[str, float]
    max_delta: float
    method: str
    reason: str
    warnings: dict[str, str] = field(default_factory=dict)

    def changes(self) -> dict[str, float]:
        return {n: round(self.proposed[n] - self.current.get(n, 0.0), 4) for n in self.proposed}


def cost_per_result_minor(stats: NetworkStats) -> float | None:
    """Spend / results in minor units; ``None`` when there are no results (never an invented 0)."""
    if stats.results <= 0:
        return None
    return round(stats.spend_minor / stats.results, 2)


def sample_warning(stats: NetworkStats, min_results: int) -> str:
    if stats.spend_minor <= 0 and stats.results <= 0:
        return "No spend recorded yet, so there is nothing to compare."
    if stats.results <= 0:
        return "Spend but no results yet. Cost per result is unknown, not zero."
    if stats.results < min_results:
        return f"Only {stats.results} results (fewer than {min_results}). Treat this cost per result as a rough estimate."
    return ""


def normalize(split: dict[str, float], networks: list[str]) -> dict[str, float]:
    """Clamp to >= 0 over ``networks`` and rescale to sum 1 (equal split when empty)."""
    clean = {n: max(0.0, float(split.get(n, 0.0) or 0.0)) for n in networks}
    total = sum(clean.values())
    if total <= 0:
        return {n: 1.0 / len(networks) for n in networks} if networks else {}
    return {n: v / total for n, v in clean.items()}


def current_split(stats: list[NetworkStats]) -> dict[str, float]:
    networks = [s.network for s in stats]
    return normalize({s.network: float(s.current_daily_minor) for s in stats}, networks)


def _round_split(split: dict[str, float], order: list[str]) -> dict[str, float]:
    """Round to 4 decimals while keeping the sum exactly 1."""
    rounded = {n: round(split[n], 4) for n in order}
    drift = round(1.0 - sum(rounded.values()), 4)
    if order and drift:
        top = max(order, key=lambda n: rounded[n])
        rounded[top] = round(rounded[top] + drift, 4)
    return rounded


def win_probabilities(stats: list[NetworkStats], rng: random.Random, draws: int = DEFAULT_DRAWS) -> dict[str, float]:
    """Monte Carlo P(network has the highest results-per-spend rate)."""
    if not stats:
        return {}
    if len(stats) == 1:
        return {stats[0].network: 1.0}
    total_spend = float(sum(max(0, s.spend_minor) for s in stats))
    total_results = sum(max(0, s.results) for s in stats)
    pooled = (total_results / total_spend) if total_spend > 0 and total_results > 0 else 1.0
    a0, b0 = PRIOR_RESULTS, PRIOR_RESULTS / pooled
    # Rates are per minor unit; the ranking is invariant to the money unit.
    params = [(a0 + max(0, s.results), b0 + max(0, s.spend_minor)) for s in stats]
    wins = [0] * len(stats)
    rounds = max(1, int(draws))
    for _ in range(rounds):
        best_idx, best = 0, -1.0
        for i, (shape, rate) in enumerate(params):
            sample = rng.gammavariate(shape, 1.0 / rate)
            if sample > best:
                best, best_idx = sample, i
        wins[best_idx] += 1
    return {s.network: w / rounds for s, w in zip(stats, wins)}


def plan_split(
    stats: list[NetworkStats],
    *,
    seed: int,
    max_step: float,
    min_share: float,
    min_results: int,
    draws: int = DEFAULT_DRAWS,
) -> SplitPlan:
    """The proposed split for ``stats`` (order preserved)."""
    networks = [s.network for s in stats]
    current = current_split(stats)
    warnings = {s.network: w for s in stats if (w := sample_warning(s, min_results))}
    if not networks:
        return SplitPlan({}, {}, {}, 0.0, METHOD_RULES, "No networks to compare.", warnings)
    hold = _round_split(current, networks)
    with_results = [s for s in stats if s.results > 0]
    if len(networks) == 1:
        return SplitPlan(hold, hold, {networks[0]: 1.0}, 0.0, METHOD_RULES,
                         "Only one network has data, so the whole budget stays there.", warnings)
    if not with_results:
        return SplitPlan(hold, hold, {n: 1.0 / len(networks) for n in networks}, 0.0, METHOD_RULES,
                         "No network has reported a result yet. Keeping the current split.", warnings)

    p_best = win_probabilities(stats, random.Random(seed), draws)
    floor = min_share if min_share * len(networks) < 1.0 else 0.0
    free = 1.0 - floor * len(networks)
    target = {n: floor + free * p_best[n] for n in networks}
    deltas = {n: target[n] - current[n] for n in networks}
    biggest = max(abs(d) for d in deltas.values())
    scale = min(1.0, max_step / biggest) if biggest > 0 else 0.0
    proposed = _round_split({n: current[n] + scale * deltas[n] for n in networks}, networks)
    max_delta = round(max(abs(proposed[n] - hold[n]) for n in networks), 4)

    leader = max(networks, key=lambda n: p_best[n])
    powered = all(s.results >= min_results for s in stats)
    if max_delta < NO_CHANGE_BELOW:
        reason = f"Hold: the current split already matches the evidence ({leader} leads at {p_best[leader]:.0%})."
    elif not powered:
        reason = (f"{leader} looks cheapest per result ({p_best[leader]:.0%} chance of being best), but some networks "
                  f"have fewer than {min_results} results, so the move is small.")
    else:
        reason = f"{leader} has a {p_best[leader]:.0%} chance of the lowest cost per result."
    if scale < 1.0 and max_delta >= NO_CHANGE_BELOW:
        reason += f" Capped at {max_step:.0%} of the budget per network per day."
    return SplitPlan(proposed, hold, {n: round(p, 4) for n, p in p_best.items()}, max_delta, METHOD_THOMPSON,
                     reason, warnings)


def split_budget(total: int, split: dict[str, float]) -> dict[str, int]:
    """Integer budgets per network that add up to exactly ``total``."""
    order = list(split)
    if not order or total <= 0:
        return {n: 0 for n in order}
    budgets = {n: int(total * split[n]) for n in order}
    leftover = total - sum(budgets.values())
    if leftover:
        top = max(order, key=lambda n: split[n])
        budgets[top] += leftover
    return budgets


__all__ = [
    "METHOD_RULES",
    "METHOD_THOMPSON",
    "NetworkStats",
    "SplitPlan",
    "cost_per_result_minor",
    "current_split",
    "normalize",
    "plan_split",
    "sample_warning",
    "split_budget",
    "win_probabilities",
]
