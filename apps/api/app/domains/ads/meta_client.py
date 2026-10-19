"""Meta Marketing API client (Graph API) for Menivor paid ads.

Structure per launch: one OUTCOME_TRAFFIC campaign (link clicks to the product
page; ad-set budgets so each creative can be funded separately) -> one ad set per creative
with its own daily budget and the audience -> one video ad per ad set.

Requires Menivor's Meta app to hold ``ads_management`` / ``ads_read`` /
``pages_show_list`` / ``pages_read_engagement`` / ``business_management``
through Advanced Access (app review). Every request sends ``appsecret_proof``.
Leads are read from the pixel/lead actions Meta reports on each ad; Menivor does
not create pixels or lead forms.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.domains.ads.config import PlatformConfig, meta_api_version
from app.domains.ads.platforms import (
    AccountRef, AdCreativeInput, AdsApiError, AdStats, Audience, TokenGrant, VideoState, new_http, to_minor,
)

SCOPES = "ads_management,ads_read,business_management,pages_show_list,pages_read_engagement"
_LEAD_ACTIONS = ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")
_GENDER = {"male": [1], "female": [2]}


class MetaAdsClient:
    platform = "meta"

    def __init__(self, cfg: PlatformConfig, http: httpx.Client | None = None) -> None:
        self._cfg = cfg
        self._http = http or new_http()
        self._base = f"https://graph.facebook.com/{meta_api_version()}"

    # ------------------------------------------------------------------ transport
    def _proof(self, token: str) -> str:
        return hmac.new(self._cfg.app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()

    def _call(self, method: str, path: str, token: str | None, params: dict[str, Any] | None = None) -> dict:
        data: dict[str, Any] = {}
        for key, value in (params or {}).items():
            data[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            data["appsecret_proof"] = self._proof(token)
        url = f"{self._base}/{path.lstrip('/')}"
        try:
            if method == "GET":
                resp = self._http.get(url, params=data, headers=headers)
            else:
                resp = self._http.post(url, data=data, headers=headers)
        except httpx.HTTPError as exc:
            raise AdsApiError("meta", f"Meta API unreachable: {exc.__class__.__name__}") from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            err = (body or {}).get("error") or {}
            message = err.get("error_user_msg") or err.get("message") or f"HTTP {resp.status_code}"
            status = 401 if err.get("code") in (190, 102) else 403 if err.get("code") in (10, 200, 294) else 502
            raise AdsApiError("meta", f"Meta: {message}", status_code=status, code=str(err.get("code", "")))
        return body if isinstance(body, dict) else {"data": body}

    # ---------------------------------------------------------------------- oauth
    def authorize_url(self, state: str) -> str:
        query = urlencode({
            "client_id": self._cfg.app_id, "redirect_uri": self._cfg.redirect_uri,
            "state": state, "scope": SCOPES, "response_type": "code",
        })
        return f"https://www.facebook.com/{meta_api_version()}/dialog/oauth?{query}"

    def exchange_code(self, code: str) -> TokenGrant:
        short = self._call("GET", "oauth/access_token", None, {
            "client_id": self._cfg.app_id, "client_secret": self._cfg.app_secret,
            "redirect_uri": self._cfg.redirect_uri, "code": code,
        })
        long = self._call("GET", "oauth/access_token", None, {
            "grant_type": "fb_exchange_token", "client_id": self._cfg.app_id,
            "client_secret": self._cfg.app_secret, "fb_exchange_token": short.get("access_token", ""),
        })
        token = str(long.get("access_token") or short.get("access_token") or "")
        if not token:
            raise AdsApiError("meta", "Meta did not return an access token", status_code=400)
        expires_in = int(long.get("expires_in") or 0)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None
        return TokenGrant(access_token=token, expires_at=expires_at, scopes=SCOPES)

    def list_accounts(self, token: str) -> list[dict]:
        body = self._call("GET", "me/adaccounts", token, {"fields": "id,account_id,name,currency,account_status", "limit": 100})
        return [
            {"id": str(a.get("id")), "name": str(a.get("name") or a.get("account_id")),
             "currency": str(a.get("currency") or "USD"), "active": a.get("account_status") == 1}
            for a in body.get("data") or []
        ]

    def list_identities(self, token: str, account_id: str) -> list[dict]:
        body = self._call("GET", "me/accounts", token, {"fields": "id,name", "limit": 100})
        return [{"id": str(p.get("id")), "name": str(p.get("name") or p.get("id"))} for p in body.get("data") or []]

    # ------------------------------------------------------------------ structure
    def create_campaign(self, token: str, acct: AccountRef, name: str) -> str:
        body = self._call("POST", f"{acct.account_id}/campaigns", token, {
            "name": name[:200], "objective": "OUTCOME_TRAFFIC",
            "status": "PAUSED", "special_ad_categories": [], "is_adset_budget_sharing_enabled": "false",
        })
        return str(body["id"])

    def create_ad_group(self, token: str, acct: AccountRef, campaign_id: str, name: str, budget_minor: int,
                        audience: Audience) -> str:
        targeting: dict[str, Any] = {
            "geo_locations": {"countries": list(audience.countries)},
            "age_min": max(18, audience.age_min), "age_max": min(65, audience.age_max),
        }
        if audience.gender in _GENDER:
            targeting["genders"] = _GENDER[audience.gender]
        body = self._call("POST", f"{acct.account_id}/adsets", token, {
            "name": name[:200], "campaign_id": campaign_id, "daily_budget": int(budget_minor),
            "billing_event": "IMPRESSIONS", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "optimization_goal": "LINK_CLICKS",
            "destination_type": "WEBSITE", "targeting": targeting, "status": "ACTIVE",
        })
        return str(body["id"])

    def upload_video(self, token: str, acct: AccountRef, video_url: str, name: str) -> str:
        body = self._call("POST", f"{acct.account_id}/advideos", token, {"file_url": video_url, "name": name[:200]})
        return str(body["id"])

    def video_state(self, token: str, acct: AccountRef, video_id: str) -> VideoState:
        body = self._call("GET", video_id, token, {"fields": "status,picture"})
        status = body.get("status") or {}
        state = str(status.get("video_status") or "")
        if state == "error":
            return VideoState(ready=False, failed=True, detail="Meta could not process the video")
        return VideoState(ready=state == "ready", thumbnail_url=str(body.get("picture") or ""), detail=state)

    def create_ad(self, token: str, acct: AccountRef, ad_group_id: str, creative: AdCreativeInput) -> dict:
        if not acct.identity_id:
            raise AdsApiError("meta", "Choose a Facebook Page for this ad account before launching", status_code=400)
        video_data: dict[str, Any] = {
            "video_id": creative.video_id, "message": creative.primary_text[:2000], "title": creative.headline[:255],
            "call_to_action": {"type": creative.cta, "value": {"link": creative.landing_url}},
        }
        if creative.thumbnail_url:
            video_data["image_url"] = creative.thumbnail_url
        made = self._call("POST", f"{acct.account_id}/adcreatives", token, {
            "name": creative.name[:200], "object_story_spec": {"page_id": acct.identity_id, "video_data": video_data},
        })
        ad = self._call("POST", f"{acct.account_id}/ads", token, {
            "name": creative.name[:200], "adset_id": ad_group_id,
            "creative": {"creative_id": str(made["id"])}, "status": "ACTIVE",
        })
        return {"ad_id": str(ad["id"]), "creative_id": str(made["id"])}

    # ---------------------------------------------------------------- operations
    def set_campaign_status(self, token: str, acct: AccountRef, campaign_id: str, active: bool) -> None:
        self._call("POST", campaign_id, token, {"status": "ACTIVE" if active else "PAUSED"})

    def set_ad_group_status(self, token: str, acct: AccountRef, ad_group_id: str, active: bool) -> None:
        self._call("POST", ad_group_id, token, {"status": "ACTIVE" if active else "PAUSED"})

    def set_ad_group_budget(self, token: str, acct: AccountRef, ad_group_id: str, budget_minor: int) -> None:
        self._call("POST", ad_group_id, token, {"daily_budget": int(budget_minor)})

    def campaign_status(self, token: str, acct: AccountRef, campaign_id: str) -> str:
        body = self._call("GET", campaign_id, token, {"fields": "effective_status"})
        return str(body.get("effective_status") or "").lower()

    def campaign_stats(self, token: str, acct: AccountRef, campaign_id: str) -> list[AdStats]:
        body = self._call("GET", f"{campaign_id}/insights", token, {
            "level": "ad", "date_preset": "maximum", "limit": 500,
            "fields": "ad_id,spend,impressions,inline_link_clicks,clicks,actions",
        })
        out = []
        for row in body.get("data") or []:
            actions = {str(a.get("action_type")): a.get("value") for a in row.get("actions") or []}
            leads = [int(float(actions[k])) for k in _LEAD_ACTIONS if k in actions]
            out.append(AdStats(
                ad_id=str(row.get("ad_id") or ""),
                spend_minor=to_minor(row.get("spend"), acct.currency),
                impressions=int(float(row.get("impressions") or 0)),
                clicks=int(float(row.get("inline_link_clicks") or row.get("clicks") or 0)),
                leads=max(leads) if leads else None,
            ))
        return out


__all__ = ["MetaAdsClient", "SCOPES"]
