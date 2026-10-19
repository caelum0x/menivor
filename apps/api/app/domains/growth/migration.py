"""Growth — sunset-model migration recommender (Sora-shutdown onboarding).

The research's clearest acquisition wedge: when a hosted model is sunset (e.g. the
Sora 2 API removal on 2026-09-24), creators mid-pipeline need a drop-in routed
replacement. This core reads the shared license/deprecation table
(``routing.license_class``) and, for a creator's current model, returns a concrete
migration recommendation — replacement model, urgency, and messaging hook — that
the onboarding funnel + in-app banner use to convert switchers.

Pure + deterministic (``on`` date is injected); shares one source of truth with
the route-time license gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domains.routing import license_class as lic


@dataclass(frozen=True)
class MigrationOffer:
    """A migration recommendation for a creator on a sunsetting model."""

    from_model: str
    needs_migration: bool
    urgency: str                 # none | soon | urgent | expired
    replacement: str = ""
    days_left: int | None = None
    headline: str = ""
    cta: str = ""


def recommend_migration(model_key: str, *, on: date, soon_days: int = 30) -> MigrationOffer:
    """Recommend a migration for ``model_key`` as of ``on``.

    urgency: ``expired`` (past sunset), ``urgent`` (≤7d), ``soon`` (≤soon_days),
    else ``none``. The replacement comes from the license table.
    """
    status = lic.sunset_status(model_key, on=on)
    days_left = status.get("days_left")
    replacement = status.get("replacement", "")

    if days_left is None:
        return MigrationOffer(model_key, False, "none")

    if days_left <= 0:
        urgency = "expired"
        headline = f"{model_key} is offline — your renders now route to {replacement}"
        cta = f"Switch to {replacement} (1 click, same wallet)"
    elif days_left <= 7:
        urgency = "urgent"
        headline = f"{model_key} shuts down in {days_left} days — migrate now"
        cta = f"Move my pipeline to {replacement}"
    elif days_left <= soon_days:
        urgency = "soon"
        headline = f"{model_key} is being retired in {days_left} days"
        cta = f"Preview {replacement} on your next reel"
    else:
        return MigrationOffer(model_key, False, "none", replacement, days_left)

    return MigrationOffer(
        from_model=model_key,
        needs_migration=True,
        urgency=urgency,
        replacement=replacement,
        days_left=days_left,
        headline=headline,
        cta=cta,
    )


def sunsetting_models(*, on: date, within_days: int = 60) -> list[MigrationOffer]:
    """All known models sunsetting within ``within_days`` (for a campaign sweep)."""
    offers: list[MigrationOffer] = []
    for model_key, model in lic._LICENSES.items():  # noqa: SLF001 - same-package read
        if model.sunset_on is None:
            continue
        offer = recommend_migration(model_key, on=on, soon_days=within_days)
        if offer.needs_migration:
            offers.append(offer)
    offers.sort(key=lambda o: (o.days_left if o.days_left is not None else 9999))
    return offers
