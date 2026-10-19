"""Catalog domain service: browse models/profiles + resolve generation quotes.

Owns the transaction-free read behaviour and the quote resolution that turns a
generation profile (or ad-hoc stage->model map) into a signed, versioned price
snapshot. Business errors are raised as :class:`CatalogError` (status + message)
so the thin router maps them to the shared HTTP envelope without leaking ORM or
provider internals.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.money import usd_to_micros
from app.domains.catalog import policy
from app.domains.catalog.repository import (
    LIVE_RELEASE_STATUSES,
    CatalogRepository,
)
from app.domains.catalog.schemas import (
    GenerationQuoteRequest,
    model_public_view,
    profile_public_view,
)


class CatalogError(Exception):
    """A caller-facing catalog failure carrying an HTTP status + safe message."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _quote_signing_secret() -> str:
    """Resolve the server-only quote signing secret (never returned to clients)."""
    secret = os.getenv("REELFORGE_QUOTE_SIGNING_KEY", "")
    if secret:
        return secret
    try:
        from app.config import config

        # Reuse the app key as a signing secret when a dedicated key is unset;
        # both are server-only and never leave the backend.
        return str(config.app.get("api_key", "") or "") or "reelforge-dev-quote-secret"
    except Exception:
        return "reelforge-dev-quote-secret"


class CatalogService:
    """Read + quote operations over the reviewed catalog."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CatalogRepository(session)

    # ------------------------------------------------------------------ #
    # Browse
    # ------------------------------------------------------------------ #
    def browse_models(
        self,
        *,
        capability: str | None = None,
        include_shadow: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        entries = self._repo.list_models(
            capability=capability,
            include_shadow=include_shadow,
            limit=limit,
            offset=offset,
        )
        providers = self._repo.providers_by_ids({e.provider_id for e in entries})
        views: list[dict] = []
        for entry in entries:
            price = self._repo.active_price_version(entry.model_id)
            views.append(
                model_public_view(entry, providers.get(entry.provider_id), price)
            )
        return views

    def compare_models(
        self, *, capability: str, sort: str = "price", limit: int = 50
    ) -> list[dict]:
        """Model listings for a capability enriched with provider health, sorted.

        Each row carries the price summary + the provider's rolling health
        (uptime %, avg latency, state) so a client can compare price vs
        reliability vs speed. ``sort`` is 'price' (cheapest first) or 'latency'
        (fastest first).
        """
        from app.domains.catalog.health import ProviderHealthService

        models = self.browse_models(capability=capability, limit=limit)
        health = ProviderHealthService(self._session)
        cache: dict[str, dict] = {}
        rows: list[dict] = []
        for model in models:
            provider_key = (model.get("provider") or {}).get("provider_key", "")
            if provider_key and provider_key not in cache:
                cache[provider_key] = health.summary(provider_key)
            rows.append({**model, "health": cache.get(provider_key, {})})

        latency_rank = {"fast": 0, "standard": 1, "slow": 2, "": 3}
        if sort == "latency":
            rows.sort(key=lambda r: latency_rank.get(r.get("latency_band", ""), 3))
        else:  # price
            rows.sort(key=lambda r: int((r.get("price") or {}).get("unit_price_micros", 0) or 0))
        return rows

    def get_model_detail(self, model_id: str, *, include_shadow: bool = False) -> dict:
        entry = self._repo.get_model(model_id)
        if entry is None or (
            not include_shadow and entry.release_status not in LIVE_RELEASE_STATUSES
        ):
            raise CatalogError(404, "model not found")
        provider = self._repo.get_provider(entry.provider_id)
        price = self._repo.active_price_version(entry.model_id)
        return model_public_view(entry, provider, price)

    def browse_profiles(
        self, *, user_id: str | None, workspace_id: str | None = None
    ) -> list[dict]:
        profiles = self._repo.list_profiles(
            user_id=user_id, workspace_id=workspace_id, include_curated=True
        )
        return [profile_public_view(p) for p in profiles]

    # ------------------------------------------------------------------ #
    # Quote
    # ------------------------------------------------------------------ #
    def _resolve_stage_map(
        self, request: GenerationQuoteRequest, *, user_id: str | None
    ) -> tuple[dict[str, str], int]:
        """Return the ``stage -> model_id`` map plus the profile-level cap.

        A named profile supplies the base stage map and (optional) max-cost cap;
        an ad-hoc ``stages`` map overrides/extends it. Raises when nothing
        resolves or the named profile is unknown / not visible to the caller.
        """
        stage_map: dict[str, str] = {}
        profile_cap_micros = 0

        if request.profile:
            profile = self._repo.get_profile(request.profile)
            if profile is None:
                raise CatalogError(404, "generation profile not found")
            if not self._repo.profile_visible_to(
                profile, user_id=user_id, workspace_id=request.workspace_id
            ):
                raise CatalogError(403, "generation profile is not available")
            for stage, spec in (profile.stages or {}).items():
                model_id = (
                    spec.get("model_id") if isinstance(spec, dict) else str(spec)
                )
                if model_id:
                    stage_map[str(stage)] = str(model_id)
            profile_cap_micros = int(profile.max_cost_micros or 0)

        for stage, model_id in (request.stages or {}).items():
            if model_id:
                stage_map[str(stage)] = str(model_id)

        if not stage_map:
            raise CatalogError(
                400, "a profile or a non-empty stages map is required"
            )
        return stage_map, profile_cap_micros

    def quote_generation(
        self,
        request: GenerationQuoteRequest,
        *,
        user_id: str | None,
        include_shadow: bool = False,
    ) -> dict:
        """Resolve a generation quote into a signed, versioned price snapshot."""
        stage_map, profile_cap_micros = self._resolve_stage_map(
            request, user_id=user_id
        )
        estimates = request.estimates or {}

        stage_snapshots: list[dict] = []
        total_micros = 0
        for stage, model_id in stage_map.items():
            entry = self._repo.get_model(model_id)
            if entry is None:
                raise CatalogError(422, f"unknown model for stage '{stage}'")
            live = entry.release_status in LIVE_RELEASE_STATUSES
            available = entry.availability_state == "available"
            if not include_shadow and (not live or not available):
                raise CatalogError(
                    422, f"model '{model_id}' is not available for '{stage}'"
                )
            price = self._repo.active_price_version(model_id)
            if price is None:
                raise CatalogError(
                    422, f"no active price for model '{model_id}'"
                )
            quantity = policy.estimate_quantity(
                price.quote_rules, estimates.get(stage)
            )
            cost = policy.stage_cost_micros(
                unit_price_micros=price.unit_price_micros,
                quantity_units=quantity,
                min_charge_micros=price.min_charge_micros,
                flat_fee_micros=price.flat_fee_micros,
            )
            total_micros += cost
            provider = self._repo.get_provider(entry.provider_id)
            stage_snapshots.append(
                {
                    "stage": stage,
                    "model_id": model_id,
                    "provider_key": getattr(provider, "provider_key", ""),
                    "capability": entry.capability,
                    "price_version_id": price.id,
                    "price_version": int(price.version or 1),
                    "unit": price.unit,
                    "unit_price_micros": int(price.unit_price_micros or 0),
                    "quantity_units": int(quantity),
                    "cost_micros": int(cost),
                    "price_source": price.source,
                }
            )

        request_cap = usd_to_micros(request.max_cost_usd) if request.max_cost_usd else 0
        cap_micros = policy.effective_cap_micros(profile_cap_micros, request_cap)
        within_budget = policy.within_cap(total_micros, cap_micros)
        expires_at = policy.quote_expiry(datetime.now(timezone.utc))

        snapshot: dict[str, Any] = {
            "quote_id": uuid.uuid4().hex,
            "profile": request.profile or "",
            "currency": "USD",
            "stages": stage_snapshots,
            "total_micros": int(total_micros),
            # The amount the wallet reserves for this job = the quoted total.
            "max_cost_micros": int(total_micros),
            "cap_micros": cap_micros,
            "within_budget": within_budget,
            "expires_at": expires_at.replace(microsecond=0).isoformat(),
        }
        snapshot["signature"] = policy.sign_quote(snapshot, _quote_signing_secret())
        return snapshot

    def verify_quote_snapshot(self, snapshot: dict) -> bool:
        """Re-check a returned quote snapshot's signature (used at job create)."""
        signature = (snapshot or {}).get("signature", "")
        return policy.verify_quote(snapshot, signature, _quote_signing_secret())
