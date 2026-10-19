"""Snapchat Marketing API connector: organizations' ad accounts and ad-level daily stats.

OAuth through Snapchat Business (scope ``snapchat-marketing-api``); access tokens
last 30 minutes and are refreshed with the stored refresh token. Spend and
purchase value come back in micro-currency. Read only this round: Snap's ad update
call needs the full ad object, so pause/resume is not offered.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from app.domains.integrations.connectors.base import (
    AccountInfo, AuthError, Connector, ConnectorError, Grant, MetricRow, body_of, env, expires_from,
    micros_to_minor, to_float, to_int,
)

AUTH_URL = "https://accounts.snapchat.com/login/oauth2/authorize"
TOKEN_URL = "https://accounts.snapchat.com/login/oauth2/access_token"
BASE = "https://adsapi.snapchat.com/v1"
SCOPE = "snapchat-marketing-api"
_FIELDS = "impressions,swipes,spend,conversion_purchases,conversion_purchases_value"


class SnapchatConnector(Connector):
    provider = "snapchat"
    label = "Snapchat Ads"
    capabilities = "Ad accounts, creative metrics"
    required_env = ("SNAPCHAT_ADS_CLIENT_ID", "SNAPCHAT_ADS_CLIENT_SECRET")

    def _get(self, transport: Any, path: str, token: str, params: dict | None = None) -> dict:
        try:
            resp = transport.request("GET", f"{BASE}/{path.lstrip('/')}",
                                     headers={"Authorization": f"Bearer {token}"}, params=params or {})
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"Snapchat is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        if resp.status_code == 401:
            raise AuthError(self.provider, "The Snapchat sign-in expired. Reconnect it.")
        if resp.status_code >= 400:
            raise ConnectorError(self.provider, f"Snapchat: {body.get('debug_message') or f'HTTP {resp.status_code}'}")
        return body

    def _token(self, transport: Any, data: dict) -> dict:
        payload = {**data, "client_id": env("SNAPCHAT_ADS_CLIENT_ID"),
                   "client_secret": env("SNAPCHAT_ADS_CLIENT_SECRET")}
        try:
            resp = transport.request("POST", TOKEN_URL, data=payload)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"Snapchat sign-in is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        if resp.status_code >= 400 or not body.get("access_token"):
            if body.get("error") == "invalid_grant":
                raise AuthError(self.provider, "The Snapchat sign-in was revoked. Reconnect it.")
            raise ConnectorError(self.provider, "Snapchat did not return an access token.", status_code=400)
        return body

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require_configured()
        return AUTH_URL + "?" + urlencode({"client_id": env("SNAPCHAT_ADS_CLIENT_ID"), "redirect_uri": redirect_uri,
                                           "response_type": "code", "scope": SCOPE, "state": state})

    def exchange_code(self, transport: Any, code: str, redirect_uri: str) -> Grant:
        self._require_configured()
        body = self._token(transport, {"grant_type": "authorization_code", "code": code,
                                       "redirect_uri": redirect_uri})
        return Grant(access_token=body["access_token"], refresh_token=body.get("refresh_token"),
                     expires_at=expires_from(body.get("expires_in")), scopes=SCOPE)

    def refresh(self, transport: Any, grant: Grant) -> Grant:
        if not grant.refresh_token:
            raise AuthError(self.provider, "Snapchat needs to be reconnected.")
        body = self._token(transport, {"grant_type": "refresh_token", "refresh_token": grant.refresh_token})
        return Grant(access_token=body["access_token"],
                     refresh_token=body.get("refresh_token") or grant.refresh_token,
                     expires_at=expires_from(body.get("expires_in")), scopes=grant.scopes)

    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:
        body = self._get(transport, "me/organizations", token, {"with_ad_accounts": "true"})
        out = []
        for wrapper in body.get("organizations") or []:
            for acct in (wrapper.get("organization") or {}).get("ad_accounts") or []:
                if acct.get("id"):
                    out.append(AccountInfo(
                        external_id=str(acct["id"]), name=str(acct.get("name") or acct["id"]),
                        currency=str(acct.get("currency") or "USD").upper(),
                        timezone=str(acct.get("timezone") or ""),
                        status="active" if str(acct.get("status") or "ACTIVE") == "ACTIVE" else "inactive"))
        return out

    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:
        body = self._get(transport, f"adaccounts/{account.external_id}/stats", token, {
            "granularity": "DAY", "breakdown": "ad", "fields": _FIELDS,
            "start_time": f"{since.isoformat()}T00:00:00",
            "end_time": f"{(until + timedelta(days=1)).isoformat()}T00:00:00",
        })
        rows: list[MetricRow] = []
        for wrapper in body.get("timeseries_stats") or []:
            ads = ((wrapper.get("timeseries_stat") or {}).get("breakdown_stats") or {}).get("ad") or []
            for ad in ads:
                for point in ad.get("timeseries") or []:
                    stats = point.get("stats") or {}
                    value = to_float(stats.get("conversion_purchases_value"))
                    rows.append(MetricRow(
                        day=str(point.get("start_time") or "")[:10], entity_id=str(ad.get("id") or ""),
                        spend_minor=micros_to_minor(stats.get("spend"), account.currency),
                        impressions=to_int(stats.get("impressions")), clicks=to_int(stats.get("swipes")),
                        conversions=to_float(stats.get("conversion_purchases")),
                        conversion_value_minor=None if value is None else micros_to_minor(value, account.currency),
                        currency=account.currency))
        return rows


__all__ = ["SnapchatConnector"]
