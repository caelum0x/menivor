"""OpenAI Ads (ads in ChatGPT) connector: Advertiser API with an ad-account-scoped key.

Public API (developers.openai.com/ads), base ``https://api.ads.openai.com/v1``,
Bearer auth with an Advertiser API key the advertiser creates in Ads Manager
(ads.openai.com). There is no OAuth, so the workspace pastes the key and Menivor
stores it encrypted. One key = one ad account.

Reporting uses ``GET /ad_account/insights`` at ad level per day; spend is in
currency units. Conversions are not documented on that call, so they stay
``None`` ("not reported"). Pause/resume is at ad-group level
(``POST /ad_groups/{id}`` with ``status``).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.domains.integrations.connectors.base import (
    AccountInfo, AuthError, Connector, ConnectorError, Grant, MetricRow, body_of, major_to_minor, to_int,
)

BASE = "https://api.ads.openai.com/v1"
_FIELDS = ["metadata.readable_time", "campaign.id", "ad_group.id", "ad.id", "ad.name", "ad.impressions",
           "ad.clicks", "ad.spend"]
PAGE_LIMIT = 2000
MAX_PAGES = 20


class OpenAIAdsConnector(Connector):
    provider = "openai_ads"
    label = "OpenAI Ads"
    capabilities = "ChatGPT ads, ad-level delivery metrics"
    auth = "api_key"
    supports_delivery = True
    delivery_level = "ad_group"

    def _call(self, transport: Any, method: str, path: str, key: str, *, params: dict | None = None,
              payload: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            resp = transport.request(method, f"{BASE}/{path.lstrip('/')}", headers=headers, params=params,
                                     json=payload)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"OpenAI Ads is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        if resp.status_code in (401, 403):
            raise AuthError(self.provider, "OpenAI Ads did not accept this API key.")
        if resp.status_code >= 400:
            message = ((body.get("error") or {}).get("message") if isinstance(body, dict) else None)
            raise ConnectorError(self.provider, f"OpenAI Ads: {message or f'HTTP {resp.status_code}'}")
        return body if isinstance(body, dict) else {}

    def validate_key(self, transport: Any, key: str) -> Grant:
        key = (key or "").strip()
        if len(key) < 8:
            raise ConnectorError(self.provider, "Paste the full OpenAI Ads API key.", status_code=422)
        acct = self._call(transport, "GET", "ad_account", key)
        return Grant(access_token=key, external_id=str(acct.get("id") or ""))

    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:
        acct = self._call(transport, "GET", "ad_account", token)
        if not acct.get("id"):
            return []
        name = acct.get("account_name") or acct.get("brand_name") or acct.get("name") or acct["id"]
        return [AccountInfo(external_id=str(acct["id"]), name=str(name),
                            currency=str(acct.get("currency_code") or "USD").upper(),
                            timezone=str(acct.get("timezone") or ""),
                            status="active" if str(acct.get("status") or "active") == "active" else "inactive")]

    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:
        params: dict[str, Any] = {
            "aggregation_level": "ad", "time_granularity": "daily", "limit": PAGE_LIMIT, "fields[]": _FIELDS,
            "time_ranges[]": json.dumps({"type": "date_range", "since": since.isoformat(),
                                         "until": until.isoformat(), "timezone": account.timezone or "UTC"}),
        }
        rows: list[MetricRow] = []
        for _ in range(MAX_PAGES):
            body = self._call(transport, "GET", "ad_account/insights", token, params=params)
            data = [d for d in body.get("data") or [] if isinstance(d, dict)]
            rows.extend(MetricRow(
                day=str(d.get("readable_time") or "")[:10], entity_id=str(d.get("ad_id") or ""),
                entity_name=str(d.get("ad_name") or ""), campaign_id=str(d.get("campaign_id") or ""),
                group_id=str(d.get("ad_group_id") or ""),
                spend_minor=major_to_minor(d.get("spend"), account.currency), impressions=to_int(d.get("impressions")),
                clicks=to_int(d.get("clicks")), currency=account.currency) for d in data)
            if not body.get("has_more") or not body.get("last_id"):
                break
            params = {**params, "after": body["last_id"]}
        return rows

    def _execute(self, transport: Any, token: str, account: AccountInfo, action: str, entity_id: str) -> dict:
        self._call(transport, "POST", f"ad_groups/{entity_id}", token,
                   payload={"status": "paused" if action == "pause" else "active"})
        return {"provider": self.provider, "entity_id": entity_id,
                "status": "paused" if action == "pause" else "active"}


__all__ = ["OpenAIAdsConnector"]
