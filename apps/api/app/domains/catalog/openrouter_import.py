"""Import OpenRouter's model list into the catalog as SHADOW entries.

Ingests OpenRouter's published ``/models`` (id, pricing, modality) and registers
each as a reviewed-shape ``model_catalog_entries`` row under the ``openrouter``
provider, in **shadow mode** (browsable/quotable internally, never a live route
until an operator promotes it). This treats OpenRouter as one upstream gateway
under ReelForge's own catalog/wallet/routing contract — not a fork of its
backend (PROVIDER_MARKETPLACE_PLAN.md §9.2).

Pricing: OpenRouter reports per-token USD prices; the completion price is mapped
to integer microdollars per output token. A model with no usable price is still
registered (browsable) but skipped for pricing so it cannot be mis-quoted.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.core.money import usd_to_micros
from app.domains.catalog.admin import CatalogAdmin

_PROVIDER_KEY = "openrouter"


def _infer_capability(row: dict) -> str:
    """Map an OpenRouter model's modality to a ReelForge capability.

    Text is by far the common case (script). Image-output models map to
    ``image``; everything else defaults to ``script`` so it stays browsable.
    """
    modality = ""
    arch = row.get("architecture")
    if isinstance(arch, dict):
        modality = str(arch.get("output_modalities") or arch.get("modality") or "")
    modality = modality.lower()
    if "image" in modality:
        return "image"
    return "script"


def _completion_price_micros(row: dict) -> int:
    """Microdollars per output token from OpenRouter's ``pricing.completion``."""
    pricing = row.get("pricing")
    if not isinstance(pricing, dict):
        return 0
    raw = pricing.get("completion")
    if raw in (None, ""):
        return 0
    try:
        return usd_to_micros(raw)
    except ValueError:
        return 0


def import_openrouter_models(
    session: Session,
    *,
    adapter: Any,
    limit: int | None = None,
) -> dict[str, int]:
    """Upsert OpenRouter models into the catalog (shadow). Returns counts.

    ``adapter`` must expose ``raw_models() -> list[dict]`` (the OpenRouter
    adapter). Idempotent: re-running updates rows and only versions a price when
    it actually changed.
    """
    admin = CatalogAdmin(session)
    admin.upsert_provider(
        _PROVIDER_KEY, display_name="OpenRouter", region="global"
    )

    rows = adapter.raw_models()
    if limit is not None:
        rows = rows[: max(0, int(limit))]

    imported = 0
    priced = 0
    for row in rows:
        raw_id = str(row.get("id") or "").strip()
        if not raw_id:
            continue
        model_id = f"{_PROVIDER_KEY}/{raw_id}"
        capability = _infer_capability(row)
        unit = "output_tokens" if capability == "script" else "images"
        admin.upsert_model(
            model_id,
            provider_key=_PROVIDER_KEY,
            capability=capability,
            display_name=str(row.get("name") or raw_id),
            description=str(row.get("description") or "")[:1000],
            metering_unit=unit,
            availability_state="available",
            release_status="shadow",
        )
        imported += 1

        if capability == "script":
            price = _completion_price_micros(row)
            if price > 0:
                admin.ensure_price(
                    model_id,
                    unit=unit,
                    unit_price_micros=price,
                    quote_rules={"default_units": 1500},
                    source="provider_import",
                )
                priced += 1

    session.flush()
    logger.info(
        f"OpenRouter catalog import: {imported} models ({priced} priced) in shadow"
    )
    return {"imported": imported, "priced": priced}
