"""Public OTT reads (MV4): storefront, title, embed, oEmbed, custom domains, RSS, MRSS and podcast RSS.

Every route answers 404 until OTT_ENABLED plus its surface flag (storefront,
embed or feeds) are on. Reads are edge-cached for at most 30 s, so an
unpublish or takedown is gone within 60 s. Feeds list only free titles that
are published, packaged and inside their window; feed media links go through
``/ott/feeds/play/{id}.m3u8``, which issues a fresh short token each time.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from fastapi import Depends, Path, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, get_session
from app.domains.ott_access import geo
from app.models.exception import HttpException
from app.utils import utils

from . import catalog_public, flags
from .models import OttChannel, OttTitle

router = new_router()
CACHE = "public, max-age=15, s-maxage=30"
WEB_BASE_ENV = "MENIVOR_PUBLIC_WEB_BASE"
API_BASE_ENV = "MENIVOR_PUBLIC_API_BASE"
ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
MEDIA = "http://search.yahoo.com/mrss/"
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("media", MEDIA)
ET.register_namespace("atom", ATOM)


def web_base() -> str:
    return (os.getenv(WEB_BASE_ENV) or "https://menivor.com").rstrip("/")


def api_base() -> str:
    return (os.getenv(API_BASE_ENV) or "https://api.menivor.com").rstrip("/")


def _not_found(request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=404, message=f"{request_id}: not found")


def _channel(session, handle: str, request_id: str) -> OttChannel:
    channel = catalog_public.channel_by_handle(session, handle)
    if channel is None:
        raise _not_found(request_id)
    return channel


@router.get("/ott/c/{handle}", dependencies=[Depends(flags.require("storefront"))], summary="Channel storefront")
def storefront(request: Request, response: Response, handle: str = Path(..., max_length=40)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        view = catalog_public.storefront(session, _channel(session, handle, request_id), geo.country(request.headers))
    response.headers["Cache-Control"] = CACHE
    response.headers["Vary"] = "CF-IPCountry"
    return utils.get_response(200, view)


@router.get("/ott/c/{handle}/titles/{title_id}", dependencies=[Depends(flags.require("storefront"))],
            summary="One title on a channel")
def title_detail(request: Request, response: Response, handle: str = Path(..., max_length=40),
                 title_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        channel = _channel(session, handle, request_id)
        title = session.get(OttTitle, title_id)
        if title is None or title.channel_id != channel.id or not catalog_public.watchable(session, title):
            raise _not_found(request_id)
        card = catalog_public.title_card(title, geo.country(request.headers))
    response.headers["Cache-Control"] = CACHE
    response.headers["Vary"] = "CF-IPCountry"
    return utils.get_response(200, {**card, "channel": {"handle": channel.handle, "title": channel.title}})


@router.get("/ott/domains/{host}", dependencies=[Depends(flags.require("storefront"))],
            summary="The channel served on a custom domain")
def custom_domain(request: Request, response: Response, host: str = Path(..., max_length=253)):
    from sqlalchemy import select

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        channel = session.execute(select(OttChannel).where(OttChannel.custom_domain == host.lower())
                                  ).scalar_one_or_none()
        if channel is None or channel.status != "published":
            raise _not_found(request_id)
        handle = channel.handle
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=300"
    return utils.get_response(200, {"handle": handle})


@router.get("/ott/embed/{title_id}", dependencies=[Depends(flags.require("embed"))], summary="Embed player data")
def embed(request: Request, response: Response, title_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        title = session.get(OttTitle, title_id)
        if not catalog_public.watchable(session, title):
            raise _not_found(request_id)
        channel = session.get(OttChannel, title.channel_id)
        card = catalog_public.title_card(title, geo.country(request.headers))
    response.headers["Cache-Control"] = CACHE
    return utils.get_response(200, {**card, "channel": {"handle": channel.handle, "title": channel.title},
                                    "watch_url": f"{web_base()}/c/{channel.handle}/{title_id}"})


@router.get("/ott/oembed", dependencies=[Depends(flags.require("embed"))], summary="oEmbed for a title page")
def oembed(request: Request, url: str = Query(..., max_length=500), maxwidth: int = Query(360, ge=120, le=1920)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) != 3 or segments[0] != "c":
        raise _not_found(request_id)
    with get_session() as session:
        title = session.get(OttTitle, segments[2])
        if not catalog_public.watchable(session, title):
            raise _not_found(request_id)
        name = title.title
    width = int(maxwidth)
    height = int(width * 16 / 9)
    src = f"{web_base()}/embed/{segments[2]}"
    html = (f'<iframe src="{src}" width="{width}" height="{height}" frameborder="0" '
            'allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>')
    return {"version": "1.0", "type": "video", "provider_name": "Menivor", "title": name, "width": width,
            "height": height, "html": html}


# --------------------------------------------------------------------------- #
# Feeds
# --------------------------------------------------------------------------- #
def _feed_titles(session, channel: OttChannel, *, kind: str | None = None) -> list[OttTitle]:
    titles = [t for t in catalog_public.visible_titles(session, channel) if t.access_tier == "free"]
    return [t for t in titles if kind is None or t.kind == kind]


def _date(value: datetime | None) -> str:
    moment = value or datetime.now(timezone.utc)
    return format_datetime(moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc))


def _sub(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        node.text = str(text)
    return node


def build_feed(channel: OttChannel, titles: list[OttTitle], *, flavour: str) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    ch = _sub(rss, "channel")
    home = f"{web_base()}/c/{channel.handle}"
    _sub(ch, "title", channel.title or channel.handle)
    _sub(ch, "link", home)
    _sub(ch, "description", channel.tagline or f"Videos from {channel.title or channel.handle}")
    _sub(ch, "language", "en")
    _sub(ch, f"{{{ATOM}}}link", href=f"{api_base()}/api/v1/ott/c/{channel.handle}/{flavour}.xml", rel="self",
         type="application/rss+xml")
    if flavour == "podcast":
        _sub(ch, f"{{{ITUNES}}}author", channel.title or channel.handle)
        _sub(ch, f"{{{ITUNES}}}explicit", "false")
        ET.SubElement(ch, f"{{{ITUNES}}}category", {"text": "Society & Culture"})
        if channel.artwork_key:
            _sub(ch, f"{{{ITUNES}}}image", href=catalog_public._art(channel.artwork_key))
    for title in titles:
        item = _sub(ch, "item")
        link = f"{home}/{title.id}"
        _sub(item, "title", title.title)
        _sub(item, "link", link)
        _sub(item, "guid", f"menivor-ott-{title.id}", isPermaLink="false")
        _sub(item, "pubDate", _date(title.published_at))
        _sub(item, "description", title.synopsis or title.title)
        play = f"{api_base()}/api/v1/ott/feeds/play/{title.id}.m3u8"
        if flavour == "mrss":
            content = _sub(item, f"{{{MEDIA}}}content", url=play, type="application/vnd.apple.mpegurl",
                           medium="video", duration=int(title.duration_s or 0))
            _sub(content, f"{{{MEDIA}}}title", title.title)
            for credit in title.credits or []:
                # Wave Q QM1.5 (U4): cast and crew in MRSS out (EBU role scheme, lower-case roles).
                _sub(content, f"{{{MEDIA}}}credit", credit.get("name", ""), role=str(credit.get("role", "")).lower(),
                     scheme="urn:ebu")
            if title.artwork_key:
                _sub(item, f"{{{MEDIA}}}thumbnail", url=catalog_public._art(title.artwork_key))
        if flavour == "podcast":
            audio = f"{api_base()}/api/v1/ott/feeds/audio/{title.id}.m4a"
            _sub(item, "enclosure", url=audio, type="audio/mp4", length=max(1, int(title.duration_s * 16000)))
            _sub(item, f"{{{ITUNES}}}duration", int(title.duration_s or 0))
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="utf-8")


def _feed(request: Request, handle: str, flavour: str, kind: str | None) -> Response:
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        channel = _channel(session, handle, request_id)
        body = build_feed(channel, _feed_titles(session, channel, kind=kind), flavour=flavour)
    return Response(content=body, media_type="application/rss+xml; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=300, s-maxage=600"})


@router.get("/ott/c/{handle}/rss.xml", dependencies=[Depends(flags.require("feeds"))], summary="Channel RSS")
def rss(request: Request, handle: str = Path(..., max_length=40)):
    return _feed(request, handle, "rss", None)


@router.get("/ott/c/{handle}/mrss.xml", dependencies=[Depends(flags.require("feeds"))], summary="Channel MRSS")
def mrss(request: Request, handle: str = Path(..., max_length=40)):
    return _feed(request, handle, "mrss", None)


@router.get("/ott/c/{handle}/podcast.xml", dependencies=[Depends(flags.require("feeds"))],
            summary="Podcast RSS of the channel's audio titles")
def podcast(request: Request, handle: str = Path(..., max_length=40)):
    return _feed(request, handle, "podcast", "audio")


@router.get("/ott/feeds/play/{title_id}.m3u8", dependencies=[Depends(flags.require("feeds"))],
            summary="A fresh tokenized stream for a feed item (free titles)")
def feed_play(request: Request, title_id: str = Path(..., max_length=32)):
    from app.domains.ott_access import service as access

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        title = session.get(OttTitle, title_id)
        if not catalog_public.watchable(session, title) or title.access_tier != "free":
            raise _not_found(request_id)
        try:
            grant = access.start(session, title, viewer=f"feed:{access.client_fingerprint(request)}",
                                 country=geo.country(request.headers))
        except access.AccessError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code, message=str(exc),
                                data={"code": exc.code}) from exc
    return RedirectResponse(grant["manifest_url"], status_code=302, headers={"Cache-Control": "no-store"})


@router.get("/ott/feeds/audio/{title_id}.m4a", dependencies=[Depends(flags.require("feeds"))],
            summary="Podcast enclosure (free audio titles)")
def feed_audio(request: Request, title_id: str = Path(..., max_length=32)):
    from app.domains.ott_access import service as access

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        title = session.get(OttTitle, title_id)
        if not catalog_public.watchable(session, title) or title.access_tier != "free" or title.kind != "audio":
            raise _not_found(request_id)
        url = access.source_url(title)
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
