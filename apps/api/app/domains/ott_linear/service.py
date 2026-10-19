"""FAST channels (MV15): schedules from a channel's free titles, the guide, and the playout engine feed.

Playout runs in Eyevinn Channel Engine (Apache-2.0, manifest rewriting only,
no transcoding; ``deploy/menivor-fast``). Its asset manager asks
``GET /ott/linear/{slug}/items/{n}`` for the n-th item of the loop and gets a
tokenized HLS link to the packaged title (engine grants live as long as the
title plus 15 minutes). Ad breaks are filled with the MV14 decision for a free
title of the channel; an empty break is skipped. Only free, packaged titles
are scheduled.
"""

from __future__ import annotations

import hmac
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.ott import catalog_public
from app.domains.ott.models import OttChannel, OttTitle
from app.domains.ott_access import service as access, tokens
from app.domains.ott_live.models import OttLinearChannel

from . import schedule

ENGINE_KEY_ENV = "OTT_FAST_ENGINE_KEY"
PLAYBACK_ENV = "OTT_FAST_PLAYBACK_BASE"
MAX_TITLES = 200
ENGINE_TTL_PAD_S = 900
_SLUG = re.compile(r"^[a-z0-9-]{3,40}$")


class LinearError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def now() -> datetime:
    return datetime.now(timezone.utc)


def _schedulable(session: Session, title: Optional[OttTitle], channel_id: str) -> bool:
    return (title is not None and title.channel_id == channel_id and title.access_tier == "free"
            and catalog_public.watchable(session, title))


def save(session: Session, channel: OttChannel, body: Mapping[str, Any]) -> OttLinearChannel:
    from app.domains.presets_hub.catalog import vendor_hits

    slug = str(body.get("slug") or channel.handle).lower()
    if not _SLUG.match(slug):
        raise LinearError(400, "slug", "the channel address is 3-40 letters, digits or dashes")
    name = " ".join(str(body.get("name") or channel.title).split())[:80]
    if vendor_hits(name):
        raise LinearError(400, "copy_vendor", "names cannot name tools or models")
    title_ids = [str(t) for t in body.get("title_ids") or []][:MAX_TITLES]
    bad = [t for t in title_ids if not _schedulable(session, session.get(OttTitle, t), channel.id)]
    if bad or not title_ids:
        raise LinearError(400, "titles", "pick free titles of your channel that are published and ready")
    ad_every = int(body.get("ad_break_every") or 0)
    if not 0 <= ad_every <= 20:
        raise LinearError(400, "ads", "an ad break every 0 to 20 programs")
    row = session.execute(select(OttLinearChannel).where(OttLinearChannel.slug == slug)).scalar_one_or_none()
    if row is not None and row.channel_id != channel.id:
        raise LinearError(409, "slug_taken", "that channel address is taken")
    if row is None:
        row = OttLinearChannel(channel_id=channel.id, slug=slug, anchor_at=now())
        session.add(row)
    if list(row.title_ids or []) != title_ids or int(row.ad_break_every or 0) != ad_every:
        row.anchor_at = now()
    row.name, row.title_ids, row.ad_break_every, row.enabled = name, title_ids, ad_every, True
    session.flush()
    return row


def by_slug(session: Session, slug: str) -> OttLinearChannel:
    row = session.execute(select(OttLinearChannel).where(OttLinearChannel.slug == slug)).scalar_one_or_none()
    if row is None or not row.enabled:
        raise LinearError(404, "not_found", "channel not found")
    return row


def cycle_for(session: Session, row: OttLinearChannel) -> list[schedule.Item]:
    programs = []
    for title_id in row.title_ids or []:
        title = session.get(OttTitle, title_id)
        if _schedulable(session, title, row.channel_id):
            programs.append(schedule.Item(kind=schedule.PROGRAM, duration_s=float(title.duration_s or 0),
                                          title_id=title.id, name=title.title, synopsis=title.synopsis or ""))
    cycle = schedule.build_cycle(programs, int(row.ad_break_every or 0))
    if not cycle:
        raise LinearError(404, "empty", "nothing to play on this channel right now")
    return cycle


def now_playing(session: Session, row: OttLinearChannel, *, at: Optional[datetime] = None) -> dict[str, Any]:
    cycle = cycle_for(session, row)
    moment = at or now()
    guide = schedule.slots(cycle, row.anchor_at, moment, hours=3)
    upcoming = [s for s in guide if s.item.kind == schedule.PROGRAM][:4]
    index, current, offset = schedule.at(cycle, row.anchor_at, moment)
    return {"slug": row.slug, "name": row.name, "index": index, "offset_s": round(offset, 1),
            "now": {"kind": current.kind, "title": current.name},
            "next": [{"title": s.item.name, "start": s.start.isoformat()} for s in upcoming if s.index > index][:3],
            "watch_url": f"{playback_base()}/channels/{row.slug}/master.m3u8"}


def epg(session: Session, row: OttLinearChannel, *, at: Optional[datetime] = None, hours: float = 24) -> bytes:
    cycle = cycle_for(session, row)
    guide = schedule.slots(cycle, row.anchor_at, at or now(), hours=hours)
    return schedule.xmltv(f"{row.slug}.menivor", row.name, guide)


def playback_base() -> str:
    return (os.getenv(PLAYBACK_ENV) or "https://fast.menivor.com").rstrip("/")


def check_engine(given: str, env: Optional[Mapping[str, str]] = None) -> None:
    key = ((env if env is not None else os.environ).get(ENGINE_KEY_ENV) or "").strip()
    if len(key) < 24 or not hmac.compare_digest(str(given or ""), key):
        raise LinearError(401, "engine", "unknown caller")


def _engine_link(title: OttTitle, *, at: Optional[float] = None) -> tuple[str, int]:
    ttl = int(float(title.duration_s or 0) + ENGINE_TTL_PAD_S)
    token, grant = tokens.issue(title.id, "fast-engine", "XX", ttl_s=ttl, max_ttl_s=tokens.ENGINE_MAX_TTL_S, now=at)
    path = access.STREAM_PATH.format(token=token, path="master.m3u8")
    return f"{access._api_base()}{path}", grant.exp


def engine_item(session: Session, row: OttLinearChannel, index: int, *, at: Optional[float] = None
                ) -> dict[str, Any]:
    """The n-th item for the playout engine; an ad break with no ad is skipped to the next program."""
    from app.domains.ott_ads import service as ads

    cycle = cycle_for(session, row)
    for step in range(len(cycle)):
        n = index + step
        current = schedule.item(cycle, n)
        if current.kind == schedule.PROGRAM:
            title = session.get(OttTitle, current.title_id)
            uri, exp = _engine_link(title, at=at)
            return {"index": n, "kind": schedule.PROGRAM, "id": title.id, "title": title.title, "uri": uri,
                    "duration_s": title.duration_s, "expires_at": exp}
        probe = OttTitle(id=f"linear-{row.id}", channel_id=row.channel_id, access_tier="free", title="")
        ad = ads.decide(session, probe)
        if ad is None:
            continue
        media = session.get(OttTitle, ad.title_id)
        uri, exp = _engine_link(media, at=at)
        return {"index": n, "kind": schedule.AD, "id": ad.id, "title": ad.name, "uri": uri,
                "duration_s": media.duration_s, "expires_at": exp}
    raise LinearError(404, "empty", "nothing to play on this channel right now")


def view(row: OttLinearChannel) -> dict[str, Any]:
    return {"id": row.id, "slug": row.slug, "name": row.name, "title_ids": list(row.title_ids or []),
            "ad_break_every": row.ad_break_every, "enabled": row.enabled,
            "watch_url": f"{playback_base()}/channels/{row.slug}/master.m3u8"}


__all__ = ["ENGINE_KEY_ENV", "LinearError", "by_slug", "check_engine", "cycle_for", "engine_item", "epg",
           "now_playing", "save", "view"]
