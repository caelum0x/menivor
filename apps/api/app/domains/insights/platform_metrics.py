"""Post-publish performance pulls from the native platform APIs.

For a post Menivor published through a native connector (``domains/publishing``)
this module reads the numbers the platform reports for it, using the creator's
own OAuth connection:

* **YouTube** — YouTube Analytics API v2 ``reports`` (views, averageViewPercentage,
  likes, comments, shares; needs ``yt-analytics.readonly``) plus the audience
  retention curve (``audienceWatchRatio`` by ``elapsedVideoTimeRatio``), whose
  final point is the completion rate, falling back to the
  Data API v3 ``videos.list?part=statistics`` (views/likes/comments; needs
  ``youtube.readonly``) when analytics access was not granted.
* **TikTok** — Display API ``POST /v2/video/query/`` (view/like/comment/share
  counts; needs ``video.list``). TikTok does not expose watch time publicly, so
  retention is reported as unavailable rather than estimated.

Completion rate and rewatch rate are only set when a platform reports them;
otherwise they stay ``None`` (unknown), never ``0``. No platform API exposes a
per-post rewatch rate today, so it is always ``None`` from these pulls.
* **Instagram** — Graph API ``/{media-id}/insights`` (views, likes, comments,
  shares, saved, ig_reels_avg_watch_time; needs ``instagram_manage_insights``).

A missing permission or an API error never raises out of :func:`fetch_post_metrics`:
the result is marked ``available=False`` with a human-readable ``note`` so the UI
can tell the creator exactly what to reconnect. The only network seam is the same
injectable :class:`Transport` the publish connectors use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger

from app.domains.publishing.connectors.base import (
    RequestsTransport,
    Transport,
    _ok,
    _safe_json,
)

_YT_ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
_YT_DATA = "https://www.googleapis.com/youtube/v3/videos"
_TIKTOK_QUERY = "https://open.tiktokapis.com/v2/video/query/"
_TIKTOK_STATUS = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
_IG_GRAPH = "https://graph.facebook.com/v21.0"

# Scope hints surfaced to the creator when a pull is refused for permissions.
SCOPE_HINTS: dict[str, str] = {
    "youtube": "YouTube analytics access (yt-analytics.readonly or youtube.readonly)",
    "tiktok": "TikTok video.list permission",
    "instagram": "Instagram insights permission (instagram_manage_insights)",
}


@dataclass(frozen=True)
class PostMetrics:
    """Numbers one platform reported for one post."""

    platform: str
    external_id: str
    available: bool
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    avg_watch_frac: float | None = None
    completion_rate: float | None = None  # share of views that reached the end
    rewatch_rate: float | None = None     # share of views that replayed
    url: str = ""
    note: str = ""
    # HTTP status of the refused call (0 when it succeeded or never reached the
    # platform) so schedulers can back off on 429 and ask for scopes on 401/403.
    status: int = 0
    # Counters this platform does not report for this post (never shown as 0).
    unknown: tuple[str, ...] = ()

    def to_record(self) -> dict:
        return {
            "platform": self.platform,
            "external_id": self.external_id,
            "available": self.available,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "saves": self.saves,
            "avg_watch_frac": None if self.avg_watch_frac is None else round(self.avg_watch_frac, 4),
            "completion_rate": None if self.completion_rate is None else round(self.completion_rate, 4),
            "rewatch_rate": None if self.rewatch_rate is None else round(self.rewatch_rate, 4),
            "url": self.url,
            "note": self.note,
        }


def _int(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _unavailable(
    platform: str, external_id: str, note: str, url: str = "", *, status: int = 0
) -> PostMetrics:
    return PostMetrics(
        platform=platform, external_id=external_id, available=False, url=url, note=note, status=status
    )


def _permission_note(platform: str, status: int) -> str:
    if status in (401, 403):
        return f"Reconnect {platform} and grant {SCOPE_HINTS.get(platform, 'analytics access')}."
    if status == 429:
        return f"{platform} asked us to slow down; the numbers will be checked again later."
    return f"{platform} could not share this post's numbers right now; they will be checked again later."


def _fraction(value: Any) -> float | None:
    """A ratio clamped to [0, 1], or ``None`` when the platform sent nothing usable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number < 0:  # NaN or negative
        return None
    return min(1.0, number)


# --------------------------------------------------------------------------- #
# YouTube
# --------------------------------------------------------------------------- #
def _youtube_completion(
    headers: dict, video_id: str, published: date, transport: Transport
) -> float | None:
    """Completion rate from the audience retention curve, or ``None``.

    ``audienceWatchRatio`` at the last ``elapsedVideoTimeRatio`` bucket (1.0) is
    the share of views still watching at the end. Shorts loop, so the ratio can
    exceed 1; it is capped at 1. Any error or an empty curve reads as unknown.
    """
    resp = transport.request(
        "GET",
        _YT_ANALYTICS,
        headers=headers,
        params={
            "ids": "channel==MINE",
            "startDate": published.isoformat(),
            "endDate": datetime.now(timezone.utc).date().isoformat(),
            "metrics": "audienceWatchRatio",
            "dimensions": "elapsedVideoTimeRatio",
            "filters": f"video=={video_id}",
        },
    )
    if not _ok(resp):
        return None
    body = _safe_json(resp)
    names = [str(h.get("name")) for h in body.get("columnHeaders") or [] if isinstance(h, dict)]
    if "elapsedVideoTimeRatio" not in names or "audienceWatchRatio" not in names:
        return None
    at_idx, ratio_idx = names.index("elapsedVideoTimeRatio"), names.index("audienceWatchRatio")
    points: list[tuple[float, Any]] = []
    for row in body.get("rows") or []:
        if not isinstance(row, list) or len(row) <= max(at_idx, ratio_idx):
            continue
        try:
            points.append((float(row[at_idx]), row[ratio_idx]))
        except (TypeError, ValueError):
            continue
    if not points:
        return None
    return _fraction(max(points, key=lambda p: p[0])[1])


def _youtube(
    token: str, video_id: str, published: date, transport: Transport, url: str
) -> PostMetrics:
    headers = {"Authorization": f"Bearer {token}"}
    resp = transport.request(
        "GET",
        _YT_ANALYTICS,
        headers=headers,
        params={
            "ids": "channel==MINE",
            "startDate": published.isoformat(),
            "endDate": datetime.now(timezone.utc).date().isoformat(),
            "metrics": "views,averageViewPercentage,likes,comments,shares",
            "filters": f"video=={video_id}",
        },
    )
    body = _safe_json(resp) if _ok(resp) else {}
    rows = body.get("rows") or []
    # An empty Analytics answer (fresh video still lagging, or a video that is
    # not on this channel) is not "0 views": fall through to the Data API
    # counters instead of reporting zeros.
    if _ok(resp) and rows and isinstance(rows[0], list):
        headers_list = [str(h.get("name")) for h in body.get("columnHeaders") or [] if isinstance(h, dict)]
        row = rows[0]
        values = dict(zip(headers_list, row))
        avg_pct = values.get("averageViewPercentage")
        completion = _youtube_completion(headers, video_id, published, transport)
        return PostMetrics(
            platform="youtube",
            external_id=video_id,
            available=True,
            views=_int(values.get("views")),
            likes=_int(values.get("likes")),
            comments=_int(values.get("comments")),
            shares=_int(values.get("shares")),
            # Shorts loop, so averageViewPercentage can exceed 100; cap the fraction.
            avg_watch_frac=None if avg_pct is None else max(0.0, min(1.0, float(avg_pct) / 100.0)),
            completion_rate=completion,
            url=url,
            unknown=("saves",),
        )
    analytics_status = 0 if _ok(resp) else int(getattr(resp, "status_code", 0))

    resp = transport.request(
        "GET", _YT_DATA, headers=headers, params={"part": "statistics", "id": video_id}
    )
    if not _ok(resp):
        status = int(getattr(resp, "status_code", 0)) or analytics_status
        return _unavailable("youtube", video_id, _permission_note("youtube", status), url, status=status)
    items = _safe_json(resp).get("items") or []
    stats = (items[0] or {}).get("statistics", {}) if items and isinstance(items[0], dict) else {}
    if not stats:
        return _unavailable("youtube", video_id, "YouTube did not return this video (deleted or private?).", url)
    return PostMetrics(
        platform="youtube",
        external_id=video_id,
        available=True,
        views=_int(stats.get("viewCount")),
        likes=_int(stats.get("likeCount")),
        comments=_int(stats.get("commentCount")),
        url=url,
        note="Watch time needs YouTube Analytics access; ranked on views and engagement.",
        unknown=("shares", "saves"),
    )


# --------------------------------------------------------------------------- #
# TikTok
# --------------------------------------------------------------------------- #
def _tiktok_post_id(token: str, publish_id: str, transport: Transport) -> str:
    """Resolve a Content Posting ``publish_id`` to the public post (video) id."""
    resp = transport.request(
        "POST",
        _TIKTOK_STATUS,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        json={"publish_id": publish_id},
    )
    if not _ok(resp):
        return ""
    data = _safe_json(resp).get("data") or {}
    ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
    return str(ids[0]) if isinstance(ids, list) and ids else ""


def _tiktok(token: str, video_id: str, transport: Transport, url: str) -> PostMetrics:
    # A publish that completed on the first status poll keeps TikTok's
    # ``publish_id`` (``v_pub_…``) as its external id; the query API needs the
    # public post id, so resolve it first.
    if video_id.startswith("v_"):
        resolved = _tiktok_post_id(token, video_id, transport)
        if not resolved:
            return _unavailable(
                "tiktok", video_id,
                "TikTok has not made this post public yet (or it is private); no metrics to read.",
                url,
            )
        video_id = resolved
        url = url or f"https://www.tiktok.com/video/{resolved}"
    resp = transport.request(
        "POST",
        _TIKTOK_QUERY,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        params={"fields": "id,view_count,like_count,comment_count,share_count"},
        json={"filters": {"video_ids": [video_id]}},
    )
    if not _ok(resp):
        status = int(getattr(resp, "status_code", 0))
        return _unavailable("tiktok", video_id, _permission_note("tiktok", status), url, status=status)
    body = _safe_json(resp)
    err = body.get("error") or {}
    if str(err.get("code", "ok")).lower() not in ("ok", "", "none"):
        code = str(err.get("code"))
        note = (
            _permission_note("tiktok", 403)
            if "scope" in code or "permission" in code
            else f"TikTok refused the metrics request ({code})."
        )
        return _unavailable("tiktok", video_id, note, url, status=403 if "scope" in code else 0)
    videos = (body.get("data") or {}).get("videos") or []
    video = next((v for v in videos if isinstance(v, dict) and str(v.get("id")) == video_id), None)
    if video is None:
        return _unavailable("tiktok", video_id, "TikTok did not return this video (still processing or removed).", url)
    return PostMetrics(
        platform="tiktok",
        external_id=video_id,
        available=True,
        views=_int(video.get("view_count")),
        likes=_int(video.get("like_count")),
        comments=_int(video.get("comment_count")),
        shares=_int(video.get("share_count")),
        avg_watch_frac=None,
        url=url,
        note="TikTok does not share watch time through its API; ranked on views and engagement.",
        unknown=("saves",),
    )


# --------------------------------------------------------------------------- #
# Instagram
# --------------------------------------------------------------------------- #
def _ig_values(body: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for entry in body.get("data") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        value: Any = None
        values = entry.get("values")
        if isinstance(values, list) and values and isinstance(values[0], dict):
            value = values[0].get("value")
        elif isinstance(entry.get("total_value"), dict):
            value = entry["total_value"].get("value")
        try:
            out[name] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _instagram(
    token: str, media_id: str, duration_s: float, transport: Transport, url: str
) -> PostMetrics:
    base_metrics = "reach,likes,comments,shares,saved,ig_reels_avg_watch_time"
    values: dict[str, float] = {}
    last_status = 0
    # ``views`` replaced ``plays`` for Reels in 2025; try the current metric first.
    for view_metric in ("views", "plays"):
        resp = transport.request(
            "GET",
            f"{_IG_GRAPH}/{media_id}/insights",
            params={"metric": f"{view_metric},{base_metrics}", "access_token": token},
        )
        last_status = int(getattr(resp, "status_code", 0))
        if _ok(resp):
            values = _ig_values(_safe_json(resp))
            values["views"] = values.get(view_metric, 0.0)
            break
        if last_status in (401, 403):
            break
    if not values:
        return _unavailable("instagram", media_id, _permission_note("instagram", last_status), url, status=last_status)
    avg_ms = values.get("ig_reels_avg_watch_time")
    avg_frac = None
    if avg_ms is not None and duration_s > 0:
        avg_frac = max(0.0, min(1.0, (avg_ms / 1000.0) / duration_s))
    return PostMetrics(
        platform="instagram",
        external_id=media_id,
        available=True,
        views=_int(values.get("views")),
        likes=_int(values.get("likes")),
        comments=_int(values.get("comments")),
        shares=_int(values.get("shares")),
        saves=_int(values.get("saved")),
        avg_watch_frac=avg_frac,
        url=url,
        note="" if avg_frac is not None else "Instagram did not report average watch time for this reel.",
    )


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def normalize_platform(platform: str) -> str:
    plat = str(platform or "").strip().lower()
    return "youtube" if plat in ("youtube_shorts", "yt", "youtube") else plat


def _token_for(user_id: str, platform: str) -> tuple[str, str]:
    """Return the creator's fresh (access_token, external_account_id) or ('', '')."""
    from app.models.db.base import get_session
    from app.services import oauth_connect

    with get_session() as session:
        account = oauth_connect.refresh_if_needed(session, user_id, platform)
        if account is None:
            return "", ""
        tokens = oauth_connect._decrypt_account(account)  # noqa: SLF001 - same pattern as native_service
        return tokens.access_token, (tokens.external_account_id or "")


def fetch_post_metrics(
    user_id: str,
    platform: str,
    external_id: str,
    *,
    published_on: date,
    duration_s: float = 0.0,
    url: str = "",
    transport: Transport | None = None,
    token: str | None = None,
) -> PostMetrics:
    """Pull one post's metrics through the creator's own connection. Never raises."""
    plat = normalize_platform(platform)
    ext = str(external_id or "").strip()
    if not ext:
        return _unavailable(plat, ext, "The platform never returned a post id for this publish.", url)
    try:
        access = token
        if access is None:
            access, _ = _token_for(user_id, plat)
        if not access:
            return _unavailable(plat, ext, f"No connected {plat} account — reconnect it under Connections.", url)
        tx = transport or RequestsTransport(timeout_s=30.0)
        if plat == "youtube":
            return _youtube(access, ext, published_on, tx, url)
        if plat == "tiktok":
            return _tiktok(access, ext, tx, url)
        if plat == "instagram":
            return _instagram(access, ext, duration_s, tx, url)
        return _unavailable(plat, ext, f"Metrics are not supported for {plat}.", url)
    except Exception as exc:  # noqa: BLE001 - a metrics pull must never break the loop
        logger.warning(f"metrics pull failed for {plat}:{ext}: {exc}")
        return _unavailable(plat, ext, "The platform could not be reached; will retry on the next check.", url)


__all__ = ["PostMetrics", "SCOPE_HINTS", "fetch_post_metrics", "normalize_platform"]
