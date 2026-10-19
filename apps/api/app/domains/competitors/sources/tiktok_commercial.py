"""TikTok Commercial Content API (official, research access): ad library query.

Access: apply for the Commercial Content API at developers.tiktok.com (approval per
app); the owner sets ``TIKTOK_COMMERCIAL_CLIENT_KEY`` / ``TIKTOK_COMMERCIAL_CLIENT_SECRET``.
A client-credentials token (``POST /v2/oauth/token/``) authorises
``POST /v2/research/adlib/ad/query/?fields=...`` with ``filters`` (advertiser
business ids, published-date range, country) or a ``search_term``. Ads shown in the
EU are covered. TikTok Creative Center has no official API and is not used.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from app.domains.competitors.sources.base import (
    SourceError,
    SourceNotConnected,
    TrackedAd,
    first_text,
    https_only,
    parse_time,
)

SOURCE = "tiktok"
KEY_ENV = "TIKTOK_COMMERCIAL_CLIENT_KEY"
SECRET_ENV = "TIKTOK_COMMERCIAL_CLIENT_SECRET"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
QUERY_URL = "https://open.tiktokapis.com/v2/research/adlib/ad/query/"
FIELDS = "ad.id,ad.first_shown_date,ad.last_shown_date,ad.status,ad.videos,ad.image_urls,advertiser.business_id," \
         "advertiser.business_name"
LOOKBACK_DAYS = 365
MAX_COUNT = 50
MAX_PAGES = 4
SETUP_STEP = ("TikTok ad library is not connected. The owner applies for the TikTok Commercial Content API and "
              "sets TIKTOK_COMMERCIAL_CLIENT_KEY and TIKTOK_COMMERCIAL_CLIENT_SECRET.")


def configured(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return bool(str(source.get(KEY_ENV) or "").strip() and str(source.get(SECRET_ENV) or "").strip())


def _token(transport: Any, env: dict[str, str]) -> str:
    try:
        resp = transport.request("POST", TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"},
                                 data={"client_key": env[KEY_ENV], "client_secret": env[SECRET_ENV],
                                       "grant_type": "client_credentials"})
        body = resp.json() or {}
    except Exception as exc:  # noqa: BLE001 - network boundary
        raise SourceError(SOURCE, f"TikTok is unreachable ({type(exc).__name__}).") from exc
    token = str(body.get("access_token") or "")
    if resp.status_code >= 400 or not token:
        raise SourceError(SOURCE, "TikTok refused the Commercial Content API keys; the owner must check them.", 409)
    return token


def _to_ad(item: dict[str, Any]) -> TrackedAd | None:
    ad = item.get("ad") or {}
    advertiser = item.get("advertiser") or {}
    ad_id = str(ad.get("id") or "").strip()
    if not ad_id:
        return None
    videos = ad.get("videos") or []
    video = videos[0] if videos and isinstance(videos[0], dict) else {}
    status = str(ad.get("status") or "").lower()
    stopped = parse_time(ad.get("last_shown_date")) if status not in ("active", "") else None
    images = ad.get("image_urls") or []
    return TrackedAd(
        source=SOURCE, external_id=ad_id[:64], advertiser=first_text(advertiser.get("business_name"), 300),
        body="", title="", page_url=f"https://library.tiktok.com/ads/detail/?ad_id={ad_id}",
        media_url=https_only(video.get("url")),
        thumbnail_url=https_only(video.get("cover_image_url") or (images[0] if images else "")),
        platforms=("tiktok",), languages=(), started_at=parse_time(ad.get("first_shown_date")), stopped_at=stopped,
        raw={"business_id": str(advertiser.get("business_id") or ""), "status": status},
    )


def fetch(transport: Any, *, advertiser_ids: list[str], search_terms: str, countries: list[str],
          env: dict[str, str] | None = None, today: date | None = None) -> list[TrackedAd]:
    source = dict(os.environ if env is None else env)
    if not configured(source):
        raise SourceNotConnected(SOURCE, SETUP_STEP)
    ids = [a for a in (str(x).strip() for x in advertiser_ids) if a.isdigit()][:10]
    if not ids and not search_terms.strip():
        return []
    end = today or date.today()
    filters: dict[str, Any] = {"ad_published_date_range": {
        "min": (end - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d"), "max": end.strftime("%Y%m%d")}}
    if ids:
        filters["advertiser_business_ids"] = [int(a) for a in ids]
    if countries:
        filters["country_code"] = str(countries[0]).upper()
    body: dict[str, Any] = {"filters": filters, "max_count": MAX_COUNT}
    if not ids:
        body["search_term"] = search_terms.strip()[:50]
    headers = {"Authorization": f"Bearer {_token(transport, source)}", "Content-Type": "application/json"}
    out: list[TrackedAd] = []
    for _ in range(MAX_PAGES):
        try:
            resp = transport.request("POST", QUERY_URL, headers=headers, params={"fields": FIELDS}, json=body)
            data = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            raise SourceError(SOURCE, f"TikTok ad library is unreachable ({type(exc).__name__}).") from exc
        error = data.get("error") or {}
        if resp.status_code >= 400 or (error.get("code") not in (None, "", "ok")):
            raise SourceError(SOURCE, f"TikTok ad library error: {str(error.get('message') or resp.status_code)[:160]}")
        payload = data.get("data") or {}
        out.extend(ad for ad in (_to_ad(i) for i in payload.get("ads") or []) if ad is not None)
        if not payload.get("has_more") or not payload.get("search_id"):
            break
        body = {**body, "search_id": payload["search_id"]}
    return out


__all__ = ["KEY_ENV", "SECRET_ENV", "SOURCE", "configured", "fetch"]
