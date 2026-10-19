"""Catalog administration: idempotent upsert of providers, models, prices, profiles.

Operator-only write path used by the seed dataset and the provider importers to
*publish* the reviewed catalog (PROVIDER_MARKETPLACE_PLAN.md §2/§4). Never a
client surface. Every operation is idempotent so a seed/import can run
repeatedly without duplicating rows or churning price versions:

* a provider/model/profile is matched on its natural key and updated in place;
* a price only creates a NEW immutable version when the price actually changed
  (same unit + amount => no-op), closing the prior version's window.

Prices seeded here are illustrative defaults with ``source='manual'`` and MUST be
reviewed by finance before any live charge; publishing a model live
(``release_status`` other than ``shadow``) is a deliberate operator choice.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.catalog.repository import CatalogRepository
from app.models.db.marketplace import (
    GenerationProfile,
    ModelCatalogEntry,
    PriceVersion,
    ProviderCatalog,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PromotionError(Exception):
    """Raised when a model is not safe to promote live (no price / no adapter)."""


class CatalogAdmin:
    """Idempotent publish operations over the reviewed catalog tables."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CatalogRepository(session)

    # ------------------------------------------------------------------ #
    # Providers
    # ------------------------------------------------------------------ #
    def upsert_provider(
        self,
        provider_key: str,
        *,
        display_name: str = "",
        region: str = "",
        data_policy: str = "",
        health_state: str | None = None,
        credential_state: str | None = None,
        enabled: bool | None = None,
    ) -> ProviderCatalog:
        """Create or update a provider. Flags default to "leave unchanged".

        ``enabled`` / ``credential_state`` / ``health_state`` are only written
        when explicitly passed, so a later shadow model of the same provider can
        never silently demote a provider an earlier call promoted (a new row
        starts disabled/unconfigured/unknown).
        """
        row = self._session.execute(
            select(ProviderCatalog).where(
                ProviderCatalog.provider_key == provider_key
            )
        ).scalars().first()
        is_new = row is None
        if row is None:
            row = ProviderCatalog(provider_key=provider_key)
            self._session.add(row)
        row.display_name = display_name or row.display_name or provider_key
        row.region = region or row.region
        row.data_policy = data_policy or row.data_policy
        if health_state is not None:
            row.health_state = health_state
        elif is_new:
            row.health_state = "unknown"
        if credential_state is not None:
            row.credential_state = credential_state
        elif is_new:
            row.credential_state = "unconfigured"
        if enabled is not None:
            row.enabled = bool(enabled)
        elif is_new:
            row.enabled = False
        row.updated_at = _now()
        self._session.flush()
        return row

    # ------------------------------------------------------------------ #
    # Model listings
    # ------------------------------------------------------------------ #
    def upsert_model(
        self,
        model_id: str,
        *,
        provider_key: str,
        capability: str,
        display_name: str = "",
        description: str = "",
        metering_unit: str = "",
        supported_inputs: list | None = None,
        output_limits: dict | None = None,
        region: str = "",
        data_policy: str = "",
        latency_band: str = "",
        availability_state: str = "available",
        release_status: str = "shadow",
    ) -> ModelCatalogEntry:
        provider = self.upsert_provider(provider_key)
        row = self._repo.get_model(model_id)
        if row is None:
            row = ModelCatalogEntry(model_id=model_id)
            self._session.add(row)
        row.provider_id = provider.id
        row.capability = capability
        row.display_name = display_name or row.display_name or model_id
        row.description = description or row.description
        row.metering_unit = metering_unit or row.metering_unit
        if supported_inputs is not None:
            row.supported_inputs = list(supported_inputs)
        if output_limits is not None:
            row.output_limits = dict(output_limits)
        row.region = region or row.region
        row.data_policy = data_policy or row.data_policy
        row.latency_band = latency_band or row.latency_band
        row.availability_state = availability_state
        row.release_status = release_status
        row.updated_at = _now()
        self._session.flush()
        return row

    # ------------------------------------------------------------------ #
    # Prices (immutable versions; new version only on real change)
    # ------------------------------------------------------------------ #
    def _latest_price(self, model_id: str) -> PriceVersion | None:
        return self._session.execute(
            select(PriceVersion)
            .where(PriceVersion.model_id == model_id)
            .order_by(PriceVersion.version.desc())
            .limit(1)
        ).scalars().first()

    def ensure_price(
        self,
        model_id: str,
        *,
        unit: str,
        unit_price_micros: int,
        min_charge_micros: int = 0,
        flat_fee_micros: int = 0,
        currency: str = "USD",
        source: str = "manual",
        quote_rules: dict | None = None,
    ) -> PriceVersion:
        """Ensure the active price matches; create a new version only on change."""
        latest = self._latest_price(model_id)
        unchanged = (
            latest is not None
            and latest.unit == unit
            and int(latest.unit_price_micros) == int(unit_price_micros)
            and int(latest.min_charge_micros) == int(min_charge_micros)
            and int(latest.flat_fee_micros) == int(flat_fee_micros)
            and latest.currency == currency
            and (latest.effective_to is None)
        )
        if unchanged:
            return latest  # type: ignore[return-value]

        model = self._repo.get_model(model_id)
        if model is None:
            raise ValueError(f"cannot price unknown model: {model_id}")

        next_version = (int(latest.version) + 1) if latest is not None else 1
        if latest is not None and latest.effective_to is None:
            # Close the prior version's window so history stays auditable.
            latest.effective_to = _now()

        row = PriceVersion(
            model_entry_id=model.id,
            model_id=model_id,
            unit=unit,
            unit_price_micros=int(unit_price_micros),
            min_charge_micros=int(min_charge_micros),
            flat_fee_micros=int(flat_fee_micros),
            currency=currency,
            source=source,
            quote_rules=dict(quote_rules or {}),
            version=next_version,
            effective_from=_now(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    # ------------------------------------------------------------------ #
    # Safe live promotion (adapter review + reconciled price gate)
    # ------------------------------------------------------------------ #
    def promotion_readiness(self, model_id: str, *, provider_registry=None) -> dict:
        """Report whether a model is safe to promote live, and why/why-not.

        A model may go live only when it has a reconciled price AND a registered
        provider adapter (the code-level proxy for "adapter reviewed"). Prices
        still marked ``source='shadow'`` do not count as reconciled.
        """
        from app.domains.routing.base import registry as default_registry

        reg = provider_registry or default_registry
        entry = self._repo.get_model(model_id)
        if entry is None:
            return {"model_id": model_id, "ready": False, "reasons": ["unknown model"]}
        provider = self._repo.get_provider(entry.provider_id)
        provider_key = getattr(provider, "provider_key", "")
        price = self._repo.active_price_version(model_id)
        reasons: list[str] = []
        has_price = price is not None and price.source != "shadow"
        if not has_price:
            reasons.append("no reconciled price (source must not be 'shadow')")
        has_adapter = bool(provider_key) and reg.has(provider_key)
        if not has_adapter:
            reasons.append(f"no registered adapter for provider '{provider_key}'")
        # MO1 licence gate: a model with non-commercial, research-only or
        # unrecorded weights can never become a live billable route.
        from app.domains.routing.license_class import is_model_sellable, model_license

        license_ok = is_model_sellable(model_id)
        if not license_ok:
            lic = model_license(model_id)
            cls = lic.license_class if lic else "unrecorded"
            reasons.append(f"licence is {cls}; not sellable (docs/THIRD_PARTY_MODELS.md)")
        return {
            "model_id": model_id,
            "provider_key": provider_key,
            "has_price": has_price,
            "has_adapter": has_adapter,
            "license_ok": license_ok,
            "ready": has_price and has_adapter and license_ok,
            "reasons": reasons,
        }

    def promote_model_live(self, model_id: str, *, provider_registry=None) -> dict:
        """Promote a model to a live billable route, enforcing readiness.

        Raises :class:`PromotionError` when the model is not ready (missing
        reconciled price or registered adapter) so an operator cannot ship a live
        route that would fail or mis-charge. On success sets ``release_status=ga``
        + ``availability=available`` and enables the provider (credential
        configured).
        """
        readiness = self.promotion_readiness(
            model_id, provider_registry=provider_registry
        )
        if not readiness["ready"]:
            raise PromotionError(
                f"cannot promote '{model_id}': {'; '.join(readiness['reasons'])}"
            )
        entry = self._repo.get_model(model_id)
        entry.release_status = "ga"
        entry.availability_state = "available"
        entry.updated_at = _now()
        self.upsert_provider(
            readiness["provider_key"], enabled=True, credential_state="configured"
        )
        self._session.flush()
        return {"model_id": model_id, "release_status": "ga", "enabled": True}

    # ------------------------------------------------------------------ #
    # Generation profiles
    # ------------------------------------------------------------------ #
    def upsert_profile(
        self,
        slug: str,
        *,
        display_name: str = "",
        description: str = "",
        stages: dict | None = None,
        routing: dict | None = None,
        max_cost_micros: int = 0,
        is_curated: bool = True,
    ) -> GenerationProfile:
        row = self._repo.get_profile(slug)
        if row is None:
            row = GenerationProfile(slug=slug)
            self._session.add(row)
        row.display_name = display_name or row.display_name or slug
        row.description = description or row.description
        if stages is not None:
            row.stages = dict(stages)
        if routing is not None:
            row.routing = dict(routing)
        row.max_cost_micros = int(max_cost_micros)
        row.is_curated = bool(is_curated)
        row.is_active = True
        row.updated_at = _now()
        self._session.flush()
        return row
