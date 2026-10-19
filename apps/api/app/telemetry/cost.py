"""Per-job USD cost telemetry (CTO plan §0: "unit economics from job #1").

This module is intentionally *pure* and dependency-light. It exposes three
side-effect-free cost estimators — one per external cost driver in the
ReelForge pipeline — plus a single :func:`record_cost` helper that writes an
append-only ``JobEvent`` carrying the estimated ``cost_usd`` and the measured
``duration_ms``.

Price table (defaults from ``ugc-tool-cto-plan.md`` §"Costs" and
``ugc-video-tool-build-plan.md`` §6 "Unit economics"):

* **LLM (Claude Sonnet):** ``<$0.01/job``. Priced per-million-tokens
  (input/output) so the estimate scales with real token usage.
* **TTS (ElevenLabs ``eleven_multilingual_v2``):** ``~$0.15`` per ~150-word
  narration → modelled as ``$0.15`` per 1,000 characters.
* **Avatar (HeyGen v2, Tier A):** ``~$0.50–1.00 / min`` → ``$0.75/min`` midpoint
  default. Tier-B self-hosted lip-sync (LatentSync) is ``~$0.02–0.05 / min``.

The tables are module-level and therefore *configurable*: callers may pass an
explicit ``prices=`` / ``usd_per_1k_chars=`` override, mutate the module dicts,
or set an ``[telemetry]`` config section (read lazily and defensively — a
missing/invalid section silently falls back to the defaults below).

All estimators clamp negative / non-finite inputs to zero and round to 6 dp
(micro-dollar precision) so a bad upstream value can never produce a NaN, a
negative cost, or a spuriously huge number.
"""

from __future__ import annotations

import math
from typing import Any

from loguru import logger

__all__ = [
    "DEFAULT_AVATAR_USD_PER_MIN",
    "DEFAULT_LLM_PRICES_PER_1M",
    "DEFAULT_TTS_USD_PER_1K_CHARS",
    "estimate_avatar_cost",
    "estimate_llm_cost",
    "estimate_tts_cost",
    "record_cost",
]

# ``status`` value written on the JobEvent produced by :func:`record_cost`.
COST_EVENT_STATUS: str = "cost"

# LLM per-1,000,000-token prices as ``(input_usd, output_usd)``. Claude Sonnet
# 4.x is the launch model (plan §Stack). ``default`` is the fallback for any
# unrecognised model id.
DEFAULT_LLM_PRICES_PER_1M: dict[str, tuple[float, float]] = {
    "anthropic/claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "default": (3.0, 15.0),
}

# ElevenLabs Creator plan, plan figure ``~$0.15`` per ~150-word narration.
DEFAULT_TTS_USD_PER_1K_CHARS: float = 0.15

# Avatar provider per-minute prices (USD). Plan §"Avatar tiers".
DEFAULT_AVATAR_USD_PER_MIN: dict[str, float] = {
    "heygen": 0.75,       # ~$0.50–1.00/min → midpoint
    "d-id": 0.60,         # cheaper Tier-A alternative
    "latentsync": 0.03,   # Tier-B self-hosted ~$0.02–0.05/min
    "musetalk": 0.03,
    "default": 0.75,
}


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _finite_non_negative(value: Any) -> float:
    """Coerce ``value`` to a finite, non-negative float (0.0 on any failure)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number) or number < 0.0:
        return 0.0
    return number


def _config_overrides() -> dict[str, Any]:
    """Best-effort read of an optional ``[telemetry]`` config price override.

    Never raises: the ``telemetry`` config section is optional and may be
    absent (it is not bound by default), so any failure falls back to ``{}``
    and the module defaults are used.
    """
    try:
        from app.config import config

        section = getattr(config, "telemetry", None)
        if section is None:
            return {}
        return dict(section)
    except Exception as exc:  # noqa: BLE001 - config is optional; never crash
        logger.debug(f"telemetry.cost: no config overrides available: {exc}")
        return {}


def _normalize_model(model: str) -> str:
    """Lower-case / strip a model id for price-table lookup."""
    return (model or "").strip().lower()


# --------------------------------------------------------------------------- #
# Pure estimators
# --------------------------------------------------------------------------- #
def estimate_llm_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    prices: dict[str, tuple[float, float]] | None = None,
) -> float:
    """Estimate the USD cost of one LLM call.

    Args:
        model: Model id (e.g. ``"anthropic/claude-sonnet-5"``). Unknown ids fall
            back to the ``"default"`` price.
        input_tokens: Prompt/input tokens (clamped to >= 0).
        output_tokens: Completion/output tokens (clamped to >= 0).
        prices: Optional override table ``{model: (in_per_1m, out_per_1m)}``.

    Returns:
        USD cost rounded to 6 decimal places (>= 0.0).
    """
    table = prices or DEFAULT_LLM_PRICES_PER_1M
    key = _normalize_model(model)
    in_per_1m, out_per_1m = table.get(key) or table.get("default") or (0.0, 0.0)

    in_tokens = _finite_non_negative(input_tokens)
    out_tokens = _finite_non_negative(output_tokens)
    cost = (
        in_tokens / 1_000_000.0 * _finite_non_negative(in_per_1m)
        + out_tokens / 1_000_000.0 * _finite_non_negative(out_per_1m)
    )
    return round(cost, 6)


def estimate_tts_cost(
    chars: int,
    *,
    usd_per_1k_chars: float | None = None,
) -> float:
    """Estimate the USD cost of a TTS synthesis from its character count.

    Args:
        chars: Number of characters synthesised (clamped to >= 0).
        usd_per_1k_chars: Optional price override. Defaults to
            :data:`DEFAULT_TTS_USD_PER_1K_CHARS` (or an ``[telemetry]`` config
            override when present).

    Returns:
        USD cost rounded to 6 decimal places (>= 0.0).
    """
    if usd_per_1k_chars is None:
        override = _config_overrides().get("tts_usd_per_1k_chars")
        usd_per_1k_chars = (
            override if override is not None else DEFAULT_TTS_USD_PER_1K_CHARS
        )
    rate = _finite_non_negative(usd_per_1k_chars)
    n_chars = _finite_non_negative(chars)
    return round(n_chars / 1000.0 * rate, 6)


def estimate_avatar_cost(
    seconds: float,
    provider: str = "heygen",
    *,
    prices: dict[str, float] | None = None,
) -> float:
    """Estimate the USD cost of an avatar render from its duration.

    Args:
        seconds: Rendered avatar duration in seconds (clamped to >= 0).
        provider: Provider id (``"heygen"`` | ``"latentsync"`` | ...). Unknown
            providers fall back to the ``"default"`` per-minute price.
        prices: Optional override table ``{provider: usd_per_min}``.

    Returns:
        USD cost rounded to 6 decimal places (>= 0.0).
    """
    table = prices or DEFAULT_AVATAR_USD_PER_MIN
    key = (provider or "").strip().lower()
    per_min = table.get(key)
    if per_min is None:
        per_min = table.get("default", 0.0)
    duration_s = _finite_non_negative(seconds)
    return round(duration_s / 60.0 * _finite_non_negative(per_min), 6)


# --------------------------------------------------------------------------- #
# Recorder
# --------------------------------------------------------------------------- #
def record_cost(
    job_id: str,
    stage: str,
    cost_usd: float,
    duration_ms: int = 0,
    meta: dict[str, Any] | None = None,
) -> Any:
    """Write an append-only ``JobEvent`` capturing this stage's unit economics.

    Delegates to :func:`app.telemetry.events.record_event` with a dedicated
    ``"cost"`` status so cost rows are trivially filterable while remaining part
    of the single append-only ``job_events`` audit trail. Best-effort: any
    persistence failure is swallowed by ``record_event`` (returns ``None``), so
    this never crashes a render stage.

    Args:
        job_id: Owning ``Job.id``.
        stage: Pipeline stage the cost is attributed to (``"tts"`` | ``"avatar"``
            | ``"script"`` | ...).
        cost_usd: Estimated USD cost (coerced non-negative downstream).
        duration_ms: Stage wall-clock duration in milliseconds.
        meta: Optional JSON-serialisable breakdown (e.g. ``{"chars": 812}``)
            stored in the event ``payload``.

    Returns:
        The persisted ``JobEvent`` (or ``None`` if telemetry was unavailable).
    """
    from app.telemetry.events import record_event

    return record_event(
        job_id,
        stage,
        COST_EVENT_STATUS,
        payload=meta or {},
        cost_usd=_finite_non_negative(cost_usd),
        duration_ms=duration_ms,
    )
