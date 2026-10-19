"""Meta Ad Library API (official): ``GET https://graph.facebook.com/<version>/ads_archive``.

Access: an identity-confirmed Meta account and an app with the Ad Library API
(developers.facebook.com, "Ad Library API"); the owner puts its user access token
in ``META_AD_LIBRARY_TOKEN``. Non-political ads are returned for ads delivered in
the EU (Digital Services Act transparency), so ``ad_reached_countries`` defaults to
EU countries. Queries are by Facebook page id (``search_page_ids``, up to 10) or
keywords (``search_terms``); ``ad_active_status=ALL`` so stopped ads keep their
end date (that is the longevity signal). The API returns no media file; the ad's
public Ad Library page is ``https://www.facebook.com/ads/library/?id=<id>``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from app.domains.competitors.sources.base import (
    SourceError,
    SourceNotConnected,
    TrackedAd,
    first_text,
    https_only,
    parse_time,
)

SOURCE = "meta"
TOKEN_ENV = "META_AD_LIBRARY_TOKEN"
VERSION_ENV = "META_AD_LIBRARY_API_VERSION"
DEFAULT_VERSION = "v23.0"
BASE = "https://graph.facebook.com"
FIELDS = ("id,page_id,page_name,ad_creation_time,ad_delivery_start_time,ad_delivery_stop_time,"
          "ad_creative_bodies,ad_creative_link_titles,ad_snapshot_url,publisher_platforms,languages")
DEFAULT_COUNTRIES = ("DE", "FR", "NL", "ES", "IT", "IE", "SE", "PL")
MAX_PAGE_IDS = 10
PAGE_LIMIT = 100
MAX_PAGES = 5
LIBRARY_PAGE = "https://www.facebook.com/ads/library/?id={id}"
SETUP_STEP = ("Meta Ad Library is not connected. The owner sets META_AD_LIBRARY_TOKEN (an identity-confirmed "
              "Meta account with Ad Library API access).")


def configured(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return bool(str(source.get(TOKEN_ENV) or "").strip())


def _version(env: dict[str, str] | None) -> str:
    source = os.environ if env is None else env
    return str(source.get(VERSION_ENV) or DEFAULT_VERSION).strip()


def _to_ad(item: dict[str, Any]) -> TrackedAd | None:
    ad_id = str(item.get("id") or "").strip()
    if not ad_id.isdigit():
        return None
    return TrackedAd(
        source=SOURCE, external_id=ad_id, advertiser=first_text(item.get("page_name"), 300),
        body=first_text(item.get("ad_creative_bodies"), 4000), title=first_text(item.get("ad_creative_link_titles"), 500),
        page_url=LIBRARY_PAGE.format(id=ad_id), media_url="", thumbnail_url="",
        platforms=tuple(str(p).lower() for p in item.get("publisher_platforms") or [])[:8],
        languages=tuple(str(lang) for lang in item.get("languages") or [])[:8],
        started_at=parse_time(item.get("ad_delivery_start_time") or item.get("ad_creation_time")),
        stopped_at=parse_time(item.get("ad_delivery_stop_time")),
        raw={"page_id": str(item.get("page_id") or ""), "snapshot_url": https_only(item.get("ad_snapshot_url"))},
    )


def fetch(transport: Any, *, page_ids: list[str], search_terms: str, countries: list[str],
          env: dict[str, str] | None = None) -> list[TrackedAd]:
    source = os.environ if env is None else env
    token = str(source.get(TOKEN_ENV) or "").strip()
    if not token:
        raise SourceNotConnected(SOURCE, SETUP_STEP)
    ids = [p for p in (str(x).strip() for x in page_ids) if p.isdigit()][:MAX_PAGE_IDS]
    if not ids and not search_terms.strip():
        return []
    params: dict[str, Any] = {
        "access_token": token, "ad_type": "ALL", "ad_active_status": "ALL", "fields": FIELDS, "limit": PAGE_LIMIT,
        "ad_reached_countries": json.dumps([c.upper() for c in (countries or DEFAULT_COUNTRIES)][:20]),
    }
    if ids:
        params["search_page_ids"] = json.dumps(ids)
    else:
        params["search_terms"] = search_terms.strip()[:100]
    url = f"{BASE}/{_version(env)}/ads_archive"
    out: list[TrackedAd] = []
    for _ in range(MAX_PAGES):
        try:
            resp = transport.request("GET", url, params=params)
        except Exception as exc:  # noqa: BLE001 - network boundary
            raise SourceError(SOURCE, f"Meta Ad Library is unreachable ({type(exc).__name__}).") from exc
        try:
            body = resp.json() or {}
        except ValueError:
            body = {}
        if resp.status_code in (401, 403) or (body.get("error") or {}).get("code") in (190, 10):
            raise SourceError(SOURCE, "Meta refused the Ad Library token; the owner must renew it.", 409)
        if resp.status_code >= 400:
            message = str((body.get("error") or {}).get("message") or "")[:160]
            raise SourceError(SOURCE, f"Meta Ad Library error {resp.status_code}: {message}".strip(": "))
        out.extend(ad for ad in (_to_ad(i) for i in body.get("data") or []) if ad is not None)
        after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
        if not (body.get("paging") or {}).get("next") or not after:
            break
        params = {**params, "after": after}
    return out


__all__ = ["DEFAULT_COUNTRIES", "SOURCE", "TOKEN_ENV", "configured", "fetch"]
