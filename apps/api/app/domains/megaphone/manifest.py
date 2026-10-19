"""The public Megaphone manifest every product site reads.

Contract (``https://media.menivor.com/megaphone/manifest.json`` and one file
per product, ``/megaphone/<product>.json``, same shape)::

    {
      "version": 1,
      "updated_at": "2026-10-08T03:00:00Z",
      "videos": [
        {
          "id": "bidstage-de-cpv45-2026w41",
          "product": "bidstage",              # bidstage | mail | oxhan | menivor
          "title": "...", "description": "...",
          "video_url": "https://media.menivor.com/megaphone/bidstage/<id>.mp4",
          "poster_url": "https://media.menivor.com/megaphone/bidstage/<id>.jpg",
          "duration_s": 31.4, "width": 1080, "height": 1920,
          "upload_date": "2026-10-08T03:00:00Z",
          "landing_url": "https://bidstage.app/tenders/de/cpv-45000000?utm_source=menivor&...",
          "page_path": "/tenders/de/cpv-45000000",
          "language": "en",
          "transcript": "...",
          "made_with": "Menivor",
          "made_with_url": "https://menivor.com/made-with-menivor",
          "dubs": [{"language": "es", "video_url": "..."}]
        }
      ]
    }

Newest first. Sites render ``<video>`` + schema.org ``VideoObject`` from it
and list it in a video sitemap; nothing in it is private.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from app.domains.megaphone.briefs import MENIVOR_GALLERY_URL, Brief

VERSION = 1
#: Videos kept per product (older ones drop out of the feed; files stay in R2).
KEEP_PER_PRODUCT = 12
PRODUCTS: tuple[str, ...] = ("bidstage", "mail", "oxhan", "menivor")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty() -> dict[str, Any]:
    return {"version": VERSION, "updated_at": None, "videos": []}


def entry(
    brief: Brief,
    *,
    video_url: str,
    poster_url: str,
    duration_s: float,
    uploaded_at: datetime,
    width: int = 1080,
    height: int = 1920,
    dubs: Iterable[Mapping[str, str]] = (),
) -> dict[str, Any]:
    return {
        "id": brief.id,
        "product": brief.product,
        "title": brief.title,
        "description": brief.description,
        "video_url": video_url,
        "poster_url": poster_url,
        "duration_s": round(float(duration_s), 2),
        "width": int(width),
        "height": int(height),
        "upload_date": iso(uploaded_at),
        "landing_url": brief.landing_url,
        "page_path": brief.page_path,
        "language": brief.language,
        "transcript": brief.script,
        "made_with": "Menivor",
        "made_with_url": MENIVOR_GALLERY_URL,
        "dubs": [dict(d) for d in dubs],
    }


def upsert(manifest: Mapping[str, Any] | None, items: Iterable[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    """New manifest with ``items`` added (same id replaces), newest first, pruned per product."""
    current = [dict(v) for v in (manifest or {}).get("videos") or [] if isinstance(v, Mapping) and v.get("id")]
    fresh = [dict(i) for i in items]
    fresh_ids = {i["id"] for i in fresh}
    merged = fresh + [v for v in current if v["id"] not in fresh_ids]
    merged.sort(key=lambda v: (str(v.get("upload_date") or ""), v["id"]), reverse=True)
    counts: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for video in merged:
        product = str(video.get("product") or "")
        if product not in PRODUCTS:
            continue
        counts[product] = counts.get(product, 0) + 1
        if counts[product] <= KEEP_PER_PRODUCT:
            kept.append(video)
    return {"version": VERSION, "updated_at": iso(now), "videos": kept}


def for_product(manifest: Mapping[str, Any], product: str) -> dict[str, Any]:
    return {
        "version": VERSION,
        "updated_at": manifest.get("updated_at"),
        "videos": [v for v in manifest.get("videos") or [] if v.get("product") == product],
    }


def recent_ids(manifest: Mapping[str, Any], product: str, limit: int = 8) -> set[str]:
    """Pair ids (week suffix stripped) of the product's latest videos, for rotation."""
    out: set[str] = set()
    for video in (manifest.get("videos") or [])[:200]:
        if video.get("product") != product:
            continue
        vid = str(video.get("id") or "")
        out.add(vid.rsplit("-", 1)[0] if "-20" in vid else vid)
        if len(out) >= limit:
            break
    return out
