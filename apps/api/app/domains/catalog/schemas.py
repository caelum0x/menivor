"""Catalog domain DTOs (Pydantic v2).

Request models for the quote endpoint plus small typed builders for the public
model/profile/quote views. Responses are emitted through the shared MPT envelope
(``utils.get_response``) so these describe the ``data`` payloads only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GenerationQuoteRequest(BaseModel):
    """A request for a generation price quote.

    Either name a curated/owned ``profile`` slug, or pass an ad-hoc
    ``stages`` map of ``stage -> model_id``. ``estimates`` optionally overrides
    the per-stage billed quantity; ``max_cost_usd`` is a caller budget cap
    (decimal string, e.g. ``"2.50"``) checked against the resolved estimate.
    """

    model_config = ConfigDict(extra="forbid")

    profile: str | None = Field(default=None, description="Generation profile slug")
    stages: dict[str, str] | None = Field(
        default=None, description="Ad-hoc stage -> catalog model_id map"
    )
    estimates: dict[str, int] | None = Field(
        default=None, description="Optional stage -> billed quantity override"
    )
    max_cost_usd: str | None = Field(
        default=None, description="Caller budget cap as a decimal USD string"
    )
    workspace_id: str | None = Field(
        default=None, description="Workspace context for profile visibility"
    )


def provider_public_view(provider: object | None) -> dict:
    """Non-sensitive provider fields safe to expose in a model listing."""
    if provider is None:
        return {}
    return {
        "provider_key": getattr(provider, "provider_key", ""),
        "display_name": getattr(provider, "display_name", ""),
        "region": getattr(provider, "region", ""),
        "data_policy": getattr(provider, "data_policy", ""),
        "health_state": getattr(provider, "health_state", "unknown"),
    }


def price_public_view(price: object | None) -> dict:
    """Compact price summary (unit + microdollar unit price) for a listing."""
    if price is None:
        return {}
    return {
        "price_version_id": getattr(price, "id", ""),
        "currency": getattr(price, "currency", "USD"),
        "unit": getattr(price, "unit", ""),
        "unit_price_micros": int(getattr(price, "unit_price_micros", 0) or 0),
        "min_charge_micros": int(getattr(price, "min_charge_micros", 0) or 0),
        "flat_fee_micros": int(getattr(price, "flat_fee_micros", 0) or 0),
        "version": int(getattr(price, "version", 1) or 1),
    }


def model_public_view(entry: object, provider: object | None, price: object | None) -> dict:
    """The client-facing shape of one reviewed model listing."""
    return {
        "model_id": getattr(entry, "model_id", ""),
        "capability": getattr(entry, "capability", ""),
        "display_name": getattr(entry, "display_name", ""),
        "description": getattr(entry, "description", ""),
        "metering_unit": getattr(entry, "metering_unit", ""),
        "supported_inputs": getattr(entry, "supported_inputs", []) or [],
        "output_limits": getattr(entry, "output_limits", {}) or {},
        "region": getattr(entry, "region", ""),
        "data_policy": getattr(entry, "data_policy", ""),
        "latency_band": getattr(entry, "latency_band", ""),
        "availability_state": getattr(entry, "availability_state", "available"),
        "release_status": getattr(entry, "release_status", "shadow"),
        "provider": provider_public_view(provider),
        "price": price_public_view(price),
    }


def profile_public_view(profile: object) -> dict:
    """The client-facing shape of one generation profile."""
    return {
        "slug": getattr(profile, "slug", ""),
        "display_name": getattr(profile, "display_name", ""),
        "description": getattr(profile, "description", ""),
        "stages": getattr(profile, "stages", {}) or {},
        "routing": getattr(profile, "routing", {}) or {},
        "max_cost_micros": int(getattr(profile, "max_cost_micros", 0) or 0),
        "is_curated": bool(getattr(profile, "is_curated", False)),
    }
