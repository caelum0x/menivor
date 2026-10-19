"""Tier resolver and preset quotes (MH1).

A preset asks for ``(capability, tier)`` and gets a priced, admissible model
route. It never names a model:

* **draft** runs the cheapest admissible model, so a preview is cheap;
* **final** runs when the user keeps the result. By default (owner decision
  OD2, flag ``MENIVOR_FINAL_TIER_PICK=cheapest_strong``) it is the cheapest
  final-grade model under the cost cap; ``best`` picks the highest-ranked
  final-grade model under the cap instead.

A model is admissible only when every rail passes:

1. its licence is sellable (``license_class.is_model_sellable``, fail closed);
2. it is a priced per-second video row in ``gateway.media_catalog``;
3. the requested length fits its ``max_seconds``;
4. the requested resolution is not above the resolution its price is for;
5. its provider has a platform credential;
6. its estimated cost is under ``max_cost_micros`` (``routing.policy``).

Rows whose price was verified at the source are preferred; legacy rows are
used only when no verified row is admissible.

**Funding.** Only AI-video credits (3x provider cost, 1 credit = 1 cent) can
fund a model route. A request funded by standard credits is refused before
any model is looked at (:class:`StandardCreditsCannotFund`, 402).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterable

from app.domains.reels.pricing import PricingError, SkuUnpriced

CAP_TEXT_TO_VIDEO: str = "text_to_video"
CAP_IMAGE_TO_VIDEO: str = "image_to_video"
CAPABILITIES: tuple[str, ...] = (CAP_TEXT_TO_VIDEO, CAP_IMAGE_TO_VIDEO)

TIER_DRAFT: str = "draft"
TIER_FINAL: str = "final"
TIERS: tuple[str, ...] = (TIER_DRAFT, TIER_FINAL)

GRADE_DRAFT: str = "draft"
GRADE_FINAL: str = "final"

FUNDING_STANDARD: str = "standard"
FUNDING_AI_VIDEO: str = "ai_video"

PICK_CHEAPEST_STRONG: str = "cheapest_strong"
PICK_BEST: str = "best"
FINAL_PICK_ENV: str = "MENIVOR_FINAL_TIER_PICK"

#: Resolutions a tier may ask for, and the default when none is given.
TIER_RESOLUTIONS: dict[str, tuple[str, ...]] = {
    TIER_DRAFT: ("480p", "720p"),
    TIER_FINAL: ("720p", "1080p"),
}
TIER_DEFAULT_RESOLUTION: dict[str, str] = {TIER_DRAFT: "480p", TIER_FINAL: "720p"}
_RESOLUTION_RANK: dict[str, int] = {"480p": 480, "580p": 580, "720p": 720, "768p": 768, "1080p": 1080}

#: Platform credential per catalog provider key.
_PROVIDER_ENV: dict[str, tuple[str, ...]] = {
    "kling-fal": ("FAL_KEY",),
    "veo": ("GEMINI_API_KEY",),
    "runway": ("RUNWAY_API_SECRET",),
    "wan": ("REPLICATE_API_TOKEN",),
    "minimax": ("MINIMAX_API_KEY",),
    "luma": ("LUMAAI_API_KEY",),
}


class StandardCreditsCannotFund(PricingError):
    """A model route asked for with standard credits (answer 402)."""

    code = "ai_video_credits_required"


@dataclass(frozen=True)
class TierCandidate:
    """One catalog row a tier may use; ``rank`` is quality (higher is better)."""

    model_id: str
    capability: str
    grade: str
    rank: int


#: The MH1 table. Ids missing from the catalog are skipped, so a row added by
#: MH0 (Kling 2.5 Turbo, LTX-2, Seedance 2.0, ...) becomes routable as soon as
#: the catalog carries it and its licence row is sellable.
TIER_TABLE: tuple[TierCandidate, ...] = (
    # --- text to video: draft grade ---
    TierCandidate("lightricks/ltx-2", CAP_TEXT_TO_VIDEO, GRADE_DRAFT, 30),
    TierCandidate("alibaba/wan-2.5", CAP_TEXT_TO_VIDEO, GRADE_DRAFT, 28),
    TierCandidate("alibaba/wan-2.2-fal", CAP_TEXT_TO_VIDEO, GRADE_DRAFT, 24),
    TierCandidate("wan/wan-2.2", CAP_TEXT_TO_VIDEO, GRADE_DRAFT, 22),
    TierCandidate("lightricks/ltx-video", CAP_TEXT_TO_VIDEO, GRADE_DRAFT, 20),
    TierCandidate("minimax/hailuo-02-fal", CAP_TEXT_TO_VIDEO, GRADE_DRAFT, 26),
    # --- text to video: final grade ---
    TierCandidate("kwaivgi/kling-v2.5-turbo-pro", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 80),
    TierCandidate("minimax/hailuo-02-pro-fal", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 74),
    TierCandidate("google/veo-3.1-fast-fal", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 82),
    TierCandidate("kwaivgi/kling-v3-pro", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 88),
    TierCandidate("bytedance/seedance-2.0-fast", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 86),
    TierCandidate("bytedance/seedance-2.0", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 92),
    TierCandidate("google/veo-3.1-lite", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 72),
    TierCandidate("kwaivgi/kling-v2.1-master", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 76),
    TierCandidate("minimax/hailuo-02", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 70),
    TierCandidate("google/veo-3.1", CAP_TEXT_TO_VIDEO, GRADE_FINAL, 90),
    # --- image to video ---
    TierCandidate("wan/wan-2.2-i2v", CAP_IMAGE_TO_VIDEO, GRADE_DRAFT, 22),
    TierCandidate("kwaivgi/kling-v1.6-i2v", CAP_IMAGE_TO_VIDEO, GRADE_FINAL, 60),
    TierCandidate("runwayml/gen-4", CAP_IMAGE_TO_VIDEO, GRADE_FINAL, 70),
    TierCandidate("kwaivgi/kling-v2-master-i2v", CAP_IMAGE_TO_VIDEO, GRADE_FINAL, 78),
)


@dataclass(frozen=True)
class PresetSku:
    """A preset the product sells: which capability it needs."""

    key: str
    capability: str
    label: str


PRESET_SKUS: dict[str, PresetSku] = {
    sku.key: sku
    for sku in (
        PresetSku("text_to_video", CAP_TEXT_TO_VIDEO, "Video from a prompt"),
        PresetSku("broll_clip", CAP_TEXT_TO_VIDEO, "AI B-roll clip"),
        PresetSku("animate_image", CAP_IMAGE_TO_VIDEO, "Animate an image"),
    )
}


@dataclass(frozen=True)
class TierRoute:
    """A priced, admissible route for one preset job."""

    preset_sku: str
    capability: str
    tier: str
    model_id: str
    provider: str
    seconds: int
    resolution: str
    cost_micros: int
    verified_price: bool

    @property
    def provider_usd(self) -> float:
        return self.cost_micros / 1_000_000

    @property
    def ai_video_credits(self) -> int:
        from app.services.billing.premium_credits import ai_video_credits_for_usd

        return ai_video_credits_for_usd(self.provider_usd)

    def as_dict(self) -> dict:
        return {
            "preset_sku": self.preset_sku,
            "capability": self.capability,
            "tier": self.tier,
            "model_id": self.model_id,
            "seconds": self.seconds,
            "resolution": self.resolution,
            "provider_usd": round(self.provider_usd, 6),
            "ai_video_credits": self.ai_video_credits,
            "verified_price": self.verified_price,
        }


# --------------------------------------------------------------------------- #
# Rails
# --------------------------------------------------------------------------- #
def provider_configured(provider: str) -> bool:
    """Whether the platform holds a credential for ``provider``."""
    names = _PROVIDER_ENV.get(str(provider or "").strip())
    return bool(names) and any(os.environ.get(name, "").strip() for name in names)


def final_pick() -> str:
    raw = os.environ.get(FINAL_PICK_ENV, "").strip().lower()
    return PICK_BEST if raw == PICK_BEST else PICK_CHEAPEST_STRONG


def _resolution_fits(requested: str, row_resolution: str) -> bool:
    if not row_resolution:
        return True  # legacy row priced at its default output
    have = _RESOLUTION_RANK.get(row_resolution)
    want = _RESOLUTION_RANK.get(requested)
    return have is not None and want is not None and want <= have


def _check_resolution(tier: str, resolution: str | None) -> str:
    chosen = (resolution or TIER_DEFAULT_RESOLUTION[tier]).strip().lower()
    if chosen not in TIER_RESOLUTIONS[tier]:
        raise SkuUnpriced(f"{tier}:{chosen}", f"{chosen} is not priced for the {tier} tier")
    return chosen


def _routes(
    preset: PresetSku,
    tier: str,
    seconds: int,
    resolution: str,
    available: Callable[[str], bool],
) -> list[tuple[TierCandidate, TierRoute]]:
    from app.domains.gateway import media_catalog
    from app.domains.routing.license_class import is_model_sellable

    grades = (GRADE_DRAFT, GRADE_FINAL) if tier == TIER_DRAFT else (GRADE_FINAL,)
    found: list[tuple[TierCandidate, TierRoute]] = []
    for cand in TIER_TABLE:
        if cand.capability != preset.capability or cand.grade not in grades:
            continue
        row = media_catalog.get_model(cand.model_id)
        if row is None or row.modality != media_catalog.VIDEO or row.unit != "second":
            continue
        if row.price_micros <= 0 or (row.max_seconds and seconds > row.max_seconds):
            continue
        if not _resolution_fits(resolution, str(getattr(row, "resolution", "") or "")):
            continue
        if not is_model_sellable(row.id) or not available(row.provider):
            continue
        found.append(
            (
                cand,
                TierRoute(
                    preset_sku=preset.key,
                    capability=preset.capability,
                    tier=tier,
                    model_id=row.id,
                    provider=row.provider,
                    seconds=seconds,
                    resolution=resolution,
                    cost_micros=int(row.price_micros) * seconds,
                    verified_price=bool(getattr(row, "price_verified", False))
                    and not bool(getattr(row, "legacy", False)),
                ),
            )
        )
    return found


def _under_cap(
    routes: Iterable[tuple[TierCandidate, TierRoute]], max_cost_micros: int | None
) -> list[tuple[TierCandidate, TierRoute]]:
    from app.domains.routing.policy import Candidate, RoutePolicy, is_admissible

    policy = RoutePolicy(max_cost_micros=max_cost_micros)
    return [
        (cand, route)
        for cand, route in routes
        if is_admissible(
            Candidate(
                model_id=route.model_id,
                provider_key=route.provider,
                capability=route.capability,
                est_cost_micros=route.cost_micros,
            ),
            policy,
        )
    ]


def resolve(
    preset_sku: str,
    tier: str,
    *,
    seconds: int,
    resolution: str | None = None,
    funding: str = FUNDING_AI_VIDEO,
    max_cost_micros: int | None = None,
    available: Callable[[str], bool] | None = None,
    pick: str | None = None,
) -> TierRoute:
    """The route for one preset job, or raise a 402 :class:`PricingError`."""
    if funding != FUNDING_AI_VIDEO:
        raise StandardCreditsCannotFund(
            str(preset_sku), "AI video presets use AI-video credits; standard credits never pay a model"
        )
    preset = PRESET_SKUS.get(str(preset_sku or "").strip())
    if preset is None:
        raise SkuUnpriced(str(preset_sku), f"preset {preset_sku!r} has no price")
    if tier not in TIERS:
        raise SkuUnpriced(f"{preset.key}:{tier}", f"tier {tier!r} has no price")
    length = int(seconds or 0)
    if length <= 0:
        raise SkuUnpriced(preset.key, "a preset job needs a length in seconds")
    chosen_res = _check_resolution(tier, resolution)
    routes = _under_cap(
        _routes(preset, tier, length, chosen_res, available or provider_configured),
        max_cost_micros,
    )
    verified = [item for item in routes if item[1].verified_price]
    pool = verified or routes
    if not pool:
        raise SkuUnpriced(
            f"{preset.key}:{tier}",
            f"no licensed, priced model can make {length} s of {chosen_res} {preset.label.lower()} under the cap",
        )
    if tier == TIER_FINAL and (pick or final_pick()) == PICK_BEST:
        _cand, route = max(pool, key=lambda item: (item[0].rank, -item[1].cost_micros))
    else:
        _cand, route = min(pool, key=lambda item: (item[1].cost_micros, -item[0].rank))
    return route


__all__ = [
    "CAPABILITIES",
    "CAP_IMAGE_TO_VIDEO",
    "CAP_TEXT_TO_VIDEO",
    "FINAL_PICK_ENV",
    "FUNDING_AI_VIDEO",
    "FUNDING_STANDARD",
    "PICK_BEST",
    "PICK_CHEAPEST_STRONG",
    "PRESET_SKUS",
    "TIERS",
    "TIER_DRAFT",
    "TIER_FINAL",
    "TIER_TABLE",
    "PresetSku",
    "StandardCreditsCannotFund",
    "TierCandidate",
    "TierRoute",
    "final_pick",
    "provider_configured",
    "resolve",
]
