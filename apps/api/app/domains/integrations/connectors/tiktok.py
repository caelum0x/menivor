"""TikTok Business API (v1.3) connector: advertisers, ad-level daily report, ad status.

Same TikTok for Business developer app as the paid-ads flow
(``MENIVOR_TIKTOK_APP_ID`` / ``MENIVOR_TIKTOK_APP_SECRET``). Marketing API access
tokens do not expire (revoked by the advertiser), so there is no refresh step.
Spark Ads report through the same ad-level report as any other TikTok ad.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import urlencode

from app.domains.integrations.connectors.base import (
    AccountInfo, AuthError, Connector, ConnectorError, Grant, MetricRow, body_of, env, major_to_minor, to_float,
    to_int,
)

BASE = "https://business-api.tiktok.com/open_api/v1.3"
AUTH_URL = "https://business-api.tiktok.com/portal/auth"
_TOKEN_ERRORS = {40001, 40100, 40102, 40104, 40105}
_METRICS = ["ad_name", "campaign_id", "adgroup_id", "spend", "impressions", "clicks", "conversion",
            "complete_payment_roas"]
PAGE_SIZE = 1000
MAX_PAGES = 20


class TikTokConnector(Connector):
    provider = "tiktok"
    label = "TikTok Ads"
    capabilities = "Spark Ads, creative metrics"
    supports_delivery = True
    required_env = ("MENIVOR_TIKTOK_APP_ID", "MENIVOR_TIKTOK_APP_SECRET")

    def _call(self, transport: Any, method: str, path: str, token: str | None, payload: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Access-Token"] = token
        url = f"{BASE}/{path.strip('/')}/"
        try:
            if method == "GET":
                params = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in (payload or {}).items()}
                resp = transport.request("GET", url, headers=headers, params=params)
            else:
                resp = transport.request("POST", url, headers=headers, json=payload or {})
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"TikTok is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        code = body.get("code") if isinstance(body, dict) else None
        if resp.status_code >= 400 or code not in (0, None):
            message = str((body or {}).get("message") or f"HTTP {resp.status_code}")
            if resp.status_code == 401 or code in _TOKEN_ERRORS:
                raise AuthError(self.provider, f"TikTok: {message}")
            raise ConnectorError(self.provider, f"TikTok: {message}")
        return body.get("data") or {}

    # ------------------------------------------------------------------- oauth
    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require_configured()
        return AUTH_URL + "?" + urlencode({"app_id": env("MENIVOR_TIKTOK_APP_ID"), "state": state,
                                           "redirect_uri": redirect_uri})

    def exchange_code(self, transport: Any, code: str, redirect_uri: str) -> Grant:
        self._require_configured()
        data = self._call(transport, "POST", "oauth2/access_token", None, {
            "app_id": env("MENIVOR_TIKTOK_APP_ID"), "secret": env("MENIVOR_TIKTOK_APP_SECRET"), "auth_code": code})
        token = str(data.get("access_token") or "")
        if not token:
            raise ConnectorError(self.provider, "TikTok did not return an access token.", status_code=400)
        return Grant(access_token=token, scopes=",".join(str(s) for s in data.get("scope") or []),
                     account_ids=tuple(str(a) for a in data.get("advertiser_ids") or []))

    # ---------------------------------------------------------------- accounts
    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:
        data = self._call(transport, "GET", "oauth2/advertiser/get", token, {
            "app_id": env("MENIVOR_TIKTOK_APP_ID"), "secret": env("MENIVOR_TIKTOK_APP_SECRET")})
        listed = [a for a in data.get("list") or [] if a.get("advertiser_id")]
        if not listed:
            return []
        ids = [str(a["advertiser_id"]) for a in listed]
        info = {str(i.get("advertiser_id")): i for i in self._call(
            transport, "GET", "advertiser/info", token, {"advertiser_ids": ids}).get("list") or []}
        out = []
        for a in listed:
            aid = str(a["advertiser_id"])
            detail = info.get(aid, {})
            out.append(AccountInfo(
                external_id=aid, name=str(detail.get("name") or a.get("advertiser_name") or aid),
                currency=str(detail.get("currency") or "USD").upper(), timezone=str(detail.get("timezone") or ""),
                status="active" if str(detail.get("status") or "STATUS_ENABLE") == "STATUS_ENABLE" else "inactive"))
        return out

    # ----------------------------------------------------------------- metrics
    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:
        rows: list[MetricRow] = []
        for page in range(1, MAX_PAGES + 1):
            data = self._call(transport, "GET", "report/integrated/get", token, {
                "advertiser_id": account.external_id, "report_type": "BASIC", "data_level": "AUCTION_AD",
                "dimensions": ["ad_id", "stat_time_day"], "metrics": _METRICS,
                "start_date": since.isoformat(), "end_date": until.isoformat(), "page": page, "page_size": PAGE_SIZE,
            })
            rows.extend(self._row(item, account.currency) for item in data.get("list") or [])
            info = data.get("page_info") or {}
            if page >= to_int(info.get("total_page") or 1):
                break
        return rows

    @staticmethod
    def _row(item: dict, currency: str) -> MetricRow:
        dims, m = item.get("dimensions") or {}, item.get("metrics") or {}
        spend = major_to_minor(m.get("spend"), currency)
        roas = to_float(m.get("complete_payment_roas"))
        return MetricRow(
            day=str(dims.get("stat_time_day") or "")[:10], entity_id=str(dims.get("ad_id") or ""),
            entity_name=str(m.get("ad_name") or ""), campaign_id=str(m.get("campaign_id") or ""),
            group_id=str(m.get("adgroup_id") or ""), spend_minor=spend, impressions=to_int(m.get("impressions")),
            clicks=to_int(m.get("clicks")), conversions=to_float(m.get("conversion")),
            conversion_value_minor=None if roas is None else int(round(roas * spend)), currency=currency,
        )

    # ---------------------------------------------------------------- delivery
    def _execute(self, transport: Any, token: str, account: AccountInfo, action: str, entity_id: str) -> dict:
        self._call(transport, "POST", "ad/status/update", token, {
            "advertiser_id": account.external_id, "ad_ids": [entity_id],
            "operation_status": "DISABLE" if action == "pause" else "ENABLE"})
        return {"provider": self.provider, "entity_id": entity_id, "status": "paused" if action == "pause" else "active"}


__all__ = ["TikTokConnector"]
