"""Keyword tracker tables (migration ``d4c10050e5db``, Menivor Growth phase 2).

* :class:`TrackedKeyword` - one (App Store app, keyword, country) a user tracks.
  ``UNIQUE(user_id, app_id, term, country)``, so re-adding the same triple is a
  no-op at the service layer rather than a duplicate row.
* :class:`KeywordRankSnapshot` - one daily top-50 rank reading for a tracked
  keyword (``position`` is ``None`` when the app did not appear in the first
  50 results for that term/country on that day). History for the sparkline +
  7/30-day-change chart is just this table ordered by ``checked_at``.

App Store only: the Google Play Developer API has no public, keyless
keyword-rank endpoint (the same honest limitation already documented for the
App Store Audit tool and Phase 3 "Connect your store" ratings).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users)
from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class TrackedKeyword(Base):
    __tablename__ = "tracked_keywords"
    __table_args__ = (
        UniqueConstraint("user_id", "app_id", "term", "country", name="uq_tracked_keywords_user_app_term_country"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # The iTunes Search API's numeric app id (the id in an apps.apple.com URL).
    app_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # Denormalized label for the UI; not re-fetched, just whatever the caller
    # named the app when adding the keyword (usually from a connected store
    # app, see app.domains.store_connect).
    app_name: Mapped[str] = mapped_column(String(300), nullable=False, server_default=sql_text("('')"))
    # Two-letter iTunes storefront country code, lowercase (matches
    # app.domains.appaudit.visibility's cache key normalization).
    country: Mapped[str] = mapped_column(String(2), nullable=False, server_default=sql_text("('us')"))
    term: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    last_error: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("('')"))
    # Apple's own Search Popularity index (5-100 in steps of 5), filled in only
    # when the caller's scope has a connected `apple_search_ads` account (see
    # app.domains.integrations.service.keyword_insights); NULL otherwise or
    # when Apple has not scored the term yet. Refreshed at most every
    # ~20h (service.POPULARITY_REFRESH_EVERY), same cadence as the rank check.
    popularity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    popularity_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KeywordRankSnapshot(Base):
    __tablename__ = "keyword_rank_snapshots"
    __table_args__ = (
        Index("ix_keyword_rank_snapshots_keyword_checked", "keyword_id", "checked_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    keyword_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_keywords.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # None = not found in the top 50 results for that term/country that day.
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checked_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))


__all__ = ["KeywordRankSnapshot", "TrackedKeyword"]
