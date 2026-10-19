"""Google Ads API connector (REST + GAQL): Search, Display and Performance Max reporting.

Auth: Google OAuth with ``https://www.googleapis.com/auth/adwords`` (offline, so a
refresh token is issued) plus Menivor's Google Ads developer token
(``GOOGLE_ADS_DEVELOPER_TOKEN``; Basic Access is applied for in the manager
account's API Center). ``GOOGLE_ADS_LOGIN_CUSTOMER_ID`` is optional and only
needed when Menivor reads through its own manager account.

Reporting reads ``ad_group_ad`` rows per day (Search, Display, Demand Gen) and,
because Performance Max has no ad-group ads, one campaign row per day for PMax
campaigns (entity id ``campaign:<id>``). Pause/resume targets an ad group ad
(``<ad_group_id>~<ad_id>``); PMax campaigns are not changed from Menivor.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlencode

from app.domains.integrations.connectors.base import (
    AccountInfo, AuthError, CampaignDraft, CampaignDraftRequest, Connector, ConnectorError, Grant, MetricRow,
    body_of, env, expires_from, major_to_minor, micros_to_minor, now_utc, to_float, to_int,
)

SCOPE = "https://www.googleapis.com/auth/adwords"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_VERSION = "v25"
_AD_ENTITY = re.compile(r"^\d+~\d+$")


def api_version() -> str:
    raw = env("GOOGLE_ADS_API_VERSION") or DEFAULT_VERSION
    return raw if raw.startswith("v") else f"v{raw}"


class GoogleAdsConnector(Connector):
    provider = "google_ads"
    label = "Google Ads"
    capabilities = "Search, Performance Max, Display"
    supports_delivery = True
    supports_campaign_drafts = True
    required_env = ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_DEVELOPER_TOKEN")

    @property
    def _base(self) -> str:
        return f"https://googleads.googleapis.com/{api_version()}"

    def _headers(self, token: str) -> dict:
        headers = {"Authorization": f"Bearer {token}", "developer-token": env("GOOGLE_ADS_DEVELOPER_TOKEN")}
        login = re.sub(r"\D", "", env("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
        if login:
            headers["login-customer-id"] = login
        return headers

    def _call(self, transport: Any, method: str, url: str, token: str, payload: dict | None = None) -> Any:
        try:
            resp = transport.request(method, url, headers=self._headers(token), json=payload)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"Google Ads is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp)
        if resp.status_code >= 400:
            err = body[0] if isinstance(body, list) and body else body
            message = ((err or {}).get("error") or {}).get("message") if isinstance(err, dict) else None
            if resp.status_code == 401:
                raise AuthError(self.provider, f"Google Ads: {message or 'the sign-in expired'}")
            raise ConnectorError(self.provider, f"Google Ads: {message or f'HTTP {resp.status_code}'}",
                                 status_code=403 if resp.status_code == 403 else 502)
        return body

    def _token(self, transport: Any, data: dict) -> dict:
        try:
            resp = transport.request("POST", TOKEN_URL, data=data)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"Google sign-in is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        if resp.status_code >= 400 or not body.get("access_token"):
            if body.get("error") == "invalid_grant":
                raise AuthError(self.provider, "The Google Ads sign-in was revoked. Reconnect it.")
            raise ConnectorError(self.provider, "Google did not return an access token.", status_code=400)
        return body

    # ------------------------------------------------------------------- oauth
    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require_configured()
        return AUTH_URL + "?" + urlencode({
            "client_id": env("GOOGLE_ADS_CLIENT_ID"), "redirect_uri": redirect_uri, "response_type": "code",
            "scope": SCOPE, "state": state, "access_type": "offline", "prompt": "consent",
            "include_granted_scopes": "true",
        })

    def exchange_code(self, transport: Any, code: str, redirect_uri: str) -> Grant:
        self._require_configured()
        body = self._token(transport, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": env("GOOGLE_ADS_CLIENT_ID"), "client_secret": env("GOOGLE_ADS_CLIENT_SECRET"),
        })
        return Grant(access_token=body["access_token"], refresh_token=body.get("refresh_token"),
                     expires_at=expires_from(body.get("expires_in")), scopes=str(body.get("scope") or SCOPE))

    def refresh(self, transport: Any, grant: Grant) -> Grant:
        if not grant.refresh_token:
            raise AuthError(self.provider, "Google Ads needs to be reconnected.")
        body = self._token(transport, {
            "grant_type": "refresh_token", "refresh_token": grant.refresh_token,
            "client_id": env("GOOGLE_ADS_CLIENT_ID"), "client_secret": env("GOOGLE_ADS_CLIENT_SECRET"),
        })
        return Grant(access_token=body["access_token"], refresh_token=body.get("refresh_token") or grant.refresh_token,
                     expires_at=expires_from(body.get("expires_in")), scopes=grant.scopes)

    # ---------------------------------------------------------------- accounts
    def _search(self, transport: Any, token: str, customer_id: str, query: str) -> list[dict]:
        body = self._call(transport, "POST", f"{self._base}/customers/{customer_id}/googleAds:searchStream",
                          token, {"query": query})
        batches = body if isinstance(body, list) else [body]
        return [r for batch in batches if isinstance(batch, dict) for r in batch.get("results") or []]

    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:
        body = self._call(transport, "GET", f"{self._base}/customers:listAccessibleCustomers", token)
        out: list[AccountInfo] = []
        for name in (body or {}).get("resourceNames") or []:
            cid = str(name).rsplit("/", 1)[-1]
            rows = self._search(transport, token, cid, "SELECT customer.id, customer.descriptive_name, "
                                "customer.currency_code, customer.time_zone, customer.manager FROM customer")
            info = (rows[0] if rows else {}).get("customer") or {}
            if info.get("manager"):
                continue  # manager accounts carry no ads of their own
            out.append(AccountInfo(external_id=cid, name=str(info.get("descriptiveName") or cid),
                                   currency=str(info.get("currencyCode") or "USD").upper(),
                                   timezone=str(info.get("timeZone") or ""), status="active"))
        return out

    # ----------------------------------------------------------------- metrics
    _METRICS = ("metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions, "
                "metrics.conversions_value")

    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:
        window = f"segments.date BETWEEN '{since.isoformat()}' AND '{until.isoformat()}'"
        ads = self._search(transport, token, account.external_id,
                           "SELECT campaign.id, ad_group.id, ad_group_ad.ad.id, ad_group_ad.ad.name, segments.date, "
                           f"{self._METRICS} FROM ad_group_ad WHERE {window}")
        pmax = self._search(transport, token, account.external_id,
                            f"SELECT campaign.id, campaign.name, segments.date, {self._METRICS} FROM campaign "
                            f"WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX' AND {window}")
        rows = []
        for r in ads:
            ad = (r.get("adGroupAd") or {}).get("ad") or {}
            group = str((r.get("adGroup") or {}).get("id") or "")
            rows.append(self._row(r, account.currency, entity_id=f"{group}~{ad.get('id')}",
                                  name=str(ad.get("name") or ""), group_id=group))
        for r in pmax:
            camp = r.get("campaign") or {}
            rows.append(self._row(r, account.currency, entity_id=f"campaign:{camp.get('id')}",
                                  name=str(camp.get("name") or ""), group_id=""))
        return rows

    @staticmethod
    def _row(r: dict, currency: str, *, entity_id: str, name: str, group_id: str) -> MetricRow:
        m = r.get("metrics") or {}
        value = to_float(m.get("conversionsValue"))
        return MetricRow(
            day=str((r.get("segments") or {}).get("date") or ""), entity_id=entity_id, entity_name=name,
            campaign_id=str((r.get("campaign") or {}).get("id") or ""), group_id=group_id,
            spend_minor=micros_to_minor(m.get("costMicros"), currency), impressions=to_int(m.get("impressions")),
            clicks=to_int(m.get("clicks")), conversions=to_float(m.get("conversions")),
            conversion_value_minor=None if value is None else major_to_minor(value, currency),
            currency=currency,
        )

    # ---------------------------------------------------------------- delivery
    def _execute(self, transport: Any, token: str, account: AccountInfo, action: str, entity_id: str) -> dict:
        if not _AD_ENTITY.match(entity_id):
            raise ConnectorError(self.provider, "Only individual Google ads can be paused from Menivor.",
                                 status_code=400)
        cid = account.external_id
        status = "PAUSED" if action == "pause" else "ENABLED"
        self._call(transport, "POST", f"{self._base}/customers/{cid}/adGroupAds:mutate", token, {
            "operations": [{"update": {"resourceName": f"customers/{cid}/adGroupAds/{entity_id}", "status": status},
                            "updateMask": "status"}]})
        return {"provider": self.provider, "entity_id": entity_id, "status": "paused" if action == "pause" else "active"}

    # ------------------------------------------------------------- campaign drafts
    def _create_campaign(self, transport: Any, token: str, account: AccountInfo,
                         request: CampaignDraftRequest) -> CampaignDraft:
        """A Search campaign shell: a budget plus one PAUSED campaign, no ad groups,
        keywords or ads yet. Geo/keyword targeting and creative are finished by the
        workspace in the Google Ads UI before they switch it on themselves."""
        cid = account.external_id
        # ``major_to_minor`` converts 1 unit of currency to minor units (100 for USD); invert it
        # to go from minor units back to micros (Google Ads' native budget unit).
        budget_micros = int(round(request.daily_budget_minor * (1_000_000 / (major_to_minor(1, account.currency) or 100))))
        stamp = int(now_utc().timestamp() * 1000)
        budget_body = {"operations": [{"create": {
            "name": f"{request.name[:190]} budget {stamp}",
            "amountMicros": str(max(budget_micros, 1_000_000)), "deliveryMethod": "STANDARD",
        }}]}
        budget_resp = self._call(transport, "POST", f"{self._base}/customers/{cid}/campaignBudgets:mutate", token,
                                 budget_body)
        budget_name = (((budget_resp or {}).get("results") or [{}])[0]).get("resourceName")
        if not budget_name:
            raise ConnectorError(self.provider, "Google Ads did not confirm the campaign budget.", status_code=502)
        campaign_body = {"operations": [{"create": {
            "name": request.name[:200], "status": "PAUSED", "advertisingChannelType": "SEARCH",
            "campaignBudget": budget_name,
            "manualCpc": {"enhancedCpcEnabled": False},
            "networkSettings": {"targetGoogleSearch": True, "targetSearchNetwork": False,
                               "targetContentNetwork": False, "targetPartnerSearchNetwork": False},
        }}]}
        camp_resp = self._call(transport, "POST", f"{self._base}/customers/{cid}/campaigns:mutate", token,
                               campaign_body)
        camp_name = (((camp_resp or {}).get("results") or [{}])[0]).get("resourceName")
        if not camp_name:
            raise ConnectorError(self.provider, "Google Ads did not confirm the campaign.", status_code=502)
        external_id = str(camp_name).rsplit("/", 1)[-1]
        return CampaignDraft(external_id=external_id, name=request.name[:200], status="paused",
                             manage_url=f"https://ads.google.com/aw/campaigns?campaignId={external_id}",
                             raw={"resource_name": camp_name, "budget_resource_name": budget_name})


__all__ = ["GoogleAdsConnector", "SCOPE", "api_version"]
