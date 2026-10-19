"""AppLovin (AppDiscovery / Axon) connector: advertiser Reporting API with the advertiser's Report Key.

AppLovin has no OAuth for advertisers. The workspace pastes its own Report Key
(AppLovin dashboard > Account > Keys); Menivor stores it encrypted like any token
and only reads reports. Campaign management is a separate, partner-gated API, so
pause/resume is not offered. One key = one AppLovin account.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.domains.integrations.connectors.base import (
    AccountInfo, AuthError, Connector, ConnectorError, Grant, MetricRow, body_of, major_to_minor, now_utc, to_float,
    to_int,
)

REPORT_URL = "https://r.applovin.com/report"
_COLUMNS = "day,campaign_id_external,campaign,creative_set_id,creative_set,impressions,clicks,cost,conversions"
ACCOUNT_ID = "applovin"


class AppLovinConnector(Connector):
    provider = "applovin"
    label = "AppLovin"
    capabilities = "App campaigns, creative set metrics"
    auth = "api_key"

    def _report(self, transport: Any, key: str, since: date, until: date) -> list[dict]:
        params = {"api_key": key, "report_type": "advertiser", "format": "json", "columns": _COLUMNS,
                  "start": since.isoformat(), "end": until.isoformat()}
        try:
            resp = transport.request("GET", REPORT_URL, params=params)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"AppLovin is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        code = to_int(body.get("code") or resp.status_code)
        if resp.status_code in (401, 403) or code in (401, 403):
            raise AuthError(self.provider, "AppLovin did not accept this Report Key.")
        if resp.status_code >= 400 or code >= 400:
            raise ConnectorError(self.provider, f"AppLovin: HTTP {resp.status_code}")
        return [r for r in body.get("results") or [] if isinstance(r, dict)]

    def validate_key(self, transport: Any, key: str) -> Grant:
        key = (key or "").strip()
        if len(key) < 8:
            raise ConnectorError(self.provider, "Paste the full AppLovin Report Key.", status_code=422)
        day = (now_utc() - timedelta(days=1)).date()
        self._report(transport, key, day, day)
        return Grant(access_token=key, external_id=ACCOUNT_ID)

    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:
        return [AccountInfo(external_id=ACCOUNT_ID, name="AppLovin account", currency="USD")]

    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:
        rows = []
        for r in self._report(transport, token, since, until):
            rows.append(MetricRow(
                day=str(r.get("day") or "")[:10], entity_id=str(r.get("creative_set_id") or r.get("campaign_id_external")),
                entity_name=str(r.get("creative_set") or r.get("campaign") or ""),
                campaign_id=str(r.get("campaign_id_external") or ""),
                spend_minor=major_to_minor(r.get("cost"), account.currency), impressions=to_int(r.get("impressions")),
                clicks=to_int(r.get("clicks")), conversions=to_float(r.get("conversions")),
                currency=account.currency))
        return rows


__all__ = ["AppLovinConnector"]
