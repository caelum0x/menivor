"""Apple Search Ads Campaign Management API connector (v5).

Apple's current auth model (`Implementing OAuth for the Apple Search Ads API`,
developer.apple.com/documentation/apple_search_ads) is per-advertiser, not a
Menivor-wide OAuth app: the workspace creates its own API user in the Apple
Search Ads UI, generates an ES256 (P-256, PKCS#8) key pair, uploads the public
key, and gets back a ``clientId``/``teamId``/``keyId``. There is nothing for
Menivor to register with Apple -- unlike Google Ads or Meta, no owner action
is queued for this provider.

The workspace pastes those four values (as one JSON blob, reusing the generic
"connect with an API key" flow) instead of a bare key string. Menivor mints a
short-lived ES256 "client secret" JWT from them, trades it for a 1-hour access
token at ``https://appleid.apple.com/auth/oauth2/token``, and stores the four
original values (not the access token) as the encrypted "refresh token" so a
fresh client secret can be minted whenever the access token expires -- Apple
issues no refresh token of its own.

Every call after that carries ``Authorization: Bearer <token>`` and
``X-AP-Context: orgId=<org>``; ``list_accounts`` enumerates the orgs the API
user can act for via ``GET /api/v5/acls``.

**Keyword insights** (Menivor Growth's keyword tracker, "Popularity/difficulty
only when the customer connects Apple Ads"): Apple's API has no app-agnostic
"look up popularity for any text" call -- ``searchPopularity`` is a property
that only appears once a term is an actual targeting keyword on an ad group
(confirmed against ``POST /v5/.../targetingkeywords/find`` and
``POST /v5/.../targetingkeywords/bulk``'s documented response shape, both of
which return the keyword's ``searchPopularity``, 5-100 in steps of 5, or
absent when Apple has not scored it). So this connector lazily provisions one
dedicated, zero-spend, permanently-``PAUSED`` campaign + ad group per
(``adamId``, country) the first time a workspace asks for insights on that
app, adds the requested terms to it as ``EXACT`` targeting keywords, and
reads ``searchPopularity`` straight back -- the ad group is never enabled, so
this never spends the workspace's budget. The campaign/ad-group ids are
handed back as an opaque ``cache`` blob for the caller to persist (this class
is stateless, per the module docstring above) so a repeat lookup reuses the
same ad group instead of creating a new one every time.
"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from app.domains.ads.platforms import minor_factor
from app.domains.integrations.connectors.base import (
    AccountInfo, AuthError, CampaignDraft, CampaignDraftRequest, Connector, ConnectorError, Grant, KeywordInsight,
    MetricRow, body_of, major_to_minor, to_float, to_int,
)

TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"
API_BASE = "https://api.searchads.apple.com/api/v5"
SCOPE = "searchadsorg"
_CLIENT_SECRET_TTL_S = 3600  # minted fresh every token call; well under Apple's 180-day hard cap
_REQUIRED_CRED_FIELDS = ("client_id", "team_id", "key_id", "private_key")
_INSIGHTS_TERM_MAX_LEN = 80  # Apple's targeting-keyword text limit
_INSIGHTS_MIN_BID_MAJOR = "0.05"  # smallest realistic bid; the ad group is never enabled, so nothing is spent
_INSIGHTS_DAILY_BUDGET_MAJOR = "1.00"


def _mint_client_secret(creds: dict) -> str:
    """A self-signed ES256 JWT Apple accepts as ``client_secret`` (not a bearer token)."""
    import jwt  # lazy: only campaigns/reporting pull in PyJWT, same pattern as app/core/clerk.py

    now = int(time.time())
    payload = {"iss": creds["team_id"], "sub": creds["client_id"], "aud": "https://appleid.apple.com",
              "iat": now, "exp": now + _CLIENT_SECRET_TTL_S}
    return jwt.encode(payload, creds["private_key"], algorithm="ES256", headers={"kid": creds["key_id"]})


class AppleSearchAdsConnector(Connector):
    provider = "apple_search_ads"
    label = "Apple Search Ads"
    capabilities = "App Store search campaigns, keyword performance"
    auth = "api_key"
    supports_delivery = True
    supports_campaign_drafts = True
    supports_keyword_insights = True
    delivery_level = "campaign"

    # ------------------------------------------------------------------ credentials
    @staticmethod
    def _parse_creds(blob: str) -> dict:
        try:
            creds = json.loads(blob)
        except ValueError as exc:
            raise ConnectorError("apple_search_ads",
                                 "Paste the Apple Search Ads credentials as JSON: "
                                 '{"client_id": ..., "team_id": ..., "key_id": ..., "private_key": "-----BEGIN...'
                                 '"}.', status_code=422) from exc
        if not isinstance(creds, dict) or any(not str(creds.get(f) or "").strip() for f in _REQUIRED_CRED_FIELDS):
            raise ConnectorError("apple_search_ads",
                                 f"The Apple Search Ads JSON needs {', '.join(_REQUIRED_CRED_FIELDS)}.",
                                 status_code=422)
        return {f: str(creds[f]) for f in _REQUIRED_CRED_FIELDS}

    def _token(self, transport: Any, creds: dict) -> dict:
        try:
            secret = _mint_client_secret(creds)
        except Exception as exc:  # noqa: BLE001 - a bad/garbled PEM, not a network failure
            raise ConnectorError(self.provider, "That private key could not be used to sign a token "
                                 "(expecting a PKCS#8 ES256/P-256 PEM key).", status_code=422) from exc
        data = {"grant_type": "client_credentials", "client_id": creds["client_id"], "client_secret": secret,
                "scope": SCOPE}
        try:
            resp = transport.request("POST", TOKEN_URL, data=data)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"Apple sign-in is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        if resp.status_code >= 400 or not body.get("access_token"):
            if body.get("error") == "invalid_client":
                raise AuthError(self.provider, "Apple rejected these Search Ads credentials. Reconnect the account.")
            raise ConnectorError(self.provider, f"Apple Search Ads: {body.get('error_description') or 'sign-in failed'}",
                                 status_code=400)
        return body

    def validate_key(self, transport: Any, key: str) -> Grant:
        creds = self._parse_creds(key)
        body = self._token(transport, creds)
        return Grant(access_token=body["access_token"], refresh_token=json.dumps(creds),
                     expires_at=self._expires_at(body.get("expires_in")), scopes=SCOPE)

    def refresh(self, transport: Any, grant: Grant) -> Grant:
        if not grant.refresh_token:
            raise AuthError(self.provider, "Apple Search Ads needs to be reconnected.")
        creds = json.loads(grant.refresh_token)
        body = self._token(transport, creds)
        return Grant(access_token=body["access_token"], refresh_token=grant.refresh_token,
                     expires_at=self._expires_at(body.get("expires_in")), scopes=grant.scopes)

    @staticmethod
    def _expires_at(seconds: Any):
        from app.domains.integrations.connectors.base import expires_from

        return expires_from(seconds)

    # ----------------------------------------------------------------- HTTP helper
    def _headers(self, token: str, org_id: str = "") -> dict:
        headers = {"Authorization": f"Bearer {token}"}
        if org_id:
            headers["X-AP-Context"] = f"orgId={org_id}"
        return headers

    def _call(self, transport: Any, method: str, path: str, token: str, *, org_id: str = "",
              payload: dict | None = None) -> dict:
        try:
            resp = transport.request(method, f"{API_BASE}/{path.lstrip('/')}", headers=self._headers(token, org_id),
                                     json=payload)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(self.provider, f"Apple Search Ads is unreachable ({exc.__class__.__name__}).") from exc
        body = body_of(resp) or {}
        if resp.status_code >= 400:
            error = body.get("error") or {}
            message = (error.get("messages") or [{}])[0].get("message") if isinstance(error, dict) else None
            if resp.status_code == 401:
                raise AuthError(self.provider, f"Apple Search Ads: {message or 'the sign-in expired'}")
            raise ConnectorError(self.provider, f"Apple Search Ads: {message or f'HTTP {resp.status_code}'}",
                                 status_code=403 if resp.status_code == 403 else 502)
        return body

    # ---------------------------------------------------------------- accounts
    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:
        body = self._call(transport, "GET", "acls", token)
        out = []
        for row in body.get("data") or []:
            org_id = str(row.get("orgId") or "")
            if not org_id:
                continue
            out.append(AccountInfo(external_id=org_id, name=str(row.get("orgName") or org_id),
                                   currency=str(row.get("currency") or "USD").upper(), status="active"))
        return out

    # ----------------------------------------------------------------- metrics
    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:
        """Campaign-level daily rows. Ad-group/keyword drill-down is a separate
        report endpoint and is out of scope for Menivor's reporting pull."""
        body = self._call(transport, "POST", "reports/campaigns", token, org_id=account.external_id, payload={
            "startTime": since.isoformat(), "endTime": until.isoformat(), "granularity": "DAILY",
            "timeZone": "UTC", "returnRowTotals": False, "returnGrandTotals": False,
            "selector": {"pagination": {"offset": 0, "limit": 1000}},
        })
        rows: list[MetricRow] = []
        report = ((body.get("data") or {}).get("reportingDataResponse") or {}).get("row") or []
        for row in report:
            meta = row.get("metadata") or {}
            campaign_id = str(meta.get("campaignId") or "")
            campaign_name = str(meta.get("campaignName") or "")
            for g in row.get("granularity") or []:
                spend = (g.get("localSpend") or {})
                rows.append(MetricRow(
                    day=str(g.get("date") or "")[:10], entity_id=campaign_id, entity_name=campaign_name,
                    campaign_id=campaign_id, spend_minor=major_to_minor(spend.get("amount"), account.currency),
                    impressions=to_int(g.get("impressions")), clicks=to_int(g.get("taps")),
                    conversions=to_float(g.get("totalInstalls")), currency=account.currency,
                ))
        return rows

    # ---------------------------------------------------------------- delivery
    def _execute(self, transport: Any, token: str, account: AccountInfo, action: str, entity_id: str) -> dict:
        status = "PAUSED" if action == "pause" else "ENABLED"
        self._call(transport, "PUT", f"campaigns/{entity_id}", token, org_id=account.external_id,
                   payload={"campaign": {"id": int(entity_id) if entity_id.isdigit() else entity_id,
                                        "status": status}})
        return {"provider": self.provider, "entity_id": entity_id, "status": "paused" if action == "pause" else "active"}

    # ------------------------------------------------------------- campaign drafts
    def _create_campaign(self, transport: Any, token: str, account: AccountInfo,
                         request: CampaignDraftRequest) -> CampaignDraft:
        """A PAUSED Search-results campaign for one App Store app. ``adam_id`` (the
        app's numeric App Store id) is required for Apple; keyword targeting is
        added by the workspace afterwards in Apple Search Ads."""
        if not str(request.adam_id or "").strip():
            raise ConnectorError(self.provider, "Choose which App Store app this campaign promotes.",
                                 status_code=400)
        amount_major = max(1, int(request.daily_budget_minor)) / minor_factor(account.currency)
        money = {"amount": f"{amount_major:.2f}", "currency": account.currency}
        payload = {
            "name": request.name[:200], "adamId": int(request.adam_id) if str(request.adam_id).isdigit()
            else request.adam_id, "budgetAmount": money, "dailyBudgetAmount": money,
            "adChannelType": "SEARCH", "billingEvent": "TAPS", "status": "PAUSED",
            "supplySources": ["APPSTORE_SEARCH_RESULTS"],
            "countriesOrRegions": list(request.countries) or ["US"],
        }
        body = self._call(transport, "POST", "campaigns", token, org_id=account.external_id, payload=payload)
        data = body.get("data") or {}
        external_id = str(data.get("id") or "")
        if not external_id:
            raise ConnectorError(self.provider, "Apple Search Ads did not confirm the campaign.", status_code=502)
        return CampaignDraft(external_id=external_id, name=request.name[:200], status="paused",
                             manage_url="https://app.searchads.apple.com/cm/app", raw=dict(data))

    # ------------------------------------------------------------- keyword insights
    def _fetch_keyword_insights(self, transport: Any, token: str, account: AccountInfo, *, adam_id: str,
                                country: str, terms: list[str],
                                cache: dict) -> tuple[list[KeywordInsight], dict]:
        key = f"{adam_id}:{country.upper()}"
        ctx = cache.get(key)
        if not isinstance(ctx, dict) or not ctx.get("campaign_id") or not ctx.get("ad_group_id"):
            ctx = self._create_insights_context(transport, token, account, adam_id, country)
            cache[key] = ctx
        popularity = self._find_keywords(transport, token, account, ctx, terms)
        missing = [t for t in terms if t.lower() not in popularity]
        if missing:
            popularity.update(self._bulk_add_keywords(transport, token, account, ctx, missing))
        insights = [KeywordInsight(term=t, popularity=popularity.get(t.lower())) for t in terms]
        return insights, cache

    def _create_insights_context(self, transport: Any, token: str, account: AccountInfo, adam_id: str,
                                 country: str) -> dict:
        """One permanently-``PAUSED`` campaign + ad group reused across every
        popularity lookup for this (app, country); never enabled, so creating
        it spends nothing."""
        money = {"amount": _INSIGHTS_DAILY_BUDGET_MAJOR, "currency": account.currency}
        campaign_payload = {
            "name": f"Menivor keyword insights ({adam_id})"[:200],
            "adamId": int(adam_id) if str(adam_id).isdigit() else adam_id,
            "budgetAmount": money, "dailyBudgetAmount": money, "adChannelType": "SEARCH",
            "billingEvent": "TAPS", "status": "PAUSED", "supplySources": ["APPSTORE_SEARCH_RESULTS"],
            "countriesOrRegions": [country.upper()],
        }
        campaign = self._call(transport, "POST", "campaigns", token, org_id=account.external_id,
                              payload=campaign_payload)
        campaign_id = str((campaign.get("data") or {}).get("id") or "")
        if not campaign_id:
            raise ConnectorError(self.provider, "Apple Search Ads did not confirm the insights campaign.",
                                 status_code=502)
        bid = {"amount": _INSIGHTS_MIN_BID_MAJOR, "currency": account.currency}
        adgroup_payload = {
            "name": "Menivor keyword insights", "status": "PAUSED", "defaultBidAmount": bid,
            "targetingDimensions": {"country": {"included": [country.upper()]}},
        }
        adgroup = self._call(transport, "POST", f"campaigns/{campaign_id}/adgroups", token,
                             org_id=account.external_id, payload=adgroup_payload)
        ad_group_id = str((adgroup.get("data") or {}).get("id") or "")
        if not ad_group_id:
            raise ConnectorError(self.provider, "Apple Search Ads did not confirm the insights ad group.",
                                 status_code=502)
        return {"campaign_id": campaign_id, "ad_group_id": ad_group_id}

    def _find_keywords(self, transport: Any, token: str, account: AccountInfo, ctx: dict,
                       terms: list[str]) -> dict[str, int | None]:
        """Free, read-only: whichever of ``terms`` are already targeting keywords
        on the insights ad group, with the ``searchPopularity`` Apple already
        scored for them."""
        payload = {"selector": {"conditions": [
            {"field": "text", "operator": "IN", "values": [t[:_INSIGHTS_TERM_MAX_LEN] for t in terms]}],
            "pagination": {"offset": 0, "limit": 1000}}}
        body = self._call(transport, "POST",
                          f"campaigns/{ctx['campaign_id']}/adgroups/{ctx['ad_group_id']}/targetingkeywords/find",
                          token, org_id=account.external_id, payload=payload)
        return self._popularity_map(body)

    def _bulk_add_keywords(self, transport: Any, token: str, account: AccountInfo, ctx: dict,
                           terms: list[str]) -> dict[str, int | None]:
        """Adds whichever of ``terms`` are not already targeting keywords on the
        insights ad group, ``PAUSED`` so they never run. Apple returns each
        new keyword's ``searchPopularity`` in the same response."""
        bid = {"amount": _INSIGHTS_MIN_BID_MAJOR, "currency": account.currency}
        payload = [{"text": t[:_INSIGHTS_TERM_MAX_LEN], "matchType": "EXACT", "status": "PAUSED", "bidAmount": bid}
                  for t in terms]
        body = self._call(transport, "POST",
                          f"campaigns/{ctx['campaign_id']}/adgroups/{ctx['ad_group_id']}/targetingkeywords/bulk",
                          token, org_id=account.external_id, payload=payload)
        return self._popularity_map(body)

    @staticmethod
    def _popularity_map(body: dict) -> dict[str, int | None]:
        out: dict[str, int | None] = {}
        for row in body.get("data") or []:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip().lower()
            if not text:
                continue
            popularity = row.get("searchPopularity")
            out[text] = int(popularity) if isinstance(popularity, (int, float)) and not isinstance(popularity, bool) \
                else None
        return out


__all__ = ["AppleSearchAdsConnector", "SCOPE", "TOKEN_URL", "API_BASE"]
