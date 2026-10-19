"""Per-SKU credit cost for reel jobs (MG3).

One place answers "what does this reel cost, in which credits" before any
job exists, so the price can be shown before render and the same numbers are
debited at create:

* **Standard credits** pay for the script (Claude via Relay), free voices,
  captions, footage and the render. A reel up to 60 s is 1 credit; a longer
  reel is 1 credit per started minute (MD8).
* **Premium voice credits** pay for ElevenLabs narration and ElevenLabs music.
  They are priced at no less than 3x the provider cost: the credits needed are
  ``ceil(3 x provider USD / USD value of one premium voice credit)``, where one
  credit is worth the premium voice pack price divided by its credit count.
* **AI-video credits** (1 credit = 1 US cent) pay for presenter and AI-video
  provider calls at 3x the provider cost (``premium_credits.AI_VIDEO_MARKUP``).

A SKU whose provider has no recorded price is **unpriced**: it answers 402
``sku_unpriced`` and is never charged a flat standard credit.

Provider prices and their sources:

* ElevenLabs TTS: ``telemetry.cost.DEFAULT_TTS_USD_PER_1K_CHARS`` ($0.15 per
  1k characters, config ``[telemetry] tts_usd_per_1k_chars``).
* ElevenLabs music: $0.30 per generated minute, the higher of the two rates
  seen on https://elevenlabs.io/pricing/api (checked 2026-09-29; $0.15 today,
  $0.30 before the June 2026 cut). Override with ``MENIVOR_MUSIC_USD_PER_MIN``.
* Presenter providers: ``telemetry.cost.DEFAULT_AVATAR_USD_PER_MIN``. Only a
  provider listed there by name is priced; the ``default`` row never prices an
  unknown provider.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

KIND_STANDARD: str = "standard"
KIND_PREMIUM_VOICE: str = "premium_voice"
KIND_AI_VIDEO: str = "ai_video"

SKU_REEL: str = "reel"
SKU_LONG_FORM: str = "long_form"
SKU_PREMIUM_VOICE: str = "premium_voice"
SKU_PREMIUM_MUSIC: str = "premium_music"
SKU_PRESENTER: str = "presenter"
SKU_PRESENTER_REEL: str = "presenter_reel"

#: A reel up to this length is one standard credit (MD8).
SHORT_REEL_MAX_S: int = 60
#: Minimum markup over provider cost for every premium SKU.
MIN_MARKUP: int = 3
DEFAULT_MUSIC_USD_PER_MIN: float = 0.30
MUSIC_PRICE_SOURCE: str = "https://elevenlabs.io/pricing/api (2026-09-29)"
TTS_PRICE_SOURCE: str = "telemetry.cost.DEFAULT_TTS_USD_PER_1K_CHARS"
AVATAR_PRICE_SOURCE: str = "telemetry.cost.DEFAULT_AVATAR_USD_PER_MIN"
_DEFAULT_SCRIPT_CHARS_PER_SECOND: int = 30
_DEFAULT_DURATION_S: int = 30
_CAPTIONS_ONLY: str = "captions_only"
_PREMIUM_VOICE_PREFIX: str = "elevenlabs:"
_PREMIUM_VOICE_PACK: str = "premium_voice_25"


class PricingError(Exception):
    """A SKU that cannot be sold for this request (answer 402, charge nothing)."""

    code: str = "sku_unpriced"
    status_code: int = 402

    def __init__(self, sku: str, detail: str) -> None:
        super().__init__(detail)
        self.sku = sku
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "sku": self.sku, "detail": self.detail}


class SkuUnpriced(PricingError):
    """The SKU's provider has no recorded price."""

    code = "sku_unpriced"


class SkuLocked(PricingError):
    """The SKU exists but the caller's plan does not include it."""

    code = "sku_locked"


@dataclass(frozen=True)
class Line:
    """One priced part of a job: which credits, how many, and why."""

    sku: str
    kind: str
    credits: int
    provider_usd: float = 0.0
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "kind": self.kind,
            "credits": self.credits,
            "provider_usd": round(self.provider_usd, 6),
            "source": self.source,
        }


@dataclass(frozen=True)
class Quote:
    """The price of ONE job (one variant), split by credit kind."""

    lines: tuple[Line, ...] = field(default_factory=tuple)
    seconds: int = 0

    def credits_of(self, kind: str) -> int:
        return sum(line.credits for line in self.lines if line.kind == kind)

    @property
    def standard_credits(self) -> int:
        return self.credits_of(KIND_STANDARD)

    @property
    def premium_voice_credits(self) -> int:
        return self.credits_of(KIND_PREMIUM_VOICE)

    @property
    def ai_video_credits(self) -> int:
        return self.credits_of(KIND_AI_VIDEO)

    @property
    def provider_usd(self) -> float:
        return round(sum(line.provider_usd for line in self.lines), 6)

    def line(self, sku: str) -> Line | None:
        return next((line for line in self.lines if line.sku == sku), None)

    def as_dict(self, variants: int = 1) -> dict[str, Any]:
        count = max(1, int(variants))
        return {
            "seconds": self.seconds,
            "variants": count,
            "per_variant": {
                KIND_STANDARD: self.standard_credits,
                KIND_PREMIUM_VOICE: self.premium_voice_credits,
                KIND_AI_VIDEO: self.ai_video_credits,
            },
            "total": {
                KIND_STANDARD: self.standard_credits * count,
                KIND_PREMIUM_VOICE: self.premium_voice_credits * count,
                KIND_AI_VIDEO: self.ai_video_credits * count,
            },
            "lines": [line.as_dict() for line in self.lines],
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _text(params: Any, name: str) -> str:
    return str(getattr(params, name, "") or "").strip()


def job_seconds(params: Any) -> int:
    """The requested reel length in seconds (30 when unset)."""
    try:
        seconds = int(getattr(params, "target_duration_s", 0) or _DEFAULT_DURATION_S)
    except (TypeError, ValueError):
        seconds = _DEFAULT_DURATION_S
    return max(1, seconds)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


def standard_credits(seconds: int) -> int:
    """1 credit up to 60 s, then 1 credit per started minute (MD8)."""
    length = max(1, int(seconds or 0))
    if length <= SHORT_REEL_MAX_S:
        return 1
    return int(math.ceil(length / 60.0))


def standard_line(params: Any) -> Line:
    """Standard credits for one job: by length, presenter floor, job-cost knob (M3.1)."""
    from app.domains.reels import policy

    seconds = job_seconds(params)
    sku = SKU_REEL if seconds <= SHORT_REEL_MAX_S else SKU_LONG_FORM
    credits = standard_credits(seconds) * max(1, int(policy.job_cost()))
    if wants_presenter(params):
        sku = SKU_PRESENTER_REEL
        credits = max(credits, policy.presenter_credits())
    return Line(sku=sku, kind=KIND_STANDARD, credits=credits, source="MD8")


def premium_voice_credit_usd() -> float:
    """USD value of one premium voice credit: pack price / pack credits."""
    from app.services.billing import premium_credits as pc

    pack = pc.get_pack(_PREMIUM_VOICE_PACK)
    if pack is None or pack.credits <= 0 or pack.price_usd <= 0:
        raise SkuUnpriced(SKU_PREMIUM_VOICE, "the premium voice pack has no price")
    return float(pack.price_usd) / float(pack.credits)


def premium_voice_credits_for_usd(provider_usd: float) -> int:
    """Premium voice credits worth at least 3x ``provider_usd`` (0 for $0)."""
    cost = float(provider_usd or 0.0)
    if not math.isfinite(cost) or cost <= 0:
        return 0
    value = premium_voice_credit_usd()
    return max(1, int(math.ceil(round(cost * MIN_MARKUP / value, 6))))


def _narration_chars(params: Any) -> int:
    script = _text(params, "video_script")
    if script:
        return len(script)
    return job_seconds(params) * _DEFAULT_SCRIPT_CHARS_PER_SECOND


def premium_voice_line(params: Any) -> Line:
    """ElevenLabs narration: at least 3x the estimated TTS cost."""
    from app.telemetry import cost

    usd = float(cost.estimate_tts_cost(_narration_chars(params)))
    if usd <= 0:
        raise SkuUnpriced(SKU_PREMIUM_VOICE, "ElevenLabs narration has no recorded price")
    return Line(
        sku=SKU_PREMIUM_VOICE,
        kind=KIND_PREMIUM_VOICE,
        credits=premium_voice_credits_for_usd(usd),
        provider_usd=usd,
        source=TTS_PRICE_SOURCE,
    )


def music_usd_per_min() -> float:
    return _env_float("MENIVOR_MUSIC_USD_PER_MIN", DEFAULT_MUSIC_USD_PER_MIN)


def premium_music_line(params: Any) -> Line:
    """ElevenLabs music for the reel's length: at least 3x the per-minute price."""
    minutes = math.ceil(job_seconds(params) / 60.0)
    usd = round(minutes * music_usd_per_min(), 6)
    return Line(
        sku=SKU_PREMIUM_MUSIC,
        kind=KIND_PREMIUM_VOICE,
        credits=premium_voice_credits_for_usd(usd),
        provider_usd=usd,
        source=MUSIC_PRICE_SOURCE,
    )


def wants_presenter(params: Any) -> bool:
    """A non ``captions_only`` layout calls a presenter (avatar) provider."""
    return _text(params, "layout") not in ("", _CAPTIONS_ONLY)


def presenter_provider(params: Any) -> str:
    return (_text(params, "avatar_provider") or "heygen").lower()


def presenter_priced(provider: str) -> bool:
    """Whether ``provider`` has its own row in the avatar price table."""
    from app.telemetry.cost import DEFAULT_AVATAR_USD_PER_MIN

    key = str(provider or "").strip().lower()
    return key != "default" and float(DEFAULT_AVATAR_USD_PER_MIN.get(key, 0.0) or 0.0) > 0


def presenter_line(params: Any) -> Line:
    """AI-video credits for the presenter: 3x the estimated provider cost."""
    from app.services.billing import premium_credits as pc
    from app.services.cost_guard import estimate_job_cost

    provider = presenter_provider(params)
    if not presenter_priced(provider):
        raise SkuUnpriced(SKU_PRESENTER, f"presenter provider {provider!r} has no recorded price")
    usd = float(estimate_job_cost(params).avatar_usd)
    credits = pc.ai_video_credits_for_usd(usd)
    if credits <= 0:
        raise SkuUnpriced(SKU_PRESENTER, f"presenter provider {provider!r} priced at $0")
    return Line(
        sku=SKU_PRESENTER,
        kind=KIND_AI_VIDEO,
        credits=credits,
        provider_usd=usd,
        source=AVATAR_PRICE_SOURCE,
    )


def credit_cost(
    params: Any,
    *,
    premium_voice: bool | None = None,
    premium_music: bool | None = None,
    presenter: bool | None = None,
) -> Quote:
    """Price ONE job for ``params``.

    ``premium_voice`` / ``premium_music`` say whether the ElevenLabs voice or
    music will actually be used (``None`` = ask :mod:`app.domains.reels.premium`);
    ``presenter=False`` leaves the presenter line to the caller.
    Raises :class:`PricingError` (402) for an unpriced SKU.
    """
    from app.domains.reels import premium

    lines: list[Line] = [standard_line(params)]
    if premium_voice is None:
        premium_voice = premium.wants_premium_voice(params)
    if premium_music is None:
        premium_music = premium.uses_elevenlabs_music(params)
    if premium_voice:
        lines.append(premium_voice_line(params))
    if premium_music:
        lines.append(premium_music_line(params))
    if presenter is None:
        presenter = wants_presenter(params)
    if presenter:
        lines.append(presenter_line(params))
    return Quote(lines=tuple(lines), seconds=job_seconds(params))


SKU_PRESET_PREFIX: str = "preset"


def preset_credit_cost(
    preset_sku: str,
    tier: str,
    seconds: int,
    resolution: str | None = None,
    *,
    funding: str = KIND_AI_VIDEO,
    max_cost_micros: int | None = None,
) -> tuple[Quote, Any]:
    """Price one AI-video preset job via the MH1 tier resolver.

    Returns ``(quote, route)``: the quote holds one AI-video line at 3x the
    routed model's provider cost; ``route`` is the
    :class:`~app.domains.routing.tiers.TierRoute` the job must run on. Only
    AI-video credits fund a model route; ``funding="standard"`` raises 402
    before any model is looked at. An unpriced preset, tier or resolution, or
    no admissible model, raises :class:`SkuUnpriced` (402).
    """
    from app.domains.routing import tiers

    route = tiers.resolve(
        preset_sku,
        tier,
        seconds=seconds,
        resolution=resolution,
        funding=tiers.FUNDING_AI_VIDEO if funding == KIND_AI_VIDEO else str(funding),
        max_cost_micros=max_cost_micros,
    )
    credits = route.ai_video_credits
    if credits <= 0:
        raise SkuUnpriced(f"{SKU_PRESET_PREFIX}:{preset_sku}", "the routed model is priced at $0")
    line = Line(
        sku=f"{SKU_PRESET_PREFIX}:{route.preset_sku}:{route.tier}",
        kind=KIND_AI_VIDEO,
        credits=credits,
        provider_usd=route.provider_usd,
        source=route.model_id,
    )
    return Quote(lines=(line,), seconds=route.seconds), route


__all__ = [
    "KIND_AI_VIDEO",
    "KIND_PREMIUM_VOICE",
    "KIND_STANDARD",
    "MIN_MARKUP",
    "SHORT_REEL_MAX_S",
    "SKU_LONG_FORM",
    "SKU_PREMIUM_MUSIC",
    "SKU_PREMIUM_VOICE",
    "SKU_PRESENTER",
    "SKU_PRESENTER_REEL",
    "SKU_REEL",
    "Line",
    "PricingError",
    "Quote",
    "SkuLocked",
    "SkuUnpriced",
    "credit_cost",
    "preset_credit_cost",
    "SKU_PRESET_PREFIX",
    "job_seconds",
    "music_usd_per_min",
    "premium_music_line",
    "premium_voice_credit_usd",
    "premium_voice_credits_for_usd",
    "premium_voice_line",
    "presenter_line",
    "presenter_priced",
    "standard_credits",
    "standard_line",
    "wants_presenter",
]
