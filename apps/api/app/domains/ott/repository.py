"""OTT catalog data access (MV1): owner-scoped reads and writes, no business rules."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import STATUS_PUBLISHED, OttChannel, OttCollection, OttSeries, OttTitle


class OttRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def channel_for_user(self, user_id: str) -> OttChannel | None:
        return self.s.execute(select(OttChannel).where(OttChannel.user_id == user_id)).scalar_one_or_none()

    def channel_by_handle(self, handle: str) -> OttChannel | None:
        return self.s.execute(select(OttChannel).where(OttChannel.handle == handle)).scalar_one_or_none()

    def channel_by_domain(self, domain: str) -> OttChannel | None:
        return self.s.execute(select(OttChannel).where(OttChannel.custom_domain == domain)).scalar_one_or_none()

    def handle_taken(self, handle: str) -> bool:
        return self.channel_by_handle(handle) is not None

    def titles(self, channel_id: str, *, published_only: bool = False) -> list[OttTitle]:
        query = select(OttTitle).where(OttTitle.channel_id == channel_id)
        if published_only:
            query = query.where(OttTitle.status == STATUS_PUBLISHED)
        return list(self.s.execute(query.order_by(OttTitle.position, OttTitle.created_at)).scalars().all())

    def title(self, channel_id: str, title_id: str) -> OttTitle | None:
        row = self.s.get(OttTitle, title_id)
        return row if row is not None and row.channel_id == channel_id else None

    def title_for_job(self, channel_id: str, job_id: str) -> OttTitle | None:
        return self.s.execute(select(OttTitle).where(OttTitle.channel_id == channel_id,
                                                     OttTitle.source_job_id == job_id)).scalar_one_or_none()

    def titles_for_job(self, job_id: str) -> list[OttTitle]:
        return list(self.s.execute(select(OttTitle).where(OttTitle.source_job_id == job_id)).scalars().all())

    def series(self, channel_id: str) -> list[OttSeries]:
        return list(self.s.execute(select(OttSeries).where(OttSeries.channel_id == channel_id)
                                   .order_by(OttSeries.position)).scalars().all())

    def collections(self, channel_id: str) -> list[OttCollection]:
        return list(self.s.execute(select(OttCollection).where(OttCollection.channel_id == channel_id)
                                   .order_by(OttCollection.position)).scalars().all())

    def add(self, row: Any) -> Any:
        self.s.add(row)
        self.s.flush()
        return row
