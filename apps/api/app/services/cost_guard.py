"""Admission-time per-job cost guardrail built on the shared telemetry prices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.config import config
from app.models.db.models import Job, JobEvent
from app.telemetry import cost

_DEFAULT_MAX_JOB_COST_USD = 1.00
_DEFAULT_SCRIPT_CHARS_PER_SECOND = 30
# Self-hosted FFmpeg compute for a faceless composite (TTS narration + captions
# over curated stock footage). Config key ``reelforge_render_usd_per_min``.
_DEFAULT_RENDER_USD_PER_MIN = 0.01
# LLM token budget for one generated narration script (prompt, completion).
_SCRIPT_LLM_TOKENS = (500, 300)
# Voice-name prefixes routed to a metered TTS API (see ``app.services.voice``).
# Edge TTS (plain ``xx-YY-NameNeural-Gender``), local Chatterbox and the silent
# "no voice" option are free and estimate to $0.
_PAID_TTS_PREFIXES = ("elevenlabs:", "siliconflow:", "gemini:", "mimo:")
_CAPTIONS_ONLY_LAYOUT = "captions_only"


class CostCapExceeded(ValueError):
    """Raised before enqueue when a request's predicted provider spend is unsafe."""


@dataclass(frozen=True)
class CostEstimate:
    """A transparent, deterministic admission estimate in USD."""

    llm_usd: float
    tts_usd: float
    avatar_usd: float
    render_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        return round(self.llm_usd + self.tts_usd + self.avatar_usd + self.render_usd, 6)


def max_job_cost_usd() -> float:
    """Read the per-variant cap; a non-positive value explicitly disables it."""
    try:
        return max(0.0, float(config.app.get("reelforge_max_job_cost_usd", _DEFAULT_MAX_JOB_COST_USD)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_JOB_COST_USD


def render_usd_per_min() -> float:
    """Per-minute self-hosted render compute price; invalid config falls back."""
    try:
        return max(0.0, float(config.app.get("reelforge_render_usd_per_min", _DEFAULT_RENDER_USD_PER_MIN)))
    except (TypeError, ValueError):
        return _DEFAULT_RENDER_USD_PER_MIN


def _is_faceless_tts(params: Any) -> bool:
    """Mirror of ``reelforge._is_faceless_tts`` (kept import-free for admission).

    A ``captions_only`` job with no uploaded narration, no uploaded footage and
    a chosen ``voice_name``: the script is generated (unless typed), narrated by
    TTS, and composed over curated stock footage with no avatar.
    """
    return (
        str(getattr(params, "layout", "") or "") == _CAPTIONS_ONLY_LAYOUT
        and not str(getattr(params, "voiceover_key", "") or "")
        and not str(getattr(params, "screen_recording_key", "") or "")
        and bool(str(getattr(params, "voice_name", "") or "").strip())
    )


def _is_paid_tts_voice(voice_name: str) -> bool:
    """Whether the voice is synthesised by a metered API rather than a free engine."""
    name = str(voice_name or "").strip()
    if name.startswith(_PAID_TTS_PREFIXES):
        return True
    # Azure Speech v2 voices are named ``xx-YY-NameNeural-V2-Gender``.
    return name.replace("-Female", "").replace("-Male", "").strip().endswith("-V2")


def _estimate_faceless_tts(params: Any) -> CostEstimate:
    """Script LLM + TTS characters + self-hosted render for a faceless story reel."""
    script = str(getattr(params, "video_script", "") or "")
    duration_s = max(1, int(getattr(params, "target_duration_s", 30) or 30))
    llm_usd = 0.0 if script else cost.estimate_llm_cost("default", *_SCRIPT_LLM_TOKENS)
    chars = len(script) if script else duration_s * _DEFAULT_SCRIPT_CHARS_PER_SECOND
    tts_usd = cost.estimate_tts_cost(chars) if _is_paid_tts_voice(getattr(params, "voice_name", "")) else 0.0
    render_usd = round(duration_s / 60.0 * render_usd_per_min(), 6)
    return CostEstimate(llm_usd=llm_usd, tts_usd=tts_usd, avatar_usd=0.0, render_usd=render_usd)


def estimate_job_cost(params: Any) -> CostEstimate:
    """Estimate provider spend from validated ReelForge parameters.

    A caller-supplied script skips LLM generation. Bring-your-own voice skips
    ElevenLabs. Avatar cost is based on requested target duration and provider,
    making the estimate available before any billable call begins.
    """
    # A faceless story reel is captions_only too, but it generates a script and
    # narrates it with TTS, so it is priced like one (no avatar).
    if _is_faceless_tts(params):
        return _estimate_faceless_tts(params)
    # The remaining avatar-less captions-only path runs no LLM, TTS, or avatar
    # provider: captions come from local transcription of the screen recording's
    # own audio. Estimate zero provider spend so the per-job cost cap never
    # rejects a reel that is, by construction, free of paid provider calls.
    if str(getattr(params, "layout", "") or "") == _CAPTIONS_ONLY_LAYOUT:
        return CostEstimate(llm_usd=0.0, tts_usd=0.0, avatar_usd=0.0)

    script = str(getattr(params, "video_script", "") or "")
    duration_s = max(1, int(getattr(params, "target_duration_s", 30) or 30))
    llm_usd = 0.0 if script else cost.estimate_llm_cost("default", *_SCRIPT_LLM_TOKENS)
    tts_usd = 0.0 if getattr(params, "voiceover_key", "") else cost.estimate_tts_cost(
        len(script) if script else duration_s * _DEFAULT_SCRIPT_CHARS_PER_SECOND
    )
    avatar_usd = cost.estimate_avatar_cost(
        duration_s, str(getattr(params, "avatar_provider", "") or "heygen")
    )
    return CostEstimate(llm_usd=llm_usd, tts_usd=tts_usd, avatar_usd=avatar_usd)


def enforce_cost_cap(params: Any) -> CostEstimate:
    """Return the estimate or reject a request before jobs/debits/enqueue exist."""
    estimate = estimate_job_cost(params)
    cap = max_job_cost_usd()
    if cap > 0 and estimate.total_usd > cap:
        raise CostCapExceeded(
            f"estimated provider cost ${estimate.total_usd:.4f} exceeds "
            f"per-job cap ${cap:.4f}"
        )
    return estimate


def enforce_runtime_cost_cap(job_id: str) -> float:
    """Raise after a measured-cost event pushes a persisted job over its cap."""
    cap = max_job_cost_usd()
    if cap <= 0 or not job_id:
        return 0.0
    from app.models.db.base import get_session

    with get_session() as session:
        total = session.execute(
            select(func.coalesce(func.sum(JobEvent.cost_usd), 0.0)).where(
                JobEvent.job_id == job_id,
                JobEvent.status == "cost",
            )
        ).scalar_one()
    total_usd = round(float(total or 0.0), 6)
    if total_usd > cap:
        raise CostCapExceeded(
            f"measured provider cost ${total_usd:.4f} exceeds per-job cap ${cap:.4f}"
        )
    return total_usd


COST_CAP_REFUND_REASON = "cost_cap_refund"


def refund_cost_capped_job_once(job_id: str) -> bool:
    """Refund the current cycle's debit exactly once after a runtime cap breach.

    Uses the same single-refund ledger rule as owner cancel and failure refunds
    (:func:`app.domains.reels.refunds.refund_latest_debit_once_in_session`): the
    job row is locked, the NEWEST debit of the job (any debit reason, including
    pilot debits) is refunded into the pool it came from, and nothing is paid if
    a positive ledger row (cancel/failure/cost-cap refund) already follows it.
    That closes cancel-then-cap and fail-retry-cap double refunds, and lets a
    retried cycle that breaches the cap again be refunded for that cycle only.

    ``params.cost_cap_refunded`` is still stamped as an informational marker for
    the job detail view; it is not used as the idempotency guard.
    """
    if not job_id:
        return False
    from app.domains.reels.refunds import refund_latest_debit_once_in_session
    from app.models.db.base import get_session

    with get_session() as session:
        amount = refund_latest_debit_once_in_session(
            session, job_id, COST_CAP_REFUND_REASON
        )
        if amount <= 0:
            return False
        job = session.get(Job, job_id)
        if job is not None:
            job.params = {**dict(job.params or {}), "cost_cap_refunded": True}
        session.flush()
    return True
