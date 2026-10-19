"""Pure provider-routing policy (no DB, no network, no adapters).

Decides which candidate route(s) are admissible for a request and their order.
ReelForge begins with deterministic **user-selected** routes; automatic fallback
is opt-in only and never substitutes a different/more-expensive provider without
consent and a max-cost cap (PROVIDER_MARKETPLACE_PLAN.md §8/§9.2).
"""

from __future__ import annotations

from dataclasses import dataclass

# Fallback modes. ``none`` = exactly the selected route or nothing. ``equivalent``
# = the selected route plus same-capability alternatives within the cost cap.
FALLBACK_NONE = "none"
FALLBACK_EQUIVALENT = "equivalent"

# Latency ordering preference (lower index = preferred) for tie-breaking.
_LATENCY_RANK = {"fast": 0, "standard": 1, "slow": 2, "": 3}


@dataclass(frozen=True)
class Candidate:
    """A resolved routing candidate: one model + its provider + estimated cost.

    ``est_cost_micros`` is the service-computed estimate for the request against
    this candidate's active price version; policy compares it to the cap.
    """

    model_id: str
    provider_key: str
    capability: str
    est_cost_micros: int
    region: str = ""
    availability_state: str = "available"
    latency_band: str = ""
    price_version_id: str = ""
    # Provider health (healthy|degraded|down|unknown) — soft routing weight.
    health_state: str = "unknown"


# Sort strategies for consented fallbacks (OpenRouter-style provider object).
SORT_PRICE = "price"      # cheapest first (":floor")
SORT_LATENCY = "latency"  # fastest first (":nitro")


@dataclass(frozen=True)
class RoutePolicy:
    """Caller/workspace routing constraints applied at selection time.

    Mirrors OpenRouter's provider preferences (independent implementation):
    a HARD ``max_cost_micros`` cap, a SOFT ``max_latency_band`` preference
    (slower candidates are deprioritized, never excluded), an explicit
    ``provider_order``, and a ``sort`` strategy for consented fallbacks.
    """

    fallback: str = FALLBACK_NONE
    max_cost_micros: int | None = None
    allowed_regions: frozenset[str] | None = None
    allow_degraded: bool = False
    # Preferred provider keys, tried first among fallbacks (in this order).
    provider_order: tuple[str, ...] = ()
    # Fallback ordering strategy: 'price' | 'latency' | None (default: price->latency).
    sort: str | None = None
    # Soft latency ceiling ('fast'|'standard'|'slow'): slower is deprioritized.
    max_latency_band: str | None = None

    def wants_fallback(self) -> bool:
        return self.fallback == FALLBACK_EQUIVALENT


def is_admissible(candidate: Candidate, policy: RoutePolicy) -> bool:
    """Whether a candidate satisfies availability, region, and cost constraints."""
    if candidate.availability_state == "unavailable":
        return False
    if candidate.availability_state == "limited" and not policy.allow_degraded:
        return False
    if policy.allowed_regions is not None:
        # A candidate with no declared region cannot satisfy a region constraint.
        if candidate.region not in policy.allowed_regions:
            return False
    if policy.max_cost_micros is not None and candidate.est_cost_micros > int(
        policy.max_cost_micros
    ):
        return False
    return True


def _provider_rank(candidate: Candidate, policy: RoutePolicy) -> int:
    """Index of the candidate's provider in the preferred order (or last)."""
    if not policy.provider_order:
        return 0
    try:
        return policy.provider_order.index(candidate.provider_key)
    except ValueError:
        return len(policy.provider_order)


def _latency_penalty(candidate: Candidate, policy: RoutePolicy) -> int:
    """0 when within the soft latency ceiling, 1 when slower (deprioritized)."""
    if not policy.max_latency_band:
        return 0
    ceiling = _LATENCY_RANK.get(policy.max_latency_band, 3)
    return 0 if _LATENCY_RANK.get(candidate.latency_band, 3) <= ceiling else 1


# Health penalty (lower = preferred): unstable providers are deprioritized as
# fallbacks, never excluded — mirroring OpenRouter avoiding recently-unstable
# providers while keeping them available.
_HEALTH_PENALTY = {"healthy": 0, "unknown": 0, "degraded": 1, "down": 2}


def _health_penalty(candidate: Candidate) -> int:
    return _HEALTH_PENALTY.get(candidate.health_state, 0)


def order_key(candidate: Candidate, policy: RoutePolicy) -> tuple:
    """Composite fallback ordering: provider order -> health -> latency -> sort.

    Public canonical ordering used both by :func:`select_route` and by the
    model advisor's degraded cost/latency policy pass-through, so the AI-less
    fallback pick matches the deterministic route ordering exactly.
    """
    cost = int(candidate.est_cost_micros)
    lat = _LATENCY_RANK.get(candidate.latency_band, 3)
    if policy.sort == SORT_LATENCY:
        primary_sort: tuple = (lat, cost)
    elif policy.sort == SORT_PRICE:
        primary_sort = (cost, lat)
    else:
        primary_sort = (cost, lat)
    return (
        _provider_rank(candidate, policy),
        _health_penalty(candidate),
        _latency_penalty(candidate, policy),
        *primary_sort,
        candidate.model_id,
    )


# Backward-compatible private alias for existing internal callers.
_order_key = order_key


def resolve_variant(model_id: str) -> tuple[str, str | None]:
    """Split an OpenRouter-style variant suffix off a model id.

    ``pixelle/wan-i2v:floor`` -> ('pixelle/wan-i2v', 'price'); ``:nitro`` ->
    'latency'. Returns ``(model_id, None)`` when there is no known variant.
    """
    raw = str(model_id or "")
    if raw.endswith(":floor"):
        return raw[: -len(":floor")], SORT_PRICE
    if raw.endswith(":nitro"):
        return raw[: -len(":nitro")], SORT_LATENCY
    return raw, None


# Consented same-capability fallback ordering for short-form video / b-roll:
# Higgsfield primary -> Wan2.2 -> LTX-Video (fal.ai) -> CogVideoX, then the
# additional open-weights fal fallbacks SVD -> AnimateDiff -> Mochi-1. This is the
# preferred provider order for an equivalent-fallback video route; the hard cost
# cap still governs which of these are actually admissible (no silent overspend).
# HunyuanVideo is intentionally EXCLUDED: it is non-commercial with an EU/UK/KR
# territorial exclusion, so it is reference-only and never a default global route.
VIDEO_FALLBACK_ORDER: tuple[str, ...] = (
    "higgsfield", "wan", "ltx_fal", "cogvideox", "svd", "animatediff", "mochi",
)

_EQUIVALENT_ORDERS: dict[str, tuple[str, ...]] = {
    "video": VIDEO_FALLBACK_ORDER,
    "broll": VIDEO_FALLBACK_ORDER,
}


def equivalent_order(capability: str) -> tuple[str, ...]:
    """Preferred provider order for an equivalent-fallback route of ``capability``.

    Returns an empty tuple for capabilities with no curated fallback chain, so the
    generic cost/latency ordering governs (the caller never invents an order).
    """
    return _EQUIVALENT_ORDERS.get(str(capability or "").strip().lower(), ())


def video_fallback_policy(
    *, max_cost_micros: int | None = None, allow_degraded: bool = False
) -> RoutePolicy:
    """An equivalent-fallback video policy ordered by :data:`VIDEO_FALLBACK_ORDER`.

    Consented same-capability fallback (Higgsfield -> Wan -> LTX -> CogVideoX)
    within a hard cost cap, so a failed primary degrades to the next admissible
    open/managed video provider without a silent overspend or a capability switch.
    """
    return RoutePolicy(
        fallback=FALLBACK_EQUIVALENT,
        max_cost_micros=max_cost_micros,
        allow_degraded=allow_degraded,
        provider_order=VIDEO_FALLBACK_ORDER,
    )


def select_route(
    primary_model_id: str,
    candidates: list[Candidate],
    policy: RoutePolicy,
) -> list[Candidate]:
    """Return the ordered admissible route: ``[primary, *fallbacks]`` or ``[]``.

    * The primary is the caller-selected ``primary_model_id``; if it is unknown
      or inadmissible the route is empty (no silent substitution).
    * ``fallback == none``  -> only the primary (when admissible).
    * ``fallback == equivalent`` -> primary followed by other admissible,
      same-capability candidates ordered cheapest/fastest first. Fallbacks never
      include a different capability and always respect the cost cap.
    """
    by_id = {c.model_id: c for c in candidates}
    primary = by_id.get(primary_model_id)
    if primary is None or not is_admissible(primary, policy):
        return []

    if not policy.wants_fallback():
        return [primary]

    alternatives = [
        c
        for c in candidates
        if c.model_id != primary.model_id
        and c.capability == primary.capability
        and is_admissible(c, policy)
    ]
    # Order fallbacks by the composite preference key (provider order -> soft
    # latency ceiling -> price/latency sort). The primary stays first (partition
    # by model), matching OpenRouter's default endpoint grouping.
    alternatives.sort(key=lambda c: _order_key(c, policy))
    return [primary, *alternatives]
