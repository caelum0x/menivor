"""Premium admission for reel jobs: standard credits never pay premium providers.

Called inside the job-create / retry / rerun transaction, after the standard
debit checks and before any job is enqueued:

* **Premium voice.** A reel asking for an ``elevenlabs:`` voice (with
  ElevenLabs configured) is narrated with it only when the user holds its
  priced premium voice credits (at least 3x the TTS cost, see
  :mod:`app.domains.reels.pricing`) per variant; they are debited per job. Otherwise
  the voice is switched to the free voice for the job's language before the
  job is stored, so the stored params say what will actually be used.
* **AI presenter.** A non ``captions_only`` layout calls an avatar provider.
  It needs AI-video credits: 3x the estimated provider cost, reserved per job.
  Too few answers 402 before any job exists. Success settles to 3x the measured
  cost (:func:`settle_job`), failure or cancel returns everything
  (:func:`refund_job`).

Wallet-funded jobs (signed generation quote) are a separate USD SKU and skip
this module entirely.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.services.billing import premium_credits as pc

MARKER_KEY: str = "_premium"
_CAPTIONS_ONLY: str = "captions_only"
PREMIUM_VOICE_PREFIX: str = "elevenlabs:"
ELEVENLABS_MUSIC: str = "elevenlabs"
SONILO_MUSIC: str = "sonilo"


class PremiumCreditsRequired(Exception):
    """A presenter job without enough AI-video credits (answer 402)."""

    def __init__(self, needed: int, available: int) -> None:
        super().__init__(
            f"AI presenter reels use AI-video credits: this needs {needed}, you have {available}."
        )
        self.needed = int(needed)
        self.available = int(available)


@dataclass(frozen=True)
class PremiumPlan:
    """What one job of this request spends from the premium ledgers."""

    params: Any
    voice_credits: int = 0
    ai_video_credits: int = 0
    voice_downgraded: bool = False
    music_credits: int = 0
    music_downgraded: bool = False

    @property
    def premium_credits(self) -> int:
        """Premium voice credits one job spends (ElevenLabs voice and/or music)."""
        return self.voice_credits + self.music_credits

    @property
    def marker(self) -> dict[str, Any]:
        return {
            MARKER_KEY: {
                "voice_credits": self.voice_credits,
                "music_credits": self.music_credits,
                "ai_video_credits": self.ai_video_credits,
                "voice_downgraded": self.voice_downgraded,
                "music_downgraded": self.music_downgraded,
            }
        }


def _text(params: Any, name: str) -> str:
    return str(getattr(params, name, "") or "").strip()


def wants_premium_voice(params: Any) -> bool:
    """Whether the TTS stage would call ElevenLabs for these params."""
    from app.core.launch.formats import elevenlabs_configured, needs_tts

    return (
        needs_tts(params)
        and _text(params, "voice_name").startswith(PREMIUM_VOICE_PREFIX)
        and elevenlabs_configured()
    )


def uses_elevenlabs_music(params: Any) -> bool:
    """Whether the compose stage would generate AI music with ElevenLabs."""
    if not _text(params, "music_prompt"):
        return False
    try:
        from app.services.bgm_ai import resolve_provider

        provider = resolve_provider(_text(params, "bgm_provider"))
    except Exception:  # noqa: BLE001 - unresolvable provider => no music call
        return False
    return provider is not None and provider.name == ELEVENLABS_MUSIC


def _without_elevenlabs_music(params: Any) -> Any:
    """Use the other music provider when it is on, else compose without AI music."""
    try:
        from app.services.bgm_ai import resolve_provider

        if resolve_provider(SONILO_MUSIC) is not None:
            return dataclasses.replace(params, bgm_provider=SONILO_MUSIC)
    except Exception:  # noqa: BLE001 - fall through to no AI music
        pass
    return dataclasses.replace(params, music_prompt="")


def ai_video_credits_needed(params: Any) -> int:
    """3x the estimated avatar-provider cost, in AI-video credits (0 if none).

    Priced by :func:`app.domains.reels.pricing.presenter_line`; an unpriced
    presenter provider raises :class:`~app.domains.reels.pricing.SkuUnpriced`.
    """
    from app.domains.reels import pricing

    if not pricing.wants_presenter(params):
        return 0
    return pricing.presenter_line(params).credits


def _free_voice(params: Any) -> Any:
    from app.core.launch.formats import free_voice_for

    return dataclasses.replace(params, voice_name=free_voice_for(_text(params, "language")))


def plan_job(session: Any, user_id: str, params: Any, variants: int) -> PremiumPlan:
    """Decide the premium spend for ``variants`` jobs; raise when unaffordable.

    Prices come from :func:`app.domains.reels.pricing.credit_cost` (MG3), so
    every premium SKU costs at least 3x its provider price. AI-video
    (presenter) is required: too few credits raise. ElevenLabs voice and
    ElevenLabs music each cost their priced premium voice credits per job;
    whatever the balance cannot cover is switched to its free alternative. An
    unpriced SKU raises :class:`~app.domains.reels.pricing.PricingError` (402).
    """
    from app.domains.reels import pricing

    count = max(1, int(variants))
    want_voice = wants_premium_voice(params)
    want_music = uses_elevenlabs_music(params)
    quote = pricing.credit_cost(
        params, premium_voice=want_voice, premium_music=want_music, presenter=False
    )
    ai_credits = ai_video_credits_needed(params)
    if ai_credits > 0:
        held = pc.balance(session, user_id, pc.KIND_AI_VIDEO)
        if held < ai_credits * count:
            raise PremiumCreditsRequired(ai_credits * count, held)
    if not (want_voice or want_music):
        return PremiumPlan(params=params, ai_video_credits=ai_credits)
    voice_line = quote.line(pricing.SKU_PREMIUM_VOICE)
    music_line = quote.line(pricing.SKU_PREMIUM_MUSIC)
    voice_price = voice_line.credits if voice_line else 0
    music_price = music_line.credits if music_line else 0
    available = pc.balance(session, user_id, pc.KIND_PREMIUM_VOICE)
    voice = voice_price if want_voice and available >= voice_price * count else 0
    music = music_price if want_music and available - voice * count >= music_price * count else 0
    planned = params
    if want_voice and not voice:
        logger.info(f"premium voice not funded for user={user_id}: narrating with a free voice")
        planned = _free_voice(planned)
    if want_music and not music:
        logger.info(f"ElevenLabs music not funded for user={user_id}: using a free alternative")
        planned = _without_elevenlabs_music(planned)
    return PremiumPlan(
        params=planned,
        voice_credits=voice,
        music_credits=music,
        ai_video_credits=ai_credits,
        voice_downgraded=bool(want_voice and not voice),
        music_downgraded=bool(want_music and not music),
    )


def plan_preset_job(
    session: Any,
    user_id: str,
    preset_sku: str,
    tier: str,
    seconds: int,
    resolution: str | None = None,
    *,
    variants: int = 1,
    funding: str = pc.KIND_AI_VIDEO,
    max_cost_micros: int | None = None,
) -> tuple[PremiumPlan, Any]:
    """Premium admission for an AI-video preset job (MH1 call site).

    Quotes through :func:`app.domains.reels.pricing.preset_credit_cost` before
    render, so the user sees the price first. Standard credits never fund a
    model route (402 ``ai_video_credits_required``); too few AI-video credits
    raise :class:`PremiumCreditsRequired`. Returns the plan (debit it with
    :func:`debit_job`) and the tier route the job must run on.
    """
    from app.domains.reels import pricing

    quote, route = pricing.preset_credit_cost(
        preset_sku, tier, seconds, resolution, funding=funding, max_cost_micros=max_cost_micros
    )
    count = max(1, int(variants))
    needed = quote.ai_video_credits * count
    held = pc.balance(session, user_id, pc.KIND_AI_VIDEO)
    if held < needed:
        raise PremiumCreditsRequired(needed, held)
    return PremiumPlan(params=None, ai_video_credits=quote.ai_video_credits), route


def debit_job(session: Any, user_id: str, job_id: str, plan: PremiumPlan) -> None:
    """Debit one job's premium credits (inside the create transaction)."""
    reason = f"{pc.DEBIT_REASON}:{job_id}"
    try:
        if plan.premium_credits > 0:
            pc.debit(session, user_id, pc.KIND_PREMIUM_VOICE, plan.premium_credits, reason, job_id)
        if plan.ai_video_credits > 0:
            pc.debit(session, user_id, pc.KIND_AI_VIDEO, plan.ai_video_credits, reason, job_id)
    except pc.InsufficientPremiumCredits as exc:
        # A concurrent spend drained the balance after planning: 402, rollback.
        raise PremiumCreditsRequired(exc.needed, exc.available) from exc


# --------------------------------------------------------------------------- #
# Pipeline guards (defense in depth for every job-creation path)
# --------------------------------------------------------------------------- #
#: Set only by server-side operator tools (never from request data) in the
#: stage ``ctx``: the operator pays the provider directly (sample renders).
OPERATOR_FUNDED_CTX_KEY: str = "_operator_funded_premium"


def _stored_params(job_id: str) -> dict[str, Any] | None:
    try:
        from app.models.db.base import get_session
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            return dict(job.params or {}) if job is not None else None
    except Exception as exc:  # noqa: BLE001 - unknown funding is unfunded
        logger.warning(f"premium guard: job {job_id} params unreadable: {type(exc).__name__}")
        return None


def _funded(job_id: str, ctx: dict | None, field: str) -> bool:
    if isinstance(ctx, dict) and ctx.get(OPERATOR_FUNDED_CTX_KEY) is True:
        return True
    stored = _stored_params(job_id)
    if stored is None:
        return False
    from app.domains.reels.wallet_bridge import read_marker

    if read_marker(stored):
        return True  # wallet-funded: the USD quote pays the provider
    marker = stored.get(MARKER_KEY) or {}
    try:
        return int(marker.get(field) or 0) > 0
    except (TypeError, ValueError, AttributeError):
        return False


def premium_voice_funded(job_id: str, ctx: dict | None = None) -> bool:
    """Whether the TTS stage may call ElevenLabs for this job."""
    return _funded(job_id, ctx, "voice_credits")


def premium_music_funded(job_id: str, ctx: dict | None = None) -> bool:
    """Whether the compose stage may generate music with ElevenLabs for this job."""
    return _funded(job_id, ctx, "music_credits")


def ai_video_funded(job_id: str, ctx: dict | None = None) -> bool:
    """Whether the avatar stage may call a paid presenter provider for this job."""
    return _funded(job_id, ctx, "ai_video_credits")


def refund_job(job_id: str) -> dict[str, int]:
    """Return a failed or cancelled job's premium credits (idempotent)."""
    return pc.refund_job_once(job_id)


def measured_avatar_usd(job_id: str) -> float:
    """Sum of the job's measured avatar-stage cost events (USD)."""
    from sqlalchemy import func, select

    from app.models.db.base import get_session
    from app.models.db.models import JobEvent

    with get_session() as session:
        total = session.execute(
            select(func.coalesce(func.sum(JobEvent.cost_usd), 0.0)).where(
                JobEvent.job_id == job_id,
                JobEvent.status == "cost",
                JobEvent.stage == "avatar",
            )
        ).scalar_one()
    return float(total or 0.0)


def settle_job(job_id: str) -> int:
    """On success keep 3x the measured AI-video cost; return the surplus credits."""
    try:
        return pc.settle_ai_video_once(job_id, measured_avatar_usd(job_id))
    except Exception as exc:  # noqa: BLE001 - settlement must never break the pipeline
        logger.error(f"premium settle failed for job {job_id}: {exc}")
        return 0


__all__ = [
    "MARKER_KEY",
    "OPERATOR_FUNDED_CTX_KEY",
    "ai_video_funded",
    "premium_music_funded",
    "premium_voice_funded",
    "uses_elevenlabs_music",
    "PremiumCreditsRequired",
    "PremiumPlan",
    "ai_video_credits_needed",
    "debit_job",
    "plan_job",
    "plan_preset_job",
    "refund_job",
    "settle_job",
    "wants_premium_voice",
]
