"""What a viewer may see and play (MV4/MV5): published, packaged, inside its window, not blocked."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.ott_access import geo

from .models import STATUS_PUBLISHED, OttChannel, OttCollection, OttSeries, OttTitle

READY = "ready"


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else (value if value.tzinfo else value.replace(tzinfo=timezone.utc))


def in_window(title: OttTitle, now: datetime | None = None) -> bool:
    moment = now or datetime.now(timezone.utc)
    start, end = _utc(title.available_from), _utc(title.available_until)
    return (start is None or start <= moment) and (end is None or moment < end)


def watchable(session: Session, title: OttTitle | None, *, now: datetime | None = None) -> bool:
    from app.domains.compliance.takedown import is_blocked_in_session

    if title is None or title.status != STATUS_PUBLISHED or title.package_status != READY:
        return False
    channel = session.get(OttChannel, title.channel_id)
    if channel is None or channel.status != STATUS_PUBLISHED or not in_window(title, now):
        return False
    if is_blocked_in_session(session, title.id):  # a report naming the title (uploads have no job)
        return False
    return not (title.source_job_id and is_blocked_in_session(session, title.source_job_id))


def channel_by_handle(session: Session, handle: str) -> OttChannel | None:
    channel = session.execute(select(OttChannel).where(OttChannel.handle == handle)).scalar_one_or_none()
    return channel if channel is not None and channel.status == STATUS_PUBLISHED else None


def visible_titles(session: Session, channel: OttChannel) -> list[OttTitle]:
    rows = session.execute(select(OttTitle).where(OttTitle.channel_id == channel.id,
                                                  OttTitle.status == STATUS_PUBLISHED)
                           .order_by(OttTitle.position, OttTitle.created_at)).scalars().all()
    return [t for t in rows if watchable(session, t)]


def _art(key: str) -> str:
    from app.domains.gallery.service import media_url

    return media_url(key)


def title_card(title: OttTitle, viewer_country: str) -> dict[str, Any]:
    return {"id": title.id, "title": title.title, "synopsis": title.synopsis, "kind": title.kind,
            "artwork_url": _art(title.artwork_key), "duration_s": title.duration_s, "genres": list(title.genres or []),
            "rating": title.rating, "series_id": title.series_id, "season": title.season, "episode": title.episode,
            "access_tier": title.access_tier, "credits": list(title.credits or []),
            "available_here": geo.allowed(title.geo_mode, title.geo_countries or [], viewer_country)}


def storefront(session: Session, channel: OttChannel, viewer_country: str) -> dict[str, Any]:
    titles = visible_titles(session, channel)
    by_id = {t.id: t for t in titles}
    rails = []
    for collection in session.execute(select(OttCollection).where(OttCollection.channel_id == channel.id)
                                      .order_by(OttCollection.position)).scalars().all():
        items = [title_card(by_id[i], viewer_country) for i in collection.title_ids or [] if i in by_id]
        if items:
            rails.append({"id": collection.id, "title": collection.title, "items": items})
    shorts = [title_card(t, viewer_country) for t in titles if t.kind == "short"]
    if shorts:
        rails.append({"id": "shorts", "title": "Shorts", "items": shorts})
    series = []
    for row in session.execute(select(OttSeries).where(OttSeries.channel_id == channel.id)
                               .order_by(OttSeries.position)).scalars().all():
        episodes = sorted((t for t in titles if t.series_id == row.id), key=lambda t: (t.season or 0, t.episode or 0))
        if episodes:
            series.append({"id": row.id, "title": row.title, "synopsis": row.synopsis,
                           "episodes": [title_card(t, viewer_country) for t in episodes]})
    return {"handle": channel.handle, "title": channel.title, "tagline": channel.tagline, "layout": channel.layout,
            "brand_colors": list(channel.brand_colors or []), "titles": [title_card(t, viewer_country) for t in titles],
            "rails": rails, "series": series}


__all__ = ["READY", "channel_by_handle", "in_window", "storefront", "title_card", "visible_titles", "watchable"]
