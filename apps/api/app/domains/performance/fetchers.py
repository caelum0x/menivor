"""Read one post's numbers - connected account first, then public endpoints.

Every function returns a :class:`Stats`; none raises. A counter a platform does
not report is ``None`` (unknown) and is never shown or summed as 0. The only
network seam is the injectable :class:`Transport` shared with the publishers.

Sources per platform:

* TikTok / YouTube / Instagram - the connected account through
  :func:`app.domains.insights.platform_metrics.fetch_post_metrics`. A YouTube
  video that is not on the connected channel falls back to the public Data API
  counters when a server key (``YOUTUBE_API_KEY``) is configured.
* Facebook Page videos - Graph API likes/comments summaries (Page token) plus
  ``video_insights`` for views.
* Threads - ``/{media-id}/insights``.
* X - ``GET /2/tweets/{id}`` ``public_metrics``.
* Bluesky - the public AppView (no account needed).
* Titles for pasted TikTok / YouTube links come from their public oEmbed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from urllib.parse import quote

from loguru import logger

from app.domains.insights.platform_metrics import PostMetrics, fetch_post_metrics
from app.domains.publishing.connectors.base import RequestsTransport, Transport, _ok, _safe_json

from .access import NOT_OFFERED, label, metrics_access

_FB_GRAPH = "https://graph.facebook.com/v21.0"
_IG_GRAPH = "https://graph.facebook.com/v21.0"
_THREADS_GRAPH = "https://graph.threads.net/v1.0"
_X_API = "https://api.x.com/2"
_BSKY_PUBLIC = "https://public.api.bsky.app/xrpc"
_YT_DATA = "https://www.googleapis.com/youtube/v3/videos"
_YT_OEMBED = "https://www.youtube.com/oembed"
_TIKTOK_OEMBED = "https://www.tiktok.com/oembed"
_MEDIA_PAGES = 4
_TITLE_MAX = 300
_TIMEOUT_S = 20.0

OK = "ok"
NEEDS_ACCESS = "needs_access"
NO_STATS = "no_stats"
RATE_LIMITED = "rate_limited"
WAITING = "waiting"


@dataclass(frozen=True)
class Access:
    """A connected account's usable token (``connected=False`` when there is none)."""

    connected: bool
    token: str = ""
    account_id: str = ""
    scopes: str = ""
    note: str = ""


NO_ACCESS = Access(connected=False)


@dataclass(frozen=True)
class Stats:
    platform: str
    external_id: str
    outcome: str
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    avg_watch_frac: float | None = None
    title: str = ""
    url: str = ""
    note: str = ""
    resolved_id: str = ""  # the platform's numeric id when the input was a shortcode/handle

    @property
    def ok(self) -> bool:
        return self.outcome == OK


def default_transport() -> Transport:
    return RequestsTransport(timeout_s=_TIMEOUT_S)


def _int(value: Any) -> int | None:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _sum(*values: int | None) -> int | None:
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def _status(resp: Any) -> int:
    try:
        return int(getattr(resp, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _refused(platform: str, external_id: str, status: int, url: str = "") -> Stats:
    name = label(platform)
    if status in (401, 403):
        return Stats(platform, external_id, NEEDS_ACCESS, url=url,
                     note=f"Reconnect {name} and allow access to your stats so Menivor can read this post.")
    if status == 429:
        return Stats(platform, external_id, RATE_LIMITED, url=url,
                     note=f"{name} asked us to slow down; the numbers will be checked again later.")
    if status == 404:
        return Stats(platform, external_id, NO_STATS, url=url,
                     note=f"{name} could not find this post. It may be private or deleted.")
    return Stats(platform, external_id, WAITING, url=url,
                 note=f"{name} could not share this post's numbers right now; they will be checked again later.")


def _title(text: Any) -> str:
    line = next((ln.strip() for ln in str(text or "").splitlines() if ln.strip()), "")
    return line[:_TITLE_MAX]


# --------------------------------------------------------------------------- #
# Native platforms (TikTok / YouTube / Instagram)
# --------------------------------------------------------------------------- #
def from_post_metrics(m: PostMetrics) -> Stats:
    """Convert the shared native-metrics record, keeping unknown counters unknown."""
    if not m.available:
        if m.status in (401, 403, 429, 404):
            return _refused(m.platform, m.external_id, m.status, m.url)
        if "No connected" in m.note:
            return Stats(m.platform, m.external_id, NEEDS_ACCESS, url=m.url,
                         note=f"Connect {label(m.platform)} so Menivor can read this post.")
        return Stats(m.platform, m.external_id, WAITING, url=m.url, note=m.note)
    unknown = set(m.unknown)
    return Stats(
        platform=m.platform,
        external_id=m.external_id,
        outcome=OK,
        views=m.views,
        likes=None if "likes" in unknown else m.likes,
        comments=None if "comments" in unknown else m.comments,
        shares=None if "shares" in unknown else m.shares,
        saves=None if "saves" in unknown else m.saves,
        avg_watch_frac=m.avg_watch_frac,
        url=m.url,
    )


def _youtube_key() -> str:
    env = os.getenv("YOUTUBE_API_KEY", "").strip()
    if env:
        return env
    try:
        from app.config import config

        return str(config.app.get("youtube_api_key", "") or "").strip()
    except Exception:  # pragma: no cover - config always bound in practice
        return ""


def youtube_public(video_id: str, transport: Transport, *, api_key: str | None = None, url: str = "") -> Stats:
    """Public counters for any public video (needs the server's YouTube API key)."""
    key = _youtube_key() if api_key is None else api_key
    if not key:
        return Stats("youtube", video_id, NEEDS_ACCESS, url=url,
                     note="Connect the YouTube channel that posted this video to see its numbers.")
    resp = transport.request("GET", _YT_DATA, params={"part": "statistics,snippet", "id": video_id, "key": key})
    if not _ok(resp):
        return _refused("youtube", video_id, _status(resp), url)
    items = _safe_json(resp).get("items") or []
    item = items[0] if items and isinstance(items[0], dict) else {}
    stats = item.get("statistics") or {}
    if not stats:
        return Stats("youtube", video_id, NO_STATS, url=url, note="YouTube did not return this video (private or deleted?).")
    return Stats(
        "youtube", video_id, OK,
        views=_int(stats.get("viewCount")), likes=_int(stats.get("likeCount")),
        comments=_int(stats.get("commentCount")),
        title=_title((item.get("snippet") or {}).get("title")), url=url,
    )


def _instagram_media_id(token: str, account_id: str, shortcode: str, transport: Transport) -> tuple[str, str, int]:
    """(media id, caption, refused status) for one of the account's posts by shortcode."""
    if not account_id:
        return "", "", 0
    url = f"{_IG_GRAPH}/{account_id}/media"
    params: dict | None = {"fields": "id,shortcode,permalink,caption", "limit": 50, "access_token": token}
    for _ in range(_MEDIA_PAGES):
        resp = transport.request("GET", url, params=params)
        if not _ok(resp):
            return "", "", _status(resp)
        body = _safe_json(resp)
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("shortcode") or "")
            permalink = str(item.get("permalink") or "")
            if code == shortcode or f"/{shortcode}/" in permalink:
                return str(item.get("id") or ""), str(item.get("caption") or ""), 0
        next_url = str(((body.get("paging") or {}).get("next")) or "")
        if not next_url.startswith(_IG_GRAPH):
            break
        url, params = next_url, None
    return "", "", 0


def native(
    user_id: str, platform: str, external_id: str, access: Access, transport: Transport, *,
    posted_on: date, duration_s: float = 0.0, url: str = "", id_kind: str = "id",
) -> Stats:
    plat = platform
    ext = external_id
    title = ""
    if not access.connected:
        if plat == "youtube":
            return youtube_public(ext, transport, url=url)
        return Stats(plat, ext, NEEDS_ACCESS, url=url,
                     note=f"Connect {label(plat)} so Menivor can read this post's numbers.")
    gate = metrics_access(plat, connected=True, scopes=access.scopes)
    if not gate.reads_numbers:
        if plat == "youtube":
            public = youtube_public(ext, transport, url=url)
            if public.ok:
                return public
        return Stats(plat, ext, NEEDS_ACCESS, url=url, note=gate.note)
    if plat == "instagram" and id_kind == "shortcode":
        media_id, caption, refused = _instagram_media_id(access.token, access.account_id, ext, transport)
        if refused:
            return _refused(plat, ext, refused, url)
        if not media_id:
            return Stats(plat, ext, NO_STATS, url=url,
                         note="This post is not on your connected Instagram account, so Instagram does not share its numbers.")
        ext, title = media_id, _title(caption)
    result = from_post_metrics(fetch_post_metrics(
        user_id, plat, ext, published_on=posted_on, duration_s=duration_s, url=url,
        transport=transport, token=access.token,
    ))
    if plat == "youtube" and not result.ok and result.outcome != RATE_LIMITED:
        # Not on the connected channel (or analytics not granted): public counters.
        public = youtube_public(ext, transport, url=url)
        if public.ok:
            return public
    return replace(result, title=title or result.title, resolved_id=ext if ext != external_id else "")


# --------------------------------------------------------------------------- #
# Facebook / Threads / X / Bluesky
# --------------------------------------------------------------------------- #
def facebook(video_id: str, access: Access, transport: Transport, *, url: str = "") -> Stats:
    if not access.connected:
        return Stats("facebook", video_id, NEEDS_ACCESS, url=url,
                     note="Connect your Facebook Page so Menivor can read this post's numbers.")
    resp = transport.request("GET", f"{_FB_GRAPH}/{video_id}", params={
        "fields": "description,likes.summary(true).limit(0),comments.summary(true).limit(0)",
        "access_token": access.token,
    })
    if not _ok(resp):
        return _refused("facebook", video_id, _status(resp), url)
    body = _safe_json(resp)
    likes = _int(((body.get("likes") or {}).get("summary") or {}).get("total_count"))
    comments = _int(((body.get("comments") or {}).get("summary") or {}).get("total_count"))
    views: int | None = None
    note = ""
    insights = transport.request("GET", f"{_FB_GRAPH}/{video_id}/video_insights", params={
        "metric": "blue_reels_play_count,total_video_views", "access_token": access.token,
    })
    if _ok(insights):
        for entry in _safe_json(insights).get("data") or []:
            if not isinstance(entry, dict):
                continue
            values = entry.get("values") or []
            value = values[0].get("value") if values and isinstance(values[0], dict) else None
            if _int(value) is not None:
                views = max(views or 0, _int(value) or 0)
    else:
        note = "Reconnect Facebook and allow insights to see views too."
    return Stats("facebook", video_id, OK, views=views, likes=likes, comments=comments,
                 title=_title(body.get("description")), url=url, note=note)


def _threads_media_id(token: str, shortcode: str, transport: Transport) -> tuple[str, str, int]:
    url = f"{_THREADS_GRAPH}/me/threads"
    params: dict | None = {"fields": "id,shortcode,permalink,text", "limit": 50, "access_token": token}
    for _ in range(_MEDIA_PAGES):
        resp = transport.request("GET", url, params=params)
        if not _ok(resp):
            return "", "", _status(resp)
        body = _safe_json(resp)
        for item in body.get("data") or []:
            if isinstance(item, dict) and (
                str(item.get("shortcode") or "") == shortcode or f"/{shortcode}" in str(item.get("permalink") or "")
            ):
                return str(item.get("id") or ""), str(item.get("text") or ""), 0
        next_url = str(((body.get("paging") or {}).get("next")) or "")
        if not next_url.startswith(_THREADS_GRAPH):
            break
        url, params = next_url, None
    return "", "", 0


def threads(external_id: str, access: Access, transport: Transport, *, url: str = "", id_kind: str = "id") -> Stats:
    if not access.connected:
        return Stats("threads", external_id, NEEDS_ACCESS, url=url,
                     note="Connect Threads so Menivor can read this post's numbers.")
    gate = metrics_access("threads", connected=True, scopes=access.scopes)
    if not gate.reads_numbers:
        return Stats("threads", external_id, NEEDS_ACCESS, url=url, note=gate.note)
    media_id, title = external_id, ""
    if id_kind == "shortcode":
        media_id, text, refused = _threads_media_id(access.token, external_id, transport)
        if refused:
            return _refused("threads", external_id, refused, url)
        if not media_id:
            return Stats("threads", external_id, NO_STATS, url=url,
                         note="This post is not on your connected Threads account, so Threads does not share its numbers.")
        title = _title(text)
    resp = transport.request("GET", f"{_THREADS_GRAPH}/{media_id}/insights", params={
        "metric": "views,likes,replies,reposts,quotes,shares", "access_token": access.token,
    })
    if not _ok(resp):
        return _refused("threads", external_id, _status(resp), url)
    values: dict[str, int | None] = {}
    for entry in _safe_json(resp).get("data") or []:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("values")
        value = raw[0].get("value") if isinstance(raw, list) and raw and isinstance(raw[0], dict) else (
            (entry.get("total_value") or {}).get("value"))
        values[str(entry.get("name") or "")] = _int(value)
    return Stats(
        "threads", external_id, OK, views=values.get("views"), likes=values.get("likes"),
        comments=values.get("replies"),
        shares=_sum(values.get("reposts"), values.get("quotes"), values.get("shares")),
        title=title, url=url, resolved_id=media_id if media_id != external_id else "",
    )


def x_post(post_id: str, access: Access, transport: Transport, *, url: str = "") -> Stats:
    if not access.connected:
        return Stats("x", post_id, NEEDS_ACCESS, url=url, note="Connect X so Menivor can read this post's numbers.")
    resp = transport.request("GET", f"{_X_API}/tweets/{post_id}", headers={
        "Authorization": f"Bearer {access.token}"}, params={"tweet.fields": "public_metrics,text"})
    status = _status(resp)
    if status in (402, 403) or (status == 401 and "client-not-enrolled" in str(getattr(resp, "text", ""))):
        return Stats("x", post_id, NO_STATS, url=url, note="X shares post numbers only on a paid X API plan.")
    if not _ok(resp):
        return _refused("x", post_id, status, url)
    data = _safe_json(resp).get("data") or {}
    pm = data.get("public_metrics") or {}
    if not pm:
        return Stats("x", post_id, NO_STATS, url=url, note="X did not return this post (deleted or protected?).")
    return Stats(
        "x", post_id, OK, views=_int(pm.get("impression_count")), likes=_int(pm.get("like_count")),
        comments=_int(pm.get("reply_count")), shares=_sum(_int(pm.get("retweet_count")), _int(pm.get("quote_count"))),
        saves=_int(pm.get("bookmark_count")), title=_title(data.get("text")), url=url,
    )


def _bluesky_uri(external_id: str, transport: Transport) -> tuple[str, int]:
    if external_id.startswith("at://"):
        return external_id, 0
    actor, _, rkey = external_id.partition("/")
    did = actor
    if not actor.startswith("did:"):
        resp = transport.request("GET", f"{_BSKY_PUBLIC}/com.atproto.identity.resolveHandle", params={"handle": actor})
        if not _ok(resp):
            return "", _status(resp)
        did = str(_safe_json(resp).get("did") or "")
    return (f"at://{did}/app.bsky.feed.post/{rkey}" if did and rkey else ""), 0


def bluesky(external_id: str, transport: Transport, *, url: str = "") -> Stats:
    uri, refused = _bluesky_uri(external_id, transport)
    if not uri:
        return _refused("bluesky", external_id, refused or 404, url)
    resp = transport.request("GET", f"{_BSKY_PUBLIC}/app.bsky.feed.getPosts", params={"uris": uri})
    if not _ok(resp):
        return _refused("bluesky", external_id, _status(resp), url)
    posts = _safe_json(resp).get("posts") or []
    post = posts[0] if posts and isinstance(posts[0], dict) else None
    if post is None:
        return Stats("bluesky", external_id, NO_STATS, url=url, note="Bluesky could not find this post.")
    return Stats(
        "bluesky", external_id, OK, likes=_int(post.get("likeCount")), comments=_int(post.get("replyCount")),
        shares=_sum(_int(post.get("repostCount")), _int(post.get("quoteCount"))),
        title=_title((post.get("record") or {}).get("text")), url=url,
        resolved_id=uri if uri != external_id else "",
    )


# --------------------------------------------------------------------------- #
# Titles for pasted links (public oEmbed)
# --------------------------------------------------------------------------- #
def public_title(platform: str, url: str, transport: Transport) -> str:
    """The post's caption/title from the platform's public oEmbed ('' when unavailable)."""
    try:
        if platform == "youtube":
            resp = transport.request("GET", _YT_OEMBED, params={"url": url, "format": "json"})
        elif platform == "tiktok":
            resp = transport.request("GET", f"{_TIKTOK_OEMBED}?url={quote(url, safe='')}")
        else:
            return ""
        return _title(_safe_json(resp).get("title")) if _ok(resp) else ""
    except Exception as exc:  # noqa: BLE001 - a title is optional
        logger.info(f"performance: oEmbed title failed for {platform}: {exc}")
        return ""


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def fetch(
    user_id: str, platform: str, external_id: str, access: Access, *,
    posted_on: date, duration_s: float = 0.0, url: str = "", id_kind: str = "id",
    transport: Transport | None = None,
) -> Stats:
    """Read one post's numbers. Never raises."""
    tx = transport or default_transport()
    plat = str(platform or "").strip().lower()
    try:
        if plat in ("tiktok", "youtube", "instagram"):
            return native(user_id, plat, external_id, access, tx, posted_on=posted_on,
                          duration_s=duration_s, url=url, id_kind=id_kind)
        if plat == "facebook":
            return facebook(external_id, access, tx, url=url)
        if plat == "threads":
            return threads(external_id, access, tx, url=url, id_kind=id_kind)
        if plat == "x":
            return x_post(external_id, access, tx, url=url)
        if plat == "bluesky":
            return bluesky(external_id, tx, url=url)
        note = NOT_OFFERED.get(plat, f"{label(plat)} numbers are not read yet.")
        return Stats(plat, external_id, NO_STATS, url=url, note=note)
    except Exception as exc:  # noqa: BLE001 - one post must never break the sweep
        logger.warning(f"performance: stats read failed for {plat}:{external_id}: {exc}")
        return Stats(plat, external_id, WAITING, url=url,
                     note=f"{label(plat)} could not be reached; the numbers will be checked again later.")


__all__ = [
    "Access",
    "NEEDS_ACCESS",
    "NO_ACCESS",
    "NO_STATS",
    "OK",
    "RATE_LIMITED",
    "Stats",
    "WAITING",
    "default_transport",
    "fetch",
    "from_post_metrics",
    "public_title",
    "youtube_public",
]
