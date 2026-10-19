"""Reddit Ads API (v3) connector: businesses' ad accounts, ad-level daily report, ad status.

OAuth on reddit.com with ``duration=permanent`` (a refresh token is issued) and
scopes ``adsread`` (reporting) + ``adsedit`` (pause/resume). Reddit requires a
descriptive User-Agent and HTTP Basic client auth on the token endpoint. Spend is
reported in micro-currency. The report body follows Reddit's v3 reporting
endpoint as described by public connector docs; it was not exercised live.
"""

from __future__ import annotations

import base64
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from app.domains.integrations.connectors.base import (
    AccountInfo, AuthError, Connector, ConnectorError, Grant, MetricRow, body_of, env, expires_from,
    micros_to_minor, to_float, to_int,
)

AUTH_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
BASE = "https://ads-api.reddit.com/api/v3"
SCOPES = "adsread adsedit"
USER_AGENT = "web:menivor-integrations:1.0 (by /u/menivor)"


class RedditConnector(Connector):
    provider = "reddit"
    label = "Reddit Ads"
    capabilities = "Ad accounts, creative metrics"
    supports_delivery = True
    required_env = ("REDDIT_ADS_CLIENT_ID", "REDDIT_ADS_CLIENT_SECRET")

    def _call(self, transport: Any, method: str, path: str, token: str, payload: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
        try:
            resp = transport.request(method, f"{BASE}/{path.lstrip('/')}", headers=headers, json=payload)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"Reddit is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        if resp.status_code == 401:
            raise AuthError(self.provider, "The Reddit sign-in expired. Reconnect it.")
        if resp.status_code >= 400:
            raise ConnectorError(self.provider, f"Reddit: HTTP {resp.status_code}")
        return body

    def _token(self, transport: Any, data: dict) -> dict:
        pair = f"{env('REDDIT_ADS_CLIENT_ID')}:{env('REDDIT_ADS_CLIENT_SECRET')}".encode()
        headers = {"Authorization": f"Basic {base64.b64encode(pair).decode()}", "User-Agent": USER_AGENT}
        try:
            resp = transport.request("POST", TOKEN_URL, data=data, headers=headers)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"Reddit sign-in is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        if resp.status_code >= 400 or not body.get("access_token"):
            if body.get("error") == "invalid_grant":
                raise AuthError(self.provider, "The Reddit sign-in was revoked. Reconnect it.")
            raise ConnectorError(self.provider, "Reddit did not return an access token.", status_code=400)
        return body

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require_configured()
        return AUTH_URL + "?" + urlencode({"client_id": env("REDDIT_ADS_CLIENT_ID"), "response_type": "code",
                                           "state": state, "redirect_uri": redirect_uri, "duration": "permanent",
                                           "scope": SCOPES})

    def exchange_code(self, transport: Any, code: str, redirect_uri: str) -> Grant:
        self._require_configured()
        body = self._token(transport, {"grant_type": "authorization_code", "code": code,
                                       "redirect_uri": redirect_uri})
        return Grant(access_token=body["access_token"], refresh_token=body.get("refresh_token"),
                     expires_at=expires_from(body.get("expires_in")), scopes=str(body.get("scope") or SCOPES))

    def refresh(self, transport: Any, grant: Grant) -> Grant:
        if not grant.refresh_token:
            raise AuthError(self.provider, "Reddit needs to be reconnected.")
        body = self._token(transport, {"grant_type": "refresh_token", "refresh_token": grant.refresh_token})
        return Grant(access_token=body["access_token"],
                     refresh_token=body.get("refresh_token") or grant.refresh_token,
                     expires_at=expires_from(body.get("expires_in")), scopes=grant.scopes)

    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:
        out = []
        for biz in self._call(transport, "GET", "me/businesses", token).get("data") or []:
            if not biz.get("id"):
                continue
            accounts = self._call(transport, "GET", f"businesses/{biz['id']}/ad_accounts", token).get("data") or []
            for acct in accounts:
                if acct.get("id"):
                    out.append(AccountInfo(
                        external_id=str(acct["id"]), name=str(acct.get("name") or acct["id"]),
                        currency=str(acct.get("currency") or "USD").upper(),
                        timezone=str(acct.get("time_zone_id") or ""), status="active"))
        return out

    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:
        body = self._call(transport, "POST", f"ad_accounts/{account.external_id}/reports", token, {"data": {
            "starts_at": f"{since.isoformat()}T00:00:00Z",
            "ends_at": f"{(until + timedelta(days=1)).isoformat()}T00:00:00Z",
            "breakdowns": ["AD_ID", "DATE"],
            "fields": ["IMPRESSIONS", "CLICKS", "SPEND", "CONVERSION_PURCHASE_TOTAL_ITEMS",
                       "CONVERSION_PURCHASE_TOTAL_VALUE"],
        }})
        rows = []
        for m in (body.get("data") or {}).get("metrics") or []:
            value = to_float(m.get("conversion_purchase_total_value"))
            rows.append(MetricRow(
                day=str(m.get("date") or "")[:10], entity_id=str(m.get("ad_id") or ""),
                spend_minor=micros_to_minor(m.get("spend"), account.currency),
                impressions=to_int(m.get("impressions")), clicks=to_int(m.get("clicks")),
                conversions=to_float(m.get("conversion_purchase_total_items")),
                conversion_value_minor=None if value is None else micros_to_minor(value, account.currency),
                currency=account.currency))
        return rows

    def _execute(self, transport: Any, token: str, account: AccountInfo, action: str, entity_id: str) -> dict:
        self._call(transport, "PATCH", f"ads/{entity_id}", token,
                   {"data": {"configured_status": "PAUSED" if action == "pause" else "ACTIVE"}})
        return {"provider": self.provider, "entity_id": entity_id,
                "status": "paused" if action == "pause" else "active"}


__all__ = ["RedditConnector"]
