"""Thompson-sampling budget allocation across ad creatives (pure).

Python port of Rally's Beta-Bernoulli bandit (``lib/autogtm/bandit.ts``): each
creative is an arm whose unknown parameter is its success rate — link CTR
(clicks / impressions) for traffic campaigns, or lead rate (leads / clicks) when
the campaign optimizes for leads. Budget shares come from P(arm is best),
estimated by Monte Carlo draws from each Beta posterior with a seeded RNG so a
given optimize pass is reproducible.

Rules layered on top (mirroring the organic winner loop's guards in
``app.domains.publishing.experiments``: a minimum sample before anything is
called, and a margin before a winner is declared):

* every kept arm gets at least the platform's minimum daily budget;
* when the total cannot fund every arm at the minimum, the arms with the lowest
  P(best) are paused first (never all of them);
* an arm is pruned (budget 0, paused) only once every arm has at least
  ``min_trials`` of evidence and its P(best) fell below ``prune_below``;
* a winner is declared when every arm has ``min_trials`` and one arm's P(best)
  is at least ``winner_at``.

No DB, clock or network.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

DEFAULT_DRAWS = 4000
DEFAULT_MIN_TRIALS = 1000      # impressions (CTR) or clicks (lead rate) per arm
DEFAULT_PRUNE_BELOW = 0.02
DEFAULT_WINNER_AT = 0.95


@dataclass(frozen=True)
class Arm:
    """Evidence for one creative. ``trials`` >= ``successes`` >= 0."""

    arm_id: str
    trials: int = 0
    successes: int = 0


@dataclass(frozen=True)
class ArmAllocation:
    arm_id: str
    p_best: float
    mean_rate: float
    budget_minor: int
    active: bool
    reason: str

    def to_record(self) -> dict:
        return {
            "arm_id": self.arm_id,
            "p_best": round(self.p_best, 4),
            "mean_rate": round(self.mean_rate, 6),
            "budget_minor": self.budget_minor,
            "active": self.active,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Allocation:
    arms: tuple[ArmAllocation, ...]
    total_minor: int
    winner_id: str = ""
    conclusive: bool = False
    reason: str = ""
    seed: int = 0
    extra: dict = field(default_factory=dict)

    def to_record(self) -> dict:
        return {
            "arms": [a.to_record() for a in self.arms],
            "total_minor": self.total_minor,
            "winner_id": self.winner_id,
            "conclusive": self.conclusive,
            "reason": self.reason,
            "seed": self.seed,
        }


def seed_from_string(value: str) -> int:
    """FNV-1a 32-bit hash, identical to Rally's ``seedFromString``."""
    h = 0x811C9DC5
    for ch in value.encode("utf-8"):
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def posterior(arm: Arm, prior_alpha: float = 1.0, prior_beta: float = 1.0) -> tuple[float, float]:
    trials = max(0, int(arm.trials))
    successes = max(0, min(int(arm.successes), trials))
    return prior_alpha + successes, prior_beta + (trials - successes)


def win_probabilities(arms: list[Arm], rng: random.Random, draws: int = DEFAULT_DRAWS) -> list[float]:
    """Monte Carlo P(arm i has the highest rate); sums to 1 for non-empty input."""
    n = len(arms)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    params = [posterior(a) for a in arms]
    wins = [0] * n
    rounds = max(1, int(draws))
    for _ in range(rounds):
        best_idx, best = 0, -1.0
        for i, (a, b) in enumerate(params):
            sample = rng.betavariate(a, b)
            if sample > best:
                best, best_idx = sample, i
        wins[best_idx] += 1
    return [w / rounds for w in wins]


def _split(total: int, floor: int, weights: dict[str, float], order: list[str]) -> dict[str, int]:
    """Give each id ``floor`` then share the remainder by weight (integer minor units)."""
    remainder = total - floor * len(order)
    weight_sum = sum(weights[i] for i in order) or float(len(order))
    budgets = {}
    for arm_id in order:
        share = weights[arm_id] / weight_sum if weight_sum else 1.0 / len(order)
        budgets[arm_id] = floor + int(remainder * share)
    # Rounding leftovers go to the strongest arm so the total is exact.
    leftover = total - sum(budgets.values())
    if order:
        budgets[order[0]] += leftover
    return budgets


def allocate(
    arms: list[Arm],
    total_minor: int,
    min_per_arm_minor: int,
    *,
    seed: int = 0,
    draws: int = DEFAULT_DRAWS,
    min_trials: int = DEFAULT_MIN_TRIALS,
    prune_below: float = DEFAULT_PRUNE_BELOW,
    winner_at: float = DEFAULT_WINNER_AT,
) -> Allocation:
    """Split ``total_minor`` per day across ``arms`` by P(best)."""
    if not arms:
        return Allocation(arms=(), total_minor=0, reason="no creatives", seed=seed)
    floor = max(1, int(min_per_arm_minor))
    total = max(0, int(total_minor))
    rng = random.Random(seed)
    probs = win_probabilities(arms, rng, draws)
    p_best = {a.arm_id: p for a, p in zip(arms, probs)}
    means = {}
    for arm in arms:
        a, b = posterior(arm)
        means[arm.arm_id] = a / (a + b)

    powered = all(a.trials >= min_trials for a in arms)
    ranked = sorted(arms, key=lambda a: (p_best[a.arm_id], means[a.arm_id]), reverse=True)
    reasons: dict[str, str] = {}
    kept = [a.arm_id for a in ranked]

    if powered and len(kept) > 1:
        survivors = [i for i in kept if p_best[i] >= prune_below]
        for arm_id in kept:
            if arm_id not in survivors:
                reasons[arm_id] = f"paused: {p_best[arm_id]:.1%} chance of being best after {min_trials}+ trials"
        kept = survivors or kept[:1]

    affordable = max(1, total // floor) if total >= floor else 0
    if affordable == 0:
        kept = []
        for arm in ranked:
            reasons.setdefault(arm.arm_id, "paused: daily budget is below the platform minimum")
    elif len(kept) > affordable:
        for arm_id in kept[affordable:]:
            reasons.setdefault(arm_id, "paused: daily budget cannot fund every creative at the platform minimum")
        kept = kept[:affordable]

    # With no evidence at all the posteriors are identical: split evenly rather
    # than by Monte Carlo noise.
    no_data = all(a.trials == 0 for a in arms)
    weights = {i: 1.0 for i in p_best} if no_data else p_best
    budgets = _split(total, floor, weights, kept) if kept else {}
    out = []
    for arm in ranked:
        active = arm.arm_id in budgets
        reason = reasons.get(arm.arm_id) or ("exploring: not enough data yet" if not powered else "funded by chance of being best")
        out.append(ArmAllocation(
            arm_id=arm.arm_id, p_best=p_best[arm.arm_id], mean_rate=means[arm.arm_id],
            budget_minor=budgets.get(arm.arm_id, 0), active=active, reason=reason,
        ))

    leader = ranked[0].arm_id
    conclusive = powered and len(arms) > 1 and p_best[leader] >= winner_at
    if len(arms) == 1:
        summary = "single creative: full budget"
    elif not powered:
        summary = f"exploring: every creative needs {min_trials} trials before a winner is called"
    elif conclusive:
        summary = f"winner: {p_best[leader]:.1%} chance of being best"
    else:
        summary = f"no clear winner yet (leader at {p_best[leader]:.1%})"
    return Allocation(
        arms=tuple(out), total_minor=sum(budgets.values()), winner_id=leader if conclusive else "",
        conclusive=conclusive, reason=summary, seed=seed,
    )


__all__ = ["Arm", "ArmAllocation", "Allocation", "allocate", "posterior", "seed_from_string", "win_probabilities"]
