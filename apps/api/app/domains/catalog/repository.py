"""Catalog persistence: reviewed providers, models, price versions, profiles.

Pure query/persistence layer (no HTTP, no business rules). The service layer
composes these reads into browse responses and quote snapshots. All methods are
owner/visibility-aware where relevant so a caller can never see another user's
private generation profile.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db.marketplace import (
    GenerationProfile,
    ModelCatalogEntry,
    PriceVersion,
    ProviderCatalog,
)

# Release statuses that are billable/live product routes. Shadow entries are
# browsable internally but excluded from the public catalog by default.
LIVE_RELEASE_STATUSES: tuple[str, ...] = ("preview", "ga")


def _as_naive_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to naive UTC for dialect-agnostic comparison.

    SQLite stores ``CURRENT_TIMESTAMP`` as a naive UTC string while Postgres
    keeps tz-aware values; comparing price-effectiveness windows in Python (on a
    handful of rows) avoids fragile cross-dialect tz coercion in SQL.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class CatalogRepository:
    """Reads over the reviewed catalog tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Providers
    # ------------------------------------------------------------------ #
    def get_provider(self, provider_id: str) -> ProviderCatalog | None:
        return self._session.get(ProviderCatalog, provider_id)

    def providers_by_ids(self, ids: set[str]) -> dict[str, ProviderCatalog]:
        """Batch-load providers for a set of entry ``provider_id`` values."""
        if not ids:
            return {}
        stmt = select(ProviderCatalog).where(ProviderCatalog.id.in_(ids))
        return {p.id: p for p in self._session.execute(stmt).scalars().all()}

    # ------------------------------------------------------------------ #
    # Model listings
    # ------------------------------------------------------------------ #
    def list_models(
        self,
        *,
        capability: str | None = None,
        include_shadow: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ModelCatalogEntry]:
        """List reviewed model entries, newest first, with optional filters.

        By default only live (non-shadow) entries are returned so the public
        browse surface never exposes an internally-evaluated shadow listing.
        """
        stmt = select(ModelCatalogEntry)
        if capability:
            stmt = stmt.where(ModelCatalogEntry.capability == capability)
        if not include_shadow:
            stmt = stmt.where(
                ModelCatalogEntry.release_status.in_(LIVE_RELEASE_STATUSES)
            )
        stmt = (
            stmt.order_by(ModelCatalogEntry.created_at.desc(), ModelCatalogEntry.id)
            .limit(max(1, min(200, limit)))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_model(self, model_id: str) -> ModelCatalogEntry | None:
        """Resolve one reviewed listing by its stable catalog ``model_id``."""
        normalized = (model_id or "").strip()
        if not normalized:
            return None
        stmt = select(ModelCatalogEntry).where(
            ModelCatalogEntry.model_id == normalized
        )
        return self._session.execute(stmt).scalars().first()

    # ------------------------------------------------------------------ #
    # Price versions
    # ------------------------------------------------------------------ #
    def active_price_version(
        self, model_id: str, *, at: datetime | None = None
    ) -> PriceVersion | None:
        """Return the price version effective at ``at`` (default: now).

        Effective when ``effective_from <= at`` and ``effective_to`` is null or
        in the future. When several overlap the highest ``version`` wins. The
        window filter runs in Python (few rows/model) for tz-safe comparison.
        """
        normalized = (model_id or "").strip()
        if not normalized:
            return None
        moment = _as_naive_utc(at) or datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = (
            select(PriceVersion)
            .where(PriceVersion.model_id == normalized)
            .order_by(PriceVersion.version.desc())
        )
        for row in self._session.execute(stmt).scalars().all():
            start = _as_naive_utc(row.effective_from)
            end = _as_naive_utc(row.effective_to)
            if start is not None and start > moment:
                continue
            if end is not None and end <= moment:
                continue
            return row
        return None

    # ------------------------------------------------------------------ #
    # Generation profiles
    # ------------------------------------------------------------------ #
    def list_profiles(
        self,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        include_curated: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GenerationProfile]:
        """List active profiles visible to a caller.

        Visible = curated (when ``include_curated``) OR owned by ``user_id`` OR
        belonging to ``workspace_id``. Inactive profiles are hidden. A caller
        never sees another user's private profile.
        """
        visibility = []
        if include_curated:
            visibility.append(GenerationProfile.is_curated.is_(True))
        if user_id:
            visibility.append(GenerationProfile.owner_user_id == user_id)
        if workspace_id:
            visibility.append(GenerationProfile.workspace_id == workspace_id)
        if not visibility:
            return []

        from sqlalchemy import or_

        stmt = (
            select(GenerationProfile)
            .where(GenerationProfile.is_active.is_(True), or_(*visibility))
            .order_by(
                GenerationProfile.is_curated.desc(),
                GenerationProfile.created_at.desc(),
                GenerationProfile.id,
            )
            .limit(max(1, min(200, limit)))
            .offset(max(0, offset))
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_price_version(self, price_version_id: str) -> PriceVersion | None:
        """Load a specific price version by id (for settling a stored quote)."""
        if not price_version_id:
            return None
        return self._session.get(PriceVersion, price_version_id)

    def get_profile(self, slug: str) -> GenerationProfile | None:
        normalized = (slug or "").strip()
        if not normalized:
            return None
        stmt = select(GenerationProfile).where(GenerationProfile.slug == normalized)
        return self._session.execute(stmt).scalars().first()

    def profile_visible_to(
        self,
        profile: GenerationProfile,
        *,
        user_id: str | None,
        workspace_id: str | None = None,
    ) -> bool:
        """Whether ``profile`` may be used by the given caller.

        Curated + active profiles are usable by everyone; an owned profile is
        usable only by its owning user or workspace. Inactive profiles are never
        usable.
        """
        if not profile.is_active:
            return False
        if profile.is_curated and profile.owner_user_id is None:
            return True
        if user_id and profile.owner_user_id == user_id:
            return True
        if workspace_id and profile.workspace_id == workspace_id:
            return True
        return False
