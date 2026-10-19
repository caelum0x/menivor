"""Winning Hook Ranker — Jev-scored, code-combined ranking of reel hook variants.

The growth surface's "which hook wins?" primitive. A creator (or the caption
generator) produces N candidate hooks/captions for one reel or campaign; this
service scores each candidate ONCE with Jev across independent dimensions, then
combines those raw signals in CODE with a fixed, tunable composite:

    composite = hook_strength - 1.5 * is_slop - 2 * is_policy_risk

Changing a weight re-ranks instantly without re-running Jev, and the raw signals
double as labelling features once real watch-through/retention outcomes exist.

Design (mirrors ``typesafe/modules/meta-ads.ts``):
  * Candidate lists are built in CODE. The model only PICKS the primary angle from
    a fixed option set and never invents options.
  * ONE batched ``system_one`` call per variant — four independent questions
    (choice + score + two nouls) run in parallel server-side.
  * Variants are scored concurrently (``asyncio.gather``), each its own batch.

Graceful degradation: when no ``TYPESAFE_API_KEY`` is configured the ranker returns
a pass-through result (input order preserved, ``degraded=True``, null signals) with
a logged warning — it never fabricates scores or a key.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping

from loguru import logger

from app.domains.growth.typesafe_client import (
    TypeSafeClient,
    TypeSafeError,
    choice,
    noul,
    score,
    typesafe_from_env,
)

# --- Candidate angle set (built in code; the model only PICKS one) -----------
PRIMARY_ANGLES: dict[str, str] = {
    "cost_saving": "Leads with saving money, time, or effort — a cheaper/faster way.",
    "identity": "Speaks to who the viewer is or wants to be (status, belonging, values).",
    "convenience": "Leads with ease — removes friction, does the hard part for them.",
    "novelty": "Leads with something new, unseen, or surprising to make/try.",
    "curiosity": "Opens a loop or withholds — makes them need to know the rest.",
}

# --- Ordered hook-strength levels (low -> high) ------------------------------
HOOK_STRENGTH_LEVELS: list[str] = [
    "Weak: generic opener, gives no reason to stop scrolling.",
    "Okay: a mild angle or benefit, easy to scroll past.",
    "Strong: a specific, curiosity- or pain-driven hook that earns a pause.",
    "Exceptional: a scroll-stopping hook that names the exact desire in the first beat.",
]

# --- Composite weights (tunable in code; no re-inference needed to re-rank) ---
SLOP_PENALTY: float = 1.5
POLICY_PENALTY: float = 2.0

# Question ids for the single batched call.
_Q_ANGLE = "primary_angle"
_Q_HOOK = "hook_strength"
_Q_SLOP = "is_slop"
_Q_POLICY = "is_policy_risk"


@dataclass(frozen=True)
class HookVariant:
    """One candidate hook/caption for a reel or campaign."""

    id: str
    text: str


@dataclass(frozen=True)
class HookContext:
    """Shared context all variants are judged against."""

    topic: str = ""
    platform: str = ""
    audience: str = ""
    brand_voice: str = ""


@dataclass(frozen=True)
class HookSignals:
    """Raw per-variant Jev signals plus the code-computed composite."""

    id: str
    text: str
    primary_angle: str
    angle_confidence: float
    hook_strength: float
    is_slop: float
    is_policy_risk: float
    composite: float
    scored: bool = True  # False when this variant fell back to pass-through
    angle_probabilities: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class HookRanking:
    """The ranked result the route returns."""

    ranked: list[HookSignals]
    winner: HookSignals | None
    recommended_angle: str
    degraded: bool
    note: str = ""


def _compute_composite(hook_strength: float, is_slop: float, is_policy_risk: float) -> float:
    """The one place the composite is defined: hook - 1.5*slop - 2*policy."""
    return hook_strength - SLOP_PENALTY * is_slop - POLICY_PENALTY * is_policy_risk


def _questions() -> dict[str, dict[str, Any]]:
    """Build the four independent questions for one variant (batched, parallel)."""
    return {
        _Q_ANGLE: choice(
            "Which single angle does this hook lead with for the target audience?",
            PRIMARY_ANGLES,
        ),
        _Q_HOOK: score(
            "How strong is this as the opening hook of a short-form reel for the "
            "target audience — will it stop the scroll in the first beat?",
            HOOK_STRENGTH_LEVELS,
        ),
        _Q_SLOP: noul(
            "Is this hook generic AI 'slop' — vague, templated, engagement-bait "
            "phrasing with no specific substance?",
            {
                "true": "Reads as templated AI filler; no specific, felt substance.",
                "false": "Specific and human; earns attention on its merits.",
            },
        ),
        _Q_POLICY: noul(
            "Might this hook create a platform-policy or brand-safety risk "
            "(unverifiable claims, medical/financial promises, prohibited or "
            "offensive content)?",
            {
                "true": "Plausible policy/brand-safety risk; needs human review.",
                "false": "No obvious policy or brand-safety issue.",
            },
        ),
    }


def _state(variant: HookVariant, context: HookContext) -> dict[str, Any]:
    return {
        "hook": variant.text,
        "reel": {
            "topic": context.topic or None,
            "platform": context.platform or None,
            "audience": context.audience or None,
            "brandVoice": context.brand_voice or None,
        },
        "note": (
            "Judge this as the opening hook / caption of a short-form vertical "
            "video (reel) aimed at the stated audience on the stated platform."
        ),
    }


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _score_variant(
    client: TypeSafeClient, variant: HookVariant, context: HookContext
) -> HookSignals:
    """Score one variant with a single batched Jev call."""
    resp = await client.system_one(_state(variant, context), _questions())
    answers = resp.get("answers", {}) if isinstance(resp, dict) else {}

    angle_ans = answers.get(_Q_ANGLE) or {}
    hook_ans = answers.get(_Q_HOOK) or {}
    slop_ans = answers.get(_Q_SLOP) or {}
    policy_ans = answers.get(_Q_POLICY) or {}

    hook_strength = _as_float(hook_ans.get("score"))
    is_slop = _as_float(slop_ans.get("noul"))
    is_policy = _as_float(policy_ans.get("noul"))
    primary_angle = str(angle_ans.get("choice") or "")
    probabilities = angle_ans.get("probabilities")
    angle_probabilities = probabilities if isinstance(probabilities, dict) else {}

    return HookSignals(
        id=variant.id,
        text=variant.text,
        primary_angle=primary_angle,
        angle_confidence=_as_float(angle_ans.get("confidence")),
        hook_strength=hook_strength,
        is_slop=is_slop,
        is_policy_risk=is_policy,
        composite=_compute_composite(hook_strength, is_slop, is_policy),
        scored=True,
        angle_probabilities={str(k): _as_float(v) for k, v in angle_probabilities.items()},
    )


def _passthrough(variant: HookVariant) -> HookSignals:
    """Non-fabricated fallback: null signals, ordering preserved, clearly unscored."""
    return HookSignals(
        id=variant.id,
        text=variant.text,
        primary_angle="",
        angle_confidence=0.0,
        hook_strength=0.0,
        is_slop=0.0,
        is_policy_risk=0.0,
        composite=0.0,
        scored=False,
        angle_probabilities={},
    )


async def rank_hooks(
    variants: list[HookVariant],
    context: HookContext,
    *,
    client: TypeSafeClient | None = None,
) -> HookRanking:
    """Rank hook variants by Jev-scored composite (highest first).

    ``client`` is injectable for tests; by default it is built from the
    environment. When no API key is configured the ranker degrades to a
    pass-through ranking (input order preserved) with ``degraded=True``.
    """
    if not variants:
        return HookRanking(ranked=[], winner=None, recommended_angle="", degraded=False)

    resolved = client or typesafe_from_env()
    if resolved is None:
        ranked = [_passthrough(v) for v in variants]
        return HookRanking(
            ranked=ranked,
            winner=ranked[0],
            recommended_angle="",
            degraded=True,
            note="TYPESAFE_API_KEY unset — variants returned in input order without AI scoring.",
        )

    try:
        scored = await asyncio.gather(
            *(_score_variant(resolved, v, context) for v in variants)
        )
    except TypeSafeError as exc:
        logger.error(f"rank_hooks: Jev scoring failed ({exc}); degrading to pass-through")
        ranked = [_passthrough(v) for v in variants]
        return HookRanking(
            ranked=ranked,
            winner=ranked[0],
            recommended_angle="",
            degraded=True,
            note=f"Jev scoring unavailable: {exc}",
        )

    # Stable sort by composite, highest first; ties keep input order.
    ranked = sorted(scored, key=lambda s: s.composite, reverse=True)
    winner = ranked[0]
    return HookRanking(
        ranked=ranked,
        winner=winner,
        recommended_angle=winner.primary_angle,
        degraded=False,
    )
