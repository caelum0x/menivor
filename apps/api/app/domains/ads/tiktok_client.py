"""TikTok Business API (v1.3) client for Menivor paid ads.

Structure per launch mirrors Meta: one TRAFFIC campaign (no campaign budget) ->
one ad group per creative with a daily budget and the audience -> one
single-video ad per ad group, posted under a custom identity created at connect
time. Requires Menivor's TikTok for Business developer app to be approved for
Ads Management + Reporting scopes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.domains.ads.config import PlatformConfig
from app.domains.ads.platforms import (
    AccountRef, AdCreativeInput, AdsApiError, AdStats, Audience, TokenGrant, VideoState, from_minor, new_http,
    to_minor,
)

BASE = "https://business-api.tiktok.com/open_api/v1.3"
AUTH_URL = "https://business-api.tiktok.com/portal/auth"

# GeoNames country ids, which TikTok uses as ``location_ids``. Callers may also
# pass a raw numeric location id.
COUNTRY_LOCATION_IDS = {
    "US": "6252001", "GB": "2635167", "CA": "6251999", "AU": "2077456", "DE": "2921044", "FR": "3017382",
    "TR": "298795", "ES": "2510769", "IT": "3175395", "NL": "2750405", "BR": "3469034", "MX": "3996063",
    "IN": "1269750", "JP": "1861060",
}
_AGE_BANDS = ((18, 24, "AGE_18_24"), (25, 34, "AGE_25_34"), (35, 44, "AGE_35_44"), (45, 54, "AGE_45_54"), (55, 100, "AGE_55_100"))
_GENDER = {"male": "GENDER_MALE", "female": "GENDER_FEMALE"}
_TOKEN_ERRORS = {40001, 40100, 40102, 40104, 40105}


def age_groups(age_min: int, age_max: int) -> list[str]:
    return [band for lo, hi, band in _AGE_BANDS if hi >= age_min and lo <= age_max]


def location_ids(countries: tuple[str, ...]) -> list[str]:
    out = []
    for c in countries:
        if c.isdigit():
            out.append(c)
        elif c.upper() in COUNTRY_LOCATION_IDS:
            out.append(COUNTRY_LOCATION_IDS[c.upper()])
        else:
            raise AdsApiError("tiktok", f"TikTok targeting does not know country {c!r}; use a TikTok location id", status_code=400)
    return out


class TikTokAdsClient:
    platform = "tiktok"

    def __init__(self, cfg: PlatformConfig, http: httpx.Client | None = None) -> None:
        self._cfg = cfg
        self._http = http or new_http()

    # ------------------------------------------------------------------ transport
    def _call(self, method: str, path: str, token: str | None, payload: dict[str, Any] | None = None) -> Any:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Access-Token"] = token
        url = f"{BASE}/{path.strip('/')}/"
        try:
            if method == "GET":
                params = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in (payload or {}).items()}
                resp = self._http.get(url, params=params, headers=headers)
            else:
                resp = self._http.post(url, json=payload or {}, headers=headers)
        except httpx.HTTPError as exc:
            raise AdsApiError("tiktok", f"TikTok API unreachable: {exc.__class__.__name__}") from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        code = int(body.get("code", -1)) if isinstance(body, dict) else -1
        if resp.status_code >= 400 or code != 0:
            message = (body or {}).get("message") or f"HTTP {resp.status_code}"
            status = 401 if code in _TOKEN_ERRORS else 502
            raise AdsApiError("tiktok", f"TikTok: {message}", status_code=status, code=str(code))
        return body.get("data")

    # ---------------------------------------------------------------------- oauth
    def authorize_url(self, state: str) -> str:
        query = urlencode({"app_id": self._cfg.app_id, "state": state, "redirect_uri": self._cfg.redirect_uri})
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, code: str) -> TokenGrant:
        data = self._call("POST", "oauth2/access_token", None, {
            "app_id": self._cfg.app_id, "secret": self._cfg.app_secret, "auth_code": code,
        }) or {}
        token = str(data.get("access_token") or "")
        if not token:
            raise AdsApiError("tiktok", "TikTok did not return an access token", status_code=400)
        scopes = ",".join(str(s) for s in data.get("scope") or [])
        # TikTok Business long-term tokens do not expire unless revoked.
        return TokenGrant(access_token=token, expires_at=None, scopes=scopes,
                          account_ids=tuple(str(a) for a in data.get("advertiser_ids") or []))

    def list_accounts(self, token: str) -> list[dict]:
        data = self._call("GET", "oauth2/advertiser/get", token, {"app_id": self._cfg.app_id, "secret": self._cfg.app_secret}) or {}
        ids = [str(a.get("advertiser_id")) for a in data.get("list") or []]
        names = {str(a.get("advertiser_id")): str(a.get("advertiser_name") or a.get("advertiser_id")) for a in data.get("list") or []}
        currencies: dict[str, str] = {}
        if ids:
            info = self._call("GET", "advertiser/info", token, {"advertiser_ids": ids, "fields": ["advertiser_id", "currency", "status"]}) or {}
            for row in info.get("list") or []:
                currencies[str(row.get("advertiser_id"))] = str(row.get("currency") or "USD")
        return [{"id": i, "name": names[i], "currency": currencies.get(i, "USD"), "active": True} for i in ids]

    def list_identities(self, token: str, account_id: str) -> list[dict]:
        data = self._call("GET", "identity/get", token, {"advertiser_id": account_id, "identity_type": "CUSTOMIZED_USER"}) or {}
        return [{"id": str(i.get("identity_id")), "name": str(i.get("display_name") or i.get("identity_id"))}
                for i in data.get("identity_list") or []]

    def create_identity(self, token: str, account_id: str, display_name: str) -> str:
        data = self._call("POST", "identity/create", token, {"advertiser_id": account_id, "display_name": display_name[:40]}) or {}
        return str(data.get("identity_id") or "")

    # ------------------------------------------------------------------ structure
    def create_campaign(self, token: str, acct: AccountRef, name: str) -> str:
        data = self._call("POST", "campaign/create", token, {
            "advertiser_id": acct.account_id, "campaign_name": name[:512], "objective_type": "TRAFFIC",
            "budget_mode": "BUDGET_MODE_INFINITE", "operation_status": "DISABLE",
        })
        return str(data["campaign_id"])

    def create_ad_group(self, token: str, acct: AccountRef, campaign_id: str, name: str, budget_minor: int,
                        audience: Audience) -> str:
        payload: dict[str, Any] = {
            "advertiser_id": acct.account_id, "campaign_id": campaign_id, "adgroup_name": name[:512],
            "promotion_type": "WEBSITE", "placement_type": "PLACEMENT_TYPE_NORMAL", "placements": ["PLACEMENT_TIKTOK"],
            "location_ids": location_ids(audience.countries), "age_groups": age_groups(audience.age_min, audience.age_max),
            "gender": _GENDER.get(audience.gender, "GENDER_UNLIMITED"),
            "budget_mode": "BUDGET_MODE_DAY", "budget": from_minor(budget_minor, acct.currency),
            "schedule_type": "SCHEDULE_FROM_NOW",
            "schedule_start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "optimization_goal": "CLICK", "billing_event": "CPC", "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH", "operation_status": "ENABLE",
        }
        data = self._call("POST", "adgroup/create", token, payload)
        return str(data["adgroup_id"])

    def upload_video(self, token: str, acct: AccountRef, video_url: str, name: str) -> str:
        data = self._call("POST", "file/video/ad/upload", token, {
            "advertiser_id": acct.account_id, "upload_type": "UPLOAD_BY_URL", "video_url": video_url, "file_name": name[:100],
        })
        row = data[0] if isinstance(data, list) and data else data or {}
        return str(row.get("video_id") or "")

    def video_state(self, token: str, acct: AccountRef, video_id: str) -> VideoState:
        data = self._call("GET", "file/video/ad/info", token, {"advertiser_id": acct.account_id, "video_ids": [video_id]}) or {}
        rows = data.get("list") or []
        if not rows:
            return VideoState(ready=False, detail="processing")
        row = rows[0]
        return VideoState(ready=bool(row.get("displayable", True)), thumbnail_url=str(row.get("video_cover_url") or ""),
                          detail="ready")

    def _upload_image(self, token: str, acct: AccountRef, image_url: str) -> str:
        data = self._call("POST", "file/image/ad/upload", token, {
            "advertiser_id": acct.account_id, "upload_type": "UPLOAD_BY_URL", "image_url": image_url,
        }) or {}
        return str(data.get("image_id") or "")

    def create_ad(self, token: str, acct: AccountRef, ad_group_id: str, creative: AdCreativeInput) -> dict:
        if not acct.identity_id:
            raise AdsApiError("tiktok", "Create a TikTok ad identity for this advertiser before launching", status_code=400)
        if not creative.thumbnail_url:
            raise AdsApiError("tiktok", "TikTok needs a cover image; the video has no poster yet", status_code=409)
        image_id = self._upload_image(token, acct, creative.thumbnail_url)
        data = self._call("POST", "ad/create", token, {
            "advertiser_id": acct.account_id, "adgroup_id": ad_group_id,
            "creatives": [{
                "ad_name": creative.name[:512], "identity_type": "CUSTOMIZED_USER", "identity_id": acct.identity_id,
                "ad_format": "SINGLE_VIDEO", "video_id": creative.video_id, "image_ids": [image_id],
                "ad_text": creative.primary_text[:100], "call_to_action": creative.cta,
                "landing_page_url": creative.landing_url,
            }],
        }) or {}
        ad_ids = data.get("ad_ids") or []
        if not ad_ids:
            raise AdsApiError("tiktok", "TikTok did not return an ad id")
        return {"ad_id": str(ad_ids[0]), "creative_id": image_id}

    # ---------------------------------------------------------------- operations
    def set_campaign_status(self, token: str, acct: AccountRef, campaign_id: str, active: bool) -> None:
        self._call("POST", "campaign/status/update", token, {
            "advertiser_id": acct.account_id, "campaign_ids": [campaign_id], "operation_status": "ENABLE" if active else "DISABLE",
        })

    def set_ad_group_status(self, token: str, acct: AccountRef, ad_group_id: str, active: bool) -> None:
        self._call("POST", "adgroup/status/update", token, {
            "advertiser_id": acct.account_id, "adgroup_ids": [ad_group_id], "operation_status": "ENABLE" if active else "DISABLE",
        })

    def set_ad_group_budget(self, token: str, acct: AccountRef, ad_group_id: str, budget_minor: int) -> None:
        self._call("POST", "adgroup/budget/update", token, {
            "advertiser_id": acct.account_id, "budget": [{"adgroup_id": ad_group_id, "budget": from_minor(budget_minor, acct.currency)}],
        })

    def campaign_status(self, token: str, acct: AccountRef, campaign_id: str) -> str:
        data = self._call("GET", "campaign/get", token, {
            "advertiser_id": acct.account_id, "filtering": {"campaign_ids": [campaign_id]},
        }) or {}
        rows = data.get("list") or []
        return str(rows[0].get("operation_status") or "").lower() if rows else ""

    def campaign_stats(self, token: str, acct: AccountRef, campaign_id: str) -> list[AdStats]:
        data = self._call("GET", "report/integrated/get", token, {
            "advertiser_id": acct.account_id, "report_type": "BASIC", "data_level": "AUCTION_AD",
            "dimensions": ["ad_id"], "metrics": ["spend", "impressions", "clicks", "conversion"],
            "filtering": [{"field_name": "campaign_ids", "filter_type": "IN", "filter_value": json.dumps([campaign_id])}],
            "query_lifetime": True, "page_size": 1000,
        }) or {}
        out = []
        for row in data.get("list") or []:
            metrics = row.get("metrics") or {}
            conv = metrics.get("conversion")
            out.append(AdStats(
                ad_id=str((row.get("dimensions") or {}).get("ad_id") or ""),
                spend_minor=to_minor(metrics.get("spend"), acct.currency),
                impressions=int(float(metrics.get("impressions") or 0)),
                clicks=int(float(metrics.get("clicks") or 0)),
                leads=int(float(conv)) if conv not in (None, "", "-") else None,
            ))
        return out


__all__ = ["COUNTRY_LOCATION_IDS", "TikTokAdsClient", "age_groups", "location_ids"]
