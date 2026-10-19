"""Viewer retention on one channel (Wave Q QM1.5, U37): watchlist, ratings and push opt-ins.

Everything is per channel viewer (the pair channel and person), so a list
on channel A is never visible on channel B. :func:`erase` runs inside
``service.delete_viewer`` so deleting the account removes all three.

Push carries only two kinds of message, and only to viewers who chose them:
a new episode on the channel (``episodes``) and a live start (``live``).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.domains.ott import catalog_public
from app.domains.ott.models import OttTitle

from .models import OttRating, OttViewer, OttViewerPush, OttWatchlistItem

TOPICS = ("episodes", "live")
PLATFORMS = ("ios", "android", "tv", "web")
MAX_WATCHLIST = 500
_EXPO_TOKEN = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_-]{10,180}\]$")


class RetentionError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _title(session: Session, viewer: OttViewer, title_id: str) -> OttTitle:
    title = session.get(OttTitle, title_id)
    if title is None or title.channel_id != viewer.channel_id or not catalog_public.watchable(session, title):
        raise RetentionError(404, "title", "title not found")
    return title


# --------------------------------------------------------------------------- #
# Watchlist
# --------------------------------------------------------------------------- #
def watchlist(session: Session, viewer: OttViewer, *, country: str = "XX") -> list[dict[str, Any]]:
    rows = session.execute(select(OttWatchlistItem).where(OttWatchlistItem.viewer_id == viewer.id)
                           .order_by(OttWatchlistItem.created_at.desc(), OttWatchlistItem.id)).scalars().all()
    titles = {t.id: t for t in session.execute(select(OttTitle).where(
        OttTitle.id.in_([r.title_id for r in rows]))).scalars()} if rows else {}
    out = []
    for row in rows:
        title = titles.get(row.title_id)
        if title is not None and catalog_public.watchable(session, title):
            out.append(catalog_public.title_card(title, country))
    return out


def add_to_watchlist(session: Session, viewer: OttViewer, title_id: str) -> bool:
    title = _title(session, viewer, title_id)
    exists = session.execute(select(OttWatchlistItem.id).where(OttWatchlistItem.viewer_id == viewer.id,
                                                               OttWatchlistItem.title_id == title.id)).first()
    if exists:
        return False
    count = session.execute(select(func.count(OttWatchlistItem.id)).where(
        OttWatchlistItem.viewer_id == viewer.id)).scalar_one()
    if count >= MAX_WATCHLIST:
        raise RetentionError(409, "watchlist_full", "Your list is full. Remove a title to add this one.")
    session.add(OttWatchlistItem(viewer_id=viewer.id, channel_id=viewer.channel_id, title_id=title.id))
    session.flush()
    return True


def remove_from_watchlist(session: Session, viewer: OttViewer, title_id: str) -> bool:
    result = session.execute(delete(OttWatchlistItem).where(OttWatchlistItem.viewer_id == viewer.id,
                                                            OttWatchlistItem.title_id == title_id))
    return bool(result.rowcount)


# --------------------------------------------------------------------------- #
# Ratings
# --------------------------------------------------------------------------- #
def rating_view(session: Session, title_id: str, viewer: OttViewer | None = None) -> dict[str, Any]:
    count, average = session.execute(select(func.count(OttRating.id), func.avg(OttRating.stars)).where(
        OttRating.title_id == title_id)).one()
    mine = None
    if viewer is not None:
        mine = session.execute(select(OttRating.stars).where(OttRating.viewer_id == viewer.id,
                                                             OttRating.title_id == title_id)).scalar_one_or_none()
    return {"title_id": title_id, "mine": mine, "count": int(count or 0),
            "average": round(float(average), 2) if average is not None else None}


def title_rating(session: Session, viewer: OttViewer, title_id: str) -> dict[str, Any]:
    """The ratings of a watchable title on the viewer's own channel (404 otherwise, QM verify)."""
    return rating_view(session, _title(session, viewer, title_id).id, viewer)


def rate(session: Session, viewer: OttViewer, title_id: str, stars: int) -> dict[str, Any]:
    if not 1 <= int(stars) <= 5:
        raise RetentionError(400, "stars", "a rating is 1 to 5 stars")
    title = _title(session, viewer, title_id)
    row = session.execute(select(OttRating).where(OttRating.viewer_id == viewer.id,
                                                  OttRating.title_id == title.id)).scalar_one_or_none()
    if row is None:
        row = OttRating(viewer_id=viewer.id, channel_id=viewer.channel_id, title_id=title.id, stars=int(stars))
        session.add(row)
    row.stars = int(stars)
    session.flush()
    return rating_view(session, title.id, viewer)


def unrate(session: Session, viewer: OttViewer, title_id: str) -> dict[str, Any]:
    session.execute(delete(OttRating).where(OttRating.viewer_id == viewer.id, OttRating.title_id == title_id))
    session.flush()
    return rating_view(session, title_id, viewer)


# --------------------------------------------------------------------------- #
# Push opt-in
# --------------------------------------------------------------------------- #
def opt_in(session: Session, viewer: OttViewer, *, token: str, platform: str, topics: list[str]) -> dict[str, Any]:
    if not _EXPO_TOKEN.match(token or ""):
        raise RetentionError(400, "token", "not a push token")
    if platform not in PLATFORMS:
        raise RetentionError(400, "platform", f"platform is one of {', '.join(PLATFORMS)}")
    chosen = sorted({t for t in topics if t in TOPICS})
    if not chosen:
        raise RetentionError(400, "topics", "choose new episodes, live starts, or both")
    row = session.execute(select(OttViewerPush).where(OttViewerPush.viewer_id == viewer.id,
                                                      OttViewerPush.token == token)).scalar_one_or_none()
    if row is None:
        row = OttViewerPush(viewer_id=viewer.id, channel_id=viewer.channel_id, token=token)
        session.add(row)
    row.platform, row.topics = platform, chosen
    session.flush()
    return {"opted_in": True, "topics": chosen}


def opt_out(session: Session, viewer: OttViewer, token: str = "") -> dict[str, Any]:
    query = delete(OttViewerPush).where(OttViewerPush.viewer_id == viewer.id)
    if token:
        query = query.where(OttViewerPush.token == token)
    removed = session.execute(query).rowcount
    return {"opted_in": False, "removed": int(removed or 0)}


def push_tokens(session: Session, channel_id: str, topic: str) -> list[str]:
    """The opted-in tokens of one channel for one topic (deduplicated)."""
    if topic not in TOPICS:
        return []
    rows = session.execute(select(OttViewerPush.token, OttViewerPush.topics).where(
        OttViewerPush.channel_id == channel_id)).all()
    return sorted({token for token, topics in rows if topic in (topics or [])})


def erase(session: Session, viewer_id: str) -> dict[str, int]:
    """Delete everything retention keeps for a viewer (account deletion)."""
    counts = {}
    for name, model in (("watchlist_deleted", OttWatchlistItem), ("ratings_deleted", OttRating),
                        ("push_deleted", OttViewerPush)):
        counts[name] = int(session.execute(delete(model).where(model.viewer_id == viewer_id)).rowcount or 0)
    return counts


__all__ = ["MAX_WATCHLIST", "PLATFORMS", "RetentionError", "TOPICS", "add_to_watchlist", "erase", "opt_in", "title_rating",
           "opt_out", "push_tokens", "rate", "rating_view", "remove_from_watchlist", "unrate", "watchlist"]
