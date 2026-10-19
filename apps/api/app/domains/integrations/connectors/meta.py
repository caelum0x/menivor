"""Meta Marketing API connector (Graph API): ad accounts, ad-level insights, pause/resume.

Uses the same Meta business app as the paid-ads launch flow
(``MENIVOR_META_APP_ID`` / ``MENIVOR_META_APP_SECRET``) and the same Graph API
version helper. Every token call carries ``appsecret_proof``. Meta issues no
refresh token: the 60-day long-lived token is re-extended with
``fb_exchange_token`` while it is still valid; once expired, the user reconnects.

Scopes (Advanced Access needs App Review + Business Verification):
``ads_read`` for reporting, ``ads_management`` for pause/resume,
``business_management`` to list business-owned ad accounts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from typing import Any
from urllib.parse import urlencode

from app.domains.ads.config import meta_api_version
from app.domains.integrations.connectors.base import (
    AccountInfo, AuthError, CampaignDraft, CampaignDraftRequest, Connector, ConnectorError, Grant, MetricRow,
    body_of, env, expires_from, major_to_minor, now_utc, to_float, to_int,
)

SCOPES = "ads_read,ads_management,business_management"
_PURCHASE_ACTIONS = ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase")
_TOKEN_CODES = {190, 102, 463, 467}
MAX_PAGES = 20


class MetaConnector(Connector):
    provider = "meta"
    label = "Meta"
    capabilities = "Campaigns, ad sets, creative performance"
    supports_delivery = True
    supports_campaign_drafts = True
    required_env = ("MENIVOR_META_APP_ID", "MENIVOR_META_APP_SECRET")

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{meta_api_version()}"

    def _proof(self, token: str) -> str:
        return hmac.new(env("MENIVOR_META_APP_SECRET").encode(), token.encode(), hashlib.sha256).hexdigest()

    def _call(self, transport: Any, method: str, path: str, token: str | None, params: dict | None = None) -> dict:
        data = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in (params or {}).items()}
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            data["appsecret_proof"] = self._proof(token)
        url = f"{self._base}/{path.lstrip('/')}"
        try:
            if method == "GET":
                resp = transport.request("GET", url, headers=headers, params=data)
            else:
                resp = transport.request("POST", url, headers=headers, data=data)
        except Exception as exc:  # noqa: BLE001 - network failure, never the token
            raise ConnectorError(self.provider, f"Meta is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp)
        if resp.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            err = (body or {}).get("error") or {} if isinstance(body, dict) else {}
            message = err.get("error_user_msg") or err.get("message") or f"HTTP {resp.status_code}"
            if resp.status_code == 401 or err.get("code") in _TOKEN_CODES:
                raise AuthError(self.provider, f"Meta: {message}")
            raise ConnectorError(self.provider, f"Meta: {message}",
                                 status_code=403 if err.get("code") in (10, 200, 294) else 502)
        return body if isinstance(body, dict) else {"data": body}

    # ------------------------------------------------------------------- oauth
    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require_configured()
        query = urlencode({"client_id": env("MENIVOR_META_APP_ID"), "redirect_uri": redirect_uri,
                           "state": state, "scope": SCOPES, "response_type": "code"})
        return f"https://www.facebook.com/{meta_api_version()}/dialog/oauth?{query}"

    def _long_lived(self, transport: Any, token: str) -> Grant:
        body = self._call(transport, "GET", "oauth/access_token", None, {
            "grant_type": "fb_exchange_token", "client_id": env("MENIVOR_META_APP_ID"),
            "client_secret": env("MENIVOR_META_APP_SECRET"), "fb_exchange_token": token,
        })
        access = str(body.get("access_token") or "")
        if not access:
            raise ConnectorError(self.provider, "Meta did not return an access token.", status_code=400)
        return Grant(access_token=access, expires_at=expires_from(body.get("expires_in")), scopes=SCOPES)

    def exchange_code(self, transport: Any, code: str, redirect_uri: str) -> Grant:
        self._require_configured()
        short = self._call(transport, "GET", "oauth/access_token", None, {
            "client_id": env("MENIVOR_META_APP_ID"), "client_secret": env("MENIVOR_META_APP_SECRET"),
            "redirect_uri": redirect_uri, "code": code,
        })
        token = str(short.get("access_token") or "")
        if not token:
            raise ConnectorError(self.provider, "Meta did not return an access token.", status_code=400)
        return self._long_lived(transport, token)

    def refresh(self, transport: Any, grant: Grant) -> Grant:
        if grant.expires_at is not None and grant.expires_at <= now_utc():
            raise AuthError(self.provider, "The Meta connection expired. Reconnect it.")
        return self._long_lived(transport, grant.access_token)

    # ---------------------------------------------------------------- accounts
    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:
        body = self._call(transport, "GET", "me/adaccounts", token, {
            "fields": "id,name,currency,timezone_name,account_status", "limit": 200})
        return [
            AccountInfo(external_id=str(a.get("id")), name=str(a.get("name") or a.get("id")),
                        currency=str(a.get("currency") or "USD").upper(), timezone=str(a.get("timezone_name") or ""),
                        status="active" if a.get("account_status") == 1 else "inactive")
            for a in body.get("data") or [] if a.get("id")
        ]

    # ----------------------------------------------------------------- metrics
    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:
        params: dict[str, Any] = {
            "level": "ad", "time_increment": 1, "limit": 500,
            "time_range": {"since": since.isoformat(), "until": until.isoformat()},
            "fields": "ad_id,ad_name,campaign_id,adset_id,spend,impressions,reach,clicks,actions,action_values",
        }
        rows: list[MetricRow] = []
        for _ in range(MAX_PAGES):
            body = self._call(transport, "GET", f"{account.external_id}/insights", token, params)
            rows.extend(self._row(item, account.currency) for item in body.get("data") or [])
            paging = body.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not paging.get("next") or not after:
                break
            params = {**params, "after": after}
        return rows

    @staticmethod
    def _pick(entries: list[dict] | None) -> float | None:
        found = {str(e.get("action_type")): to_float(e.get("value")) for e in entries or []}
        for key in _PURCHASE_ACTIONS:
            if found.get(key) is not None:
                return found[key]
        return None

    def _row(self, item: dict, currency: str) -> MetricRow:
        conversions = self._pick(item.get("actions"))
        value = self._pick(item.get("action_values"))
        return MetricRow(
            day=str(item.get("date_start") or ""), entity_id=str(item.get("ad_id") or ""),
            entity_name=str(item.get("ad_name") or ""), campaign_id=str(item.get("campaign_id") or ""),
            group_id=str(item.get("adset_id") or ""), spend_minor=major_to_minor(item.get("spend"), currency),
            impressions=to_int(item.get("impressions")), clicks=to_int(item.get("clicks")),
            conversions=conversions, conversion_value_minor=None if value is None else major_to_minor(value, currency),
            currency=currency, reach=to_int(item.get("reach")) if item.get("reach") is not None else None,
        )

    # ---------------------------------------------------------------- delivery
    def _execute(self, transport: Any, token: str, account: AccountInfo, action: str, entity_id: str) -> dict:
        status = "PAUSED" if action == "pause" else "ACTIVE"
        self._call(transport, "POST", entity_id, token, {"status": status})
        return {"provider": self.provider, "entity_id": entity_id, "status": "paused" if action == "pause" else "active"}

    # ------------------------------------------------------------- campaign drafts
    def _create_campaign(self, transport: Any, token: str, account: AccountInfo,
                         request: CampaignDraftRequest) -> CampaignDraft:
        """A campaign-budget-optimized shell campaign, status PAUSED, no ad sets or
        ads yet. The workspace adds targeting, placements and creative in Meta Ads
        Manager before launching it themselves."""
        body = self._call(transport, "POST", f"{account.external_id}/campaigns", token, {
            "name": request.name[:200], "objective": "OUTCOME_TRAFFIC", "status": "PAUSED",
            "special_ad_categories": [], "daily_budget": str(max(1, int(request.daily_budget_minor))),
        })
        external_id = str(body.get("id") or "")
        if not external_id:
            raise ConnectorError(self.provider, "Meta did not confirm the campaign.", status_code=502)
        return CampaignDraft(external_id=external_id, name=request.name[:200], status="paused",
                             manage_url=f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?"
                                        f"act={account.external_id.removeprefix('act_')}&selected_campaign_ids="
                                        f"{external_id}",
                             raw=dict(body))


__all__ = ["MetaConnector", "SCOPES"]
