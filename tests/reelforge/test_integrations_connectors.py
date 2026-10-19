"""Ad-account connectors: OAuth URL, code exchange, refresh, account list, metrics normalization, delivery.

Every connector runs against a recording fake transport; only the network is faked.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.domains.integrations.connectors import AD_PROVIDERS, get_connector
from app.domains.integrations.connectors.base import AccountInfo, AuthError, CampaignDraftRequest, ConnectorError, Grant
from app.domains.integrations.connectors.google_ads import GoogleAdsConnector
from tests.reelforge._integrations_fakes import FakeTransport, Resp

REDIRECT = "https://menivor.test/settings/integrations/callback"
SINCE, UNTIL = date(2026, 10, 1), date(2026, 10, 2)


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    values = {
        "MENIVOR_META_APP_ID": "meta-app", "MENIVOR_META_APP_SECRET": "meta-secret",
        "MENIVOR_TIKTOK_APP_ID": "tt-app", "MENIVOR_TIKTOK_APP_SECRET": "tt-secret",
        "GOOGLE_ADS_CLIENT_ID": "g-client", "GOOGLE_ADS_CLIENT_SECRET": "g-secret",
        "GOOGLE_ADS_DEVELOPER_TOKEN": "g-devtoken",
        "SNAPCHAT_ADS_CLIENT_ID": "snap-client", "SNAPCHAT_ADS_CLIENT_SECRET": "snap-secret",
        "REDDIT_ADS_CLIENT_ID": "rd-client", "REDDIT_ADS_CLIENT_SECRET": "rd-secret",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_registry_lists_every_creatify_provider_in_order():
    assert AD_PROVIDERS == ("meta", "google_ads", "apple_search_ads", "tiktok", "snapchat", "reddit", "applovin",
                            "openai_ads")
    for provider in AD_PROVIDERS:
        conn = get_connector(provider)
        assert conn.provider == provider and conn.label and conn.capabilities
    with pytest.raises(KeyError):
        get_connector("myspace")


def test_unconfigured_oauth_provider_reports_missing_settings(monkeypatch):
    monkeypatch.delenv("SNAPCHAT_ADS_CLIENT_SECRET")
    conn = get_connector("snapchat")
    assert not conn.configured()
    assert conn.missing_settings() == ["SNAPCHAT_ADS_CLIENT_SECRET"]
    # API-key providers need no server app.
    assert get_connector("applovin").configured() and get_connector("openai_ads").configured()


# --------------------------------------------------------------------------- Meta
def test_meta_oauth_url_exchange_accounts_metrics_and_pause():
    meta = get_connector("meta")
    q = _query(meta.authorize_url("st-1", REDIRECT))
    assert q["client_id"] == "meta-app" and q["state"] == "st-1" and q["redirect_uri"] == REDIRECT
    assert set(q["scope"].split(",")) >= {"ads_read", "ads_management", "business_management"}

    t = FakeTransport()
    t.add("GET", "https://graph.facebook.com/v21.0/oauth/access_token",
          Resp(200, {"access_token": "short"}), Resp(200, {"access_token": "long-tok", "expires_in": 5184000}))
    grant = meta.exchange_code(t, "code-1", REDIRECT)
    assert grant.access_token == "long-tok" and grant.refresh_token is None
    assert grant.expires_at and grant.expires_at > datetime.now(timezone.utc) + timedelta(days=50)
    second = t.calls[1]["params"]
    assert second["grant_type"] == "fb_exchange_token" and second["fb_exchange_token"] == "short"

    t.add("GET", "https://graph.facebook.com/v21.0/me/adaccounts", Resp(200, {"data": [
        {"id": "act_1", "name": "Shop", "currency": "USD", "timezone_name": "America/New_York", "account_status": 1},
        {"id": "act_2", "name": "Old", "currency": "EUR", "account_status": 2},
    ]}))
    accounts = meta.list_accounts(t, "long-tok")
    assert [a.external_id for a in accounts] == ["act_1", "act_2"]
    assert accounts[0].currency == "USD" and accounts[0].status == "active" and accounts[1].status == "inactive"
    assert "appsecret_proof" in t.find("GET", "https://graph.facebook.com/v21.0/me/adaccounts")[0]["params"]

    t.add("GET", "https://graph.facebook.com/v21.0/act_1/insights", Resp(200, {"data": [
        {"ad_id": "a1", "ad_name": "Hook A", "campaign_id": "c1", "date_start": "2026-10-01", "spend": "12.34",
         "impressions": "1000", "clicks": "40",
         "actions": [{"action_type": "omni_purchase", "value": "2"}],
         "action_values": [{"action_type": "omni_purchase", "value": "80.50"}]},
        {"ad_id": "a2", "ad_name": "Hook B", "campaign_id": "c1", "date_start": "2026-10-02", "spend": "5",
         "impressions": "300", "clicks": "3"},
    ], "paging": {}}))
    rows = meta.fetch_metrics(t, "long-tok", accounts[0], SINCE, UNTIL)
    assert rows[0].spend_minor == 1234 and rows[0].impressions == 1000 and rows[0].clicks == 40
    assert rows[0].conversions == 2 and rows[0].conversion_value_minor == 8050 and rows[0].day == "2026-10-01"
    assert rows[1].conversions is None and rows[1].conversion_value_minor is None
    params = t.find("GET", "https://graph.facebook.com/v21.0/act_1/insights")[0]["params"]
    assert params["level"] == "ad" and json.loads(params["time_range"]) == {"since": "2026-10-01", "until": "2026-10-02"}

    t.add("POST", "https://graph.facebook.com/v21.0/a1", Resp(200, {"success": True}))
    out = meta.execute(t, "long-tok", accounts[0], "pause", "a1")
    assert out["status"] == "paused" and t.find("POST", "https://graph.facebook.com/v21.0/a1")[0]["data"]["status"] == "PAUSED"


def test_meta_create_campaign_draft_is_always_posted_paused():
    meta = get_connector("meta")
    assert meta.supports_campaign_drafts
    base = "https://graph.facebook.com/v21.0"
    t = FakeTransport().add("POST", f"{base}/act_1/campaigns", Resp(200, {"id": "cmp_1"}))
    account = AccountInfo(external_id="act_1", name="Shop", currency="USD")
    draft = meta.create_campaign(t, "tok", account,
                                 CampaignDraftRequest(name="Fall launch", daily_budget_minor=2500))
    assert draft.external_id == "cmp_1" and draft.status == "paused"
    body = t.find("POST", f"{base}/act_1/campaigns")[0]["data"]
    assert body["status"] == "PAUSED" and body["daily_budget"] == "2500"
    assert json.loads(body["special_ad_categories"]) == []


def test_meta_create_campaign_draft_requires_a_name_and_positive_budget():
    meta = get_connector("meta")
    account = AccountInfo(external_id="act_1", name="Shop", currency="USD")
    with pytest.raises(ConnectorError):
        meta.create_campaign(FakeTransport(), "tok", account,
                             CampaignDraftRequest(name="", daily_budget_minor=1000))
    with pytest.raises(ConnectorError):
        meta.create_campaign(FakeTransport(), "tok", account,
                             CampaignDraftRequest(name="Fall launch", daily_budget_minor=0))


def test_meta_refresh_extends_live_token_and_expired_token_needs_reauth():
    meta = get_connector("meta")
    t = FakeTransport().add("GET", "https://graph.facebook.com/v21.0/oauth/access_token",
                            Resp(200, {"access_token": "new", "expires_in": 5184000}))
    fresh = meta.refresh(t, Grant(access_token="old", expires_at=datetime.now(timezone.utc) + timedelta(days=2)))
    assert fresh.access_token == "new"
    with pytest.raises(AuthError):
        meta.refresh(FakeTransport(), Grant(access_token="old", expires_at=datetime.now(timezone.utc) - timedelta(days=1)))


def test_meta_token_error_maps_to_auth_error():
    meta = get_connector("meta")
    t = FakeTransport().add("GET", "https://graph.facebook.com/v21.0/me/adaccounts",
                            Resp(400, {"error": {"code": 190, "message": "Session expired"}}))
    with pytest.raises(AuthError):
        meta.list_accounts(t, "tok")


# ------------------------------------------------------------------- Google Ads
def test_google_ads_oauth_refresh_accounts_metrics_and_pause(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "999-000-1111")
    g = get_connector("google_ads")
    q = _query(g.authorize_url("st", REDIRECT))
    assert q["scope"] == "https://www.googleapis.com/auth/adwords"
    assert q["access_type"] == "offline" and q["prompt"] == "consent" and q["client_id"] == "g-client"

    t = FakeTransport().add("POST", "https://oauth2.googleapis.com/token",
                            Resp(200, {"access_token": "ya29", "refresh_token": "1//r", "expires_in": 3599,
                                       "scope": "https://www.googleapis.com/auth/adwords"}),
                            Resp(200, {"access_token": "ya29-new", "expires_in": 3599}))
    grant = g.exchange_code(t, "code", REDIRECT)
    assert grant.refresh_token == "1//r" and grant.expires_at is not None
    fresh = g.refresh(t, grant)
    assert fresh.access_token == "ya29-new" and fresh.refresh_token == "1//r"  # kept
    assert t.calls[1]["data"]["grant_type"] == "refresh_token"

    base = "https://googleads.googleapis.com/v25"
    t.add("GET", f"{base}/customers:listAccessibleCustomers",
          Resp(200, {"resourceNames": ["customers/1234567890"]}))
    t.add("POST", f"{base}/customers/1234567890/googleAds:searchStream",
          Resp(200, [{"results": [{"customer": {"id": "1234567890", "descriptiveName": "Shop Ads",
                                                "currencyCode": "EUR", "timeZone": "Europe/Berlin",
                                                "manager": False}}]}]),
          Resp(200, [{"results": [
              {"campaign": {"id": "11", "advertisingChannelType": "SEARCH"},
               "adGroupAd": {"ad": {"id": "77", "name": "RSA 1"}}, "adGroup": {"id": "55"},
               "segments": {"date": "2026-10-01"},
               "metrics": {"costMicros": "2500000", "impressions": "900", "clicks": "30", "conversions": 1.5,
                           "conversionsValue": 45.2}}]}]),
          Resp(200, [{"results": [
              {"campaign": {"id": "12", "name": "PMax shoes", "advertisingChannelType": "PERFORMANCE_MAX"},
               "segments": {"date": "2026-10-01"},
               "metrics": {"costMicros": "1000000", "impressions": "100", "clicks": "2", "conversions": 0,
                           "conversionsValue": 0}}]}]))
    accounts = g.list_accounts(t, "ya29")
    assert accounts == [AccountInfo(external_id="1234567890", name="Shop Ads", currency="EUR",
                                    timezone="Europe/Berlin", status="active")]
    call = t.find("GET", f"{base}/customers:listAccessibleCustomers")[0]
    assert call["headers"]["developer-token"] == "g-devtoken" and call["headers"]["login-customer-id"] == "9990001111"

    rows = g.fetch_metrics(t, "ya29", accounts[0], SINCE, UNTIL)
    assert rows[0].entity_id == "55~77" and rows[0].spend_minor == 250 and rows[0].conversions == 1.5
    assert rows[0].conversion_value_minor == 4520 and rows[0].currency == "EUR"
    assert rows[1].entity_id == "campaign:12" and rows[1].entity_name == "PMax shoes" and rows[1].spend_minor == 100
    gaql = t.find("POST", f"{base}/customers/1234567890/googleAds:searchStream")[1]["json"]["query"]
    assert "FROM ad_group_ad" in gaql and "BETWEEN '2026-10-01' AND '2026-10-02'" in gaql

    t.add("POST", f"{base}/customers/1234567890/adGroupAds:mutate", Resp(200, {"results": [{}]}))
    g.execute(t, "ya29", accounts[0], "pause", "55~77")
    body = t.find("POST", f"{base}/customers/1234567890/adGroupAds:mutate")[0]["json"]
    assert body["operations"][0]["update"] == {"resourceName": "customers/1234567890/adGroupAds/55~77",
                                               "status": "PAUSED"}
    with pytest.raises(ConnectorError):
        g.execute(t, "ya29", accounts[0], "pause", "campaign:12")

    t.add("POST", f"{base}/customers/1234567890/campaignBudgets:mutate",
          Resp(200, {"results": [{"resourceName": "customers/1234567890/campaignBudgets/555"}]}))
    t.add("POST", f"{base}/customers/1234567890/campaigns:mutate",
          Resp(200, {"results": [{"resourceName": "customers/1234567890/campaigns/999"}]}))
    draft = g.create_campaign(t, "ya29", accounts[0],
                              CampaignDraftRequest(name="Launch week", daily_budget_minor=5000))
    assert draft.external_id == "999" and draft.status == "paused"
    budget_body = t.find("POST", f"{base}/customers/1234567890/campaignBudgets:mutate")[0]["json"]
    assert int(budget_body["operations"][0]["create"]["amountMicros"]) == 50_000_000  # 50.00 EUR -> micros
    camp_body = t.find("POST", f"{base}/customers/1234567890/campaigns:mutate")[0]["json"]
    create = camp_body["operations"][0]["create"]
    assert create["status"] == "PAUSED" and create["campaignBudget"] == "customers/1234567890/campaignBudgets/555"


def test_google_ads_create_campaign_draft_requires_a_name_and_positive_budget():
    g = get_connector("google_ads")
    account = AccountInfo(external_id="123", name="Shop", currency="USD")
    with pytest.raises(ConnectorError):
        g.create_campaign(FakeTransport(), "tok", account,
                          CampaignDraftRequest(name="  ", daily_budget_minor=1000))
    with pytest.raises(ConnectorError):
        g.create_campaign(FakeTransport(), "tok", account,
                          CampaignDraftRequest(name="Launch", daily_budget_minor=-1))


# ------------------------------------------------------------------ Apple Search Ads
def _es256_private_key_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(encoding=serialization.Encoding.PEM,
                             format=serialization.PrivateFormat.PKCS8,
                             encryption_algorithm=serialization.NoEncryption()).decode()


def _apple_creds() -> str:
    return json.dumps({"client_id": "SEARCHADS.abc", "team_id": "TEAM123", "key_id": "KEY456",
                       "private_key": _es256_private_key_pem()})


def test_apple_search_ads_rejects_malformed_or_incomplete_credentials():
    apple = get_connector("apple_search_ads")
    assert apple.auth == "api_key" and apple.configured()  # bring-your-own-cert; no Menivor app to register
    with pytest.raises(ConnectorError):
        apple.validate_key(FakeTransport(), "not json")
    with pytest.raises(ConnectorError):
        apple.validate_key(FakeTransport(), json.dumps({"client_id": "x"}))


def test_apple_search_ads_mints_a_client_secret_jwt_and_exchanges_it():
    import jwt as pyjwt

    apple = get_connector("apple_search_ads")
    creds_blob = _apple_creds()
    creds = json.loads(creds_blob)
    t = FakeTransport().add("POST", "https://appleid.apple.com/auth/oauth2/token",
                            Resp(200, {"access_token": "ap-tok", "expires_in": 3600}))
    grant = apple.validate_key(t, creds_blob)
    assert grant.access_token == "ap-tok" and json.loads(grant.refresh_token) == creds
    data = t.calls[0]["data"]
    assert data["grant_type"] == "client_credentials" and data["scope"] == "searchadsorg"
    assert data["client_id"] == creds["client_id"]
    header = pyjwt.get_unverified_header(data["client_secret"])
    claims = pyjwt.decode(data["client_secret"], options={"verify_signature": False})
    assert header["alg"] == "ES256" and header["kid"] == "KEY456"
    assert claims["iss"] == "TEAM123" and claims["sub"] == "SEARCHADS.abc" and claims["aud"] == "https://appleid.apple.com"


def test_apple_search_ads_invalid_client_is_auth_error():
    apple = get_connector("apple_search_ads")
    t = FakeTransport().add("POST", "https://appleid.apple.com/auth/oauth2/token",
                            Resp(400, {"error": "invalid_client"}))
    with pytest.raises(AuthError):
        apple.validate_key(t, _apple_creds())


def test_apple_search_ads_refresh_remints_from_stored_credentials():
    apple = get_connector("apple_search_ads")
    creds_blob = _apple_creds()
    t = FakeTransport().add("POST", "https://appleid.apple.com/auth/oauth2/token",
                            Resp(200, {"access_token": "ap-2", "expires_in": 3600}))
    fresh = apple.refresh(t, Grant(access_token="stale", refresh_token=creds_blob))
    assert fresh.access_token == "ap-2" and fresh.refresh_token == creds_blob
    with pytest.raises(AuthError):
        apple.refresh(FakeTransport(), Grant(access_token="stale"))


def test_apple_search_ads_accounts_metrics_pause_and_draft():
    apple = get_connector("apple_search_ads")
    base = "https://api.searchads.apple.com/api/v5"
    t = FakeTransport().add("GET", f"{base}/acls", Resp(200, {"data": [
        {"orgId": 4001, "orgName": "Acme Co", "currency": "USD"}]}))
    accounts = apple.list_accounts(t, "ap-tok")
    assert accounts[0].external_id == "4001" and accounts[0].name == "Acme Co"
    assert t.calls[0]["headers"]["Authorization"] == "Bearer ap-tok"

    t.add("POST", f"{base}/reports/campaigns", Resp(200, {"data": {"reportingDataResponse": {"row": [
        {"metadata": {"campaignId": 777, "campaignName": "US Search"},
         "granularity": [{"date": "2026-10-01", "impressions": 500, "taps": 20,
                          "localSpend": {"amount": "12.00", "currency": "USD"}, "totalInstalls": 4}]}]}}}))
    rows = apple.fetch_metrics(t, "ap-tok", accounts[0], SINCE, UNTIL)
    assert rows[0].entity_id == "777" and rows[0].spend_minor == 1200 and rows[0].clicks == 20
    assert rows[0].conversions == 4 and rows[0].day == "2026-10-01"
    report_call = t.find("POST", f"{base}/reports/campaigns")[0]
    assert report_call["headers"]["X-AP-Context"] == "orgId=4001"

    t.add("PUT", f"{base}/campaigns/777", Resp(200, {"data": {"id": 777, "status": "PAUSED"}}))
    out = apple.execute(t, "ap-tok", accounts[0], "pause", "777")
    assert out["status"] == "paused"

    t.add("POST", f"{base}/campaigns", Resp(200, {"data": {"id": 888, "name": "App launch"}}))
    draft = apple.create_campaign(t, "ap-tok", accounts[0],
                                  CampaignDraftRequest(name="App launch", daily_budget_minor=3000,
                                                       countries=("US", "CA"), adam_id="123456789"))
    assert draft.external_id == "888" and draft.status == "paused"
    create_body = t.find("POST", f"{base}/campaigns")[0]["json"]
    assert create_body["status"] == "PAUSED" and create_body["adamId"] == 123456789
    assert create_body["countriesOrRegions"] == ["US", "CA"] and create_body["supplySources"] == ["APPSTORE_SEARCH_RESULTS"]
    assert create_body["budgetAmount"] == {"amount": "30.00", "currency": "USD"}


def test_apple_search_ads_draft_requires_an_adam_id():
    apple = get_connector("apple_search_ads")
    account = AccountInfo(external_id="4001", name="Acme", currency="USD")
    with pytest.raises(ConnectorError):
        apple.create_campaign(FakeTransport(), "tok", account,
                              CampaignDraftRequest(name="App launch", daily_budget_minor=1000))


# ----------------------------------------------------------------- Apple Search Ads keyword insights
def test_apple_search_ads_keyword_insights_provisions_once_then_reuses_the_cache():
    apple = get_connector("apple_search_ads")
    base = "https://api.searchads.apple.com/api/v5"
    account = AccountInfo(external_id="4001", name="Acme", currency="USD")

    t = FakeTransport()
    t.add("POST", f"{base}/campaigns", Resp(200, {"data": {"id": 9001}}))
    t.add("POST", f"{base}/campaigns/9001/adgroups", Resp(200, {"data": {"id": 7001}}))
    t.add("POST", f"{base}/campaigns/9001/adgroups/7001/targetingkeywords/find", Resp(200, {"data": []}))
    t.add("POST", f"{base}/campaigns/9001/adgroups/7001/targetingkeywords/bulk", Resp(200, {"data": [
        {"text": "calorie tracker", "searchPopularity": 65}, {"text": "fitness app", "searchPopularity": None}]}))

    insights, cache = apple.keyword_insights(t, "ap-tok", account, adam_id="123456789", country="us",
                                             terms=["calorie tracker", "fitness app"])
    by_term = {i.term: i.popularity for i in insights}
    assert by_term == {"calorie tracker": 65, "fitness app": None}
    assert cache == {"123456789:US": {"campaign_id": "9001", "ad_group_id": "7001"}}
    create_body = t.find("POST", f"{base}/campaigns")[0]["json"]
    assert create_body["status"] == "PAUSED" and create_body["adamId"] == 123456789
    bulk_body = t.find("POST", f"{base}/campaigns/9001/adgroups/7001/targetingkeywords/bulk")[0]["json"]
    assert all(row["status"] == "PAUSED" for row in bulk_body)

    # A repeat lookup with the same cache reuses the ad group (one find call,
    # no new campaign/ad-group create) -- the earlier terms are already
    # targeting keywords, so `find` alone answers it.
    t2 = FakeTransport()
    t2.add("POST", f"{base}/campaigns/9001/adgroups/7001/targetingkeywords/find", Resp(200, {"data": [
        {"text": "calorie tracker", "searchPopularity": 70}]}))
    insights2, cache2 = apple.keyword_insights(t2, "ap-tok", account, adam_id="123456789", country="us",
                                               terms=["calorie tracker"], cache=cache)
    assert insights2[0].popularity == 70
    assert len(t2.calls) == 1  # only the one `find` call -- no re-create
    assert cache2 == cache


def test_apple_search_ads_keyword_insights_adds_only_the_missing_terms():
    apple = get_connector("apple_search_ads")
    base = "https://api.searchads.apple.com/api/v5"
    account = AccountInfo(external_id="4001", name="Acme", currency="USD")
    cache = {"42:US": {"campaign_id": "9001", "ad_group_id": "7001"}}

    t = FakeTransport()
    t.add("POST", f"{base}/campaigns/9001/adgroups/7001/targetingkeywords/find", Resp(200, {"data": [
        {"text": "known term", "searchPopularity": 55}]}))
    t.add("POST", f"{base}/campaigns/9001/adgroups/7001/targetingkeywords/bulk", Resp(200, {"data": [
        {"text": "new term", "searchPopularity": 30}]}))

    insights, _ = apple.keyword_insights(t, "ap-tok", account, adam_id="42", country="us",
                                         terms=["known term", "new term"], cache=cache)
    by_term = {i.term: i.popularity for i in insights}
    assert by_term == {"known term": 55, "new term": 30}
    bulk_body = t.find("POST", f"{base}/campaigns/9001/adgroups/7001/targetingkeywords/bulk")[0]["json"]
    assert [row["text"] for row in bulk_body] == ["new term"]


def test_apple_search_ads_keyword_insights_empty_terms_is_a_no_op():
    apple = get_connector("apple_search_ads")
    account = AccountInfo(external_id="4001", name="Acme", currency="USD")
    insights, cache = apple.keyword_insights(FakeTransport(), "ap-tok", account, adam_id="42", country="us",
                                             terms=["  ", ""])
    assert insights == [] and cache == {}


def test_keyword_insights_is_refused_for_a_provider_that_does_not_support_it():
    google = GoogleAdsConnector()
    account = AccountInfo(external_id="1", name="Acme", currency="USD")
    assert google.supports_keyword_insights is False
    with pytest.raises(ConnectorError):
        google.keyword_insights(FakeTransport(), "tok", account, adam_id="42", country="us", terms=["x"])


# ----------------------------------------------------------------------- TikTok
def test_tiktok_oauth_accounts_metrics_and_pause():
    tt = get_connector("tiktok")
    q = _query(tt.authorize_url("st", REDIRECT))
    assert q["app_id"] == "tt-app" and q["state"] == "st" and q["redirect_uri"] == REDIRECT
    base = "https://business-api.tiktok.com/open_api/v1.3"
    t = FakeTransport()
    t.add("POST", f"{base}/oauth2/access_token/", Resp(200, {"code": 0, "data": {
        "access_token": "tt-tok", "advertiser_ids": ["700"], "scope": [4, 5]}}))
    grant = tt.exchange_code(t, "auth-code", REDIRECT)
    assert grant.access_token == "tt-tok" and grant.expires_at is None and grant.account_ids == ("700",)
    assert t.calls[0]["json"] == {"app_id": "tt-app", "secret": "tt-secret", "auth_code": "auth-code"}

    t.add("GET", f"{base}/oauth2/advertiser/get/", Resp(200, {"code": 0, "data": {"list": [
        {"advertiser_id": "700", "advertiser_name": "Shop TT"}]}}))
    t.add("GET", f"{base}/advertiser/info/", Resp(200, {"code": 0, "data": {"list": [
        {"advertiser_id": "700", "name": "Shop TT", "currency": "USD", "timezone": "Etc/GMT", "status": "STATUS_ENABLE"}]}}))
    accounts = tt.list_accounts(t, "tt-tok")
    assert accounts[0].external_id == "700" and accounts[0].currency == "USD" and accounts[0].status == "active"

    t.add("GET", f"{base}/report/integrated/get/", Resp(200, {"code": 0, "data": {
        "list": [{"dimensions": {"ad_id": "9001", "stat_time_day": "2026-10-01 00:00:00"},
                  "metrics": {"ad_name": "Spark 1", "campaign_id": "300", "spend": "7.50", "impressions": "1500",
                              "clicks": "60", "conversion": "3", "complete_payment_roas": "2.0"}}],
        "page_info": {"page": 1, "total_page": 1}}}))
    rows = tt.fetch_metrics(t, "tt-tok", accounts[0], SINCE, UNTIL)
    assert rows[0].entity_id == "9001" and rows[0].day == "2026-10-01" and rows[0].spend_minor == 750
    assert rows[0].conversions == 3 and rows[0].conversion_value_minor == 1500
    params = t.find("GET", f"{base}/report/integrated/get/")[0]["params"]
    assert params["data_level"] == "AUCTION_AD" and params["advertiser_id"] == "700"

    t.add("POST", f"{base}/ad/status/update/", Resp(200, {"code": 0, "data": {}}))
    tt.execute(t, "tt-tok", accounts[0], "resume", "9001")
    assert t.find("POST", f"{base}/ad/status/update/")[0]["json"] == {
        "advertiser_id": "700", "ad_ids": ["9001"], "operation_status": "ENABLE"}


def test_tiktok_api_error_code_in_200_body_raises():
    tt = get_connector("tiktok")
    t = FakeTransport().add("GET", "https://business-api.tiktok.com/open_api/v1.3/oauth2/advertiser/get/",
                            Resp(200, {"code": 40105, "message": "Access token is invalid"}))
    with pytest.raises(AuthError):
        tt.list_accounts(t, "bad")


# --------------------------------------------------------------------- Snapchat
def test_snapchat_oauth_refresh_accounts_and_micro_currency_metrics():
    snap = get_connector("snapchat")
    q = _query(snap.authorize_url("st", REDIRECT))
    assert q["scope"] == "snapchat-marketing-api" and q["client_id"] == "snap-client"
    t = FakeTransport()
    t.add("POST", "https://accounts.snapchat.com/login/oauth2/access_token",
          Resp(200, {"access_token": "s1", "refresh_token": "sr", "expires_in": 1800}),
          Resp(200, {"access_token": "s2", "refresh_token": "sr2", "expires_in": 1800}))
    grant = snap.exchange_code(t, "c", REDIRECT)
    assert grant.refresh_token == "sr"
    assert snap.refresh(t, grant).refresh_token == "sr2"

    t.add("GET", "https://adsapi.snapchat.com/v1/me/organizations", Resp(200, {"organizations": [
        {"organization": {"id": "org1", "ad_accounts": [
            {"id": "aa1", "name": "Snap Shop", "currency": "USD", "timezone": "UTC", "status": "ACTIVE"}]}}]}))
    accounts = snap.list_accounts(t, "s2")
    assert accounts[0].external_id == "aa1"

    t.add("GET", "https://adsapi.snapchat.com/v1/adaccounts/aa1/stats", Resp(200, {"timeseries_stats": [
        {"timeseries_stat": {"breakdown_stats": {"ad": [{"id": "ad9", "timeseries": [
            {"start_time": "2026-10-01T00:00:00.000-00:00",
             "stats": {"impressions": 400, "swipes": 12, "spend": 3450000,
                       "conversion_purchases": 1, "conversion_purchases_value": 20000000}}]}]}}}]}))
    rows = snap.fetch_metrics(t, "s2", accounts[0], SINCE, UNTIL)
    assert rows[0].spend_minor == 345 and rows[0].clicks == 12 and rows[0].conversion_value_minor == 2000
    assert not snap.supports_delivery
    with pytest.raises(ConnectorError):
        snap.execute(t, "s2", accounts[0], "pause", "ad9")


# ----------------------------------------------------------------------- Reddit
def test_reddit_oauth_basic_auth_accounts_metrics_and_pause():
    rd = get_connector("reddit")
    q = _query(rd.authorize_url("st", REDIRECT))
    assert q["duration"] == "permanent" and set(q["scope"].split(" ")) == {"adsread", "adsedit"}
    t = FakeTransport()
    t.add("POST", "https://www.reddit.com/api/v1/access_token",
          Resp(200, {"access_token": "r1", "refresh_token": "rr", "expires_in": 3600, "scope": "adsread adsedit"}))
    grant = rd.exchange_code(t, "c", REDIRECT)
    assert grant.refresh_token == "rr"
    call = t.calls[0]
    assert call["headers"]["Authorization"].startswith("Basic ") and call["headers"]["User-Agent"]

    base = "https://ads-api.reddit.com/api/v3"
    t.add("GET", f"{base}/me/businesses", Resp(200, {"data": [{"id": "biz1"}]}))
    t.add("GET", f"{base}/businesses/biz1/ad_accounts", Resp(200, {"data": [
        {"id": "t2_acc", "name": "Reddit Shop", "currency": "USD", "time_zone_id": "America/Los_Angeles"}]}))
    accounts = rd.list_accounts(t, "r1")
    assert accounts[0].external_id == "t2_acc" and accounts[0].timezone == "America/Los_Angeles"

    t.add("POST", f"{base}/ad_accounts/t2_acc/reports", Resp(200, {"data": {"metrics": [
        {"ad_id": "rad1", "date": "2026-10-02", "impressions": 800, "clicks": 16, "spend": 4000000}]}}))
    rows = rd.fetch_metrics(t, "r1", accounts[0], SINCE, UNTIL)
    assert rows[0].spend_minor == 400 and rows[0].conversions is None and rows[0].day == "2026-10-02"
    body = t.find("POST", f"{base}/ad_accounts/t2_acc/reports")[0]["json"]["data"]
    assert body["breakdowns"] == ["AD_ID", "DATE"] and "SPEND" in body["fields"]

    t.add("PATCH", f"{base}/ads/rad1", Resp(200, {"data": {"id": "rad1"}}))
    rd.execute(t, "r1", accounts[0], "pause", "rad1")
    assert t.find("PATCH", f"{base}/ads/rad1")[0]["json"] == {"data": {"configured_status": "PAUSED"}}


# --------------------------------------------------------------------- AppLovin
def test_applovin_report_key_validation_and_metrics():
    al = get_connector("applovin")
    assert al.auth == "api_key" and not al.supports_delivery
    t = FakeTransport().add("GET", "https://r.applovin.com/report", Resp(200, {"code": 200, "results": []}))
    grant = al.validate_key(t, "report-key-123")
    assert grant.access_token == "report-key-123"
    assert al.list_accounts(t, "report-key-123")[0].external_id == "applovin"

    t2 = FakeTransport().add("GET", "https://r.applovin.com/report", Resp(200, {"code": 200, "results": [
        {"day": "2026-10-01", "campaign_id_external": "cmp1", "campaign": "Game UA", "creative_set_id": "cs1",
         "creative_set": "Video 15s", "impressions": "5000", "clicks": "100", "cost": "25.50",
         "conversions": "10"}]}))
    rows = al.fetch_metrics(t2, "report-key-123", AccountInfo("applovin", "AppLovin", "USD"), SINCE, UNTIL)
    assert rows[0].entity_id == "cs1" and rows[0].spend_minor == 2550 and rows[0].conversions == 10
    params = t2.calls[0]["params"]
    assert params["report_type"] == "advertiser" and params["api_key"] == "report-key-123"


def test_applovin_bad_key_is_auth_error():
    t = FakeTransport().add("GET", "https://r.applovin.com/report", Resp(401, {"code": 401}))
    with pytest.raises(AuthError):
        get_connector("applovin").validate_key(t, "nope-nope")


# ------------------------------------------------------------------- OpenAI Ads
def test_openai_ads_key_account_insights_and_ad_group_pause():
    oa = get_connector("openai_ads")
    assert oa.auth == "api_key" and oa.supports_delivery and oa.delivery_level == "ad_group"
    base = "https://api.ads.openai.com/v1"
    t = FakeTransport().add("GET", f"{base}/ad_account", Resp(200, {
        "id": "adacct_123", "account_name": "Acme ChatGPT", "currency_code": "USD", "status": "active",
        "timezone": "America/New_York"}))
    oa.validate_key(t, "sk-ads-xyz")
    assert t.calls[0]["headers"]["Authorization"] == "Bearer sk-ads-xyz"
    accounts = oa.list_accounts(t, "sk-ads-xyz")
    assert accounts[0].external_id == "adacct_123" and accounts[0].name == "Acme ChatGPT"

    t.add("GET", f"{base}/ad_account/insights", Resp(200, {"object": "list", "data": [
        {"readable_time": "2026-10-01", "campaign_id": "cmpn_1", "ad_group_id": "adg_1", "ad_id": "ad_501",
         "ad_name": "Blue shoes", "impressions": 700, "clicks": 22, "spend": 14.86}], "has_more": False}))
    rows = oa.fetch_metrics(t, "sk-ads-xyz", accounts[0], SINCE, UNTIL)
    assert rows[0].entity_id == "ad_501" and rows[0].spend_minor == 1486 and rows[0].conversions is None
    params = t.find("GET", f"{base}/ad_account/insights")[0]["params"]
    assert params["aggregation_level"] == "ad" and json.loads(params["time_ranges[]"])["since"] == "2026-10-01"

    t.add("POST", f"{base}/ad_groups/adg_1", Resp(200, {"id": "adg_1", "status": "paused"}))
    oa.execute(t, "sk-ads-xyz", accounts[0], "pause", "adg_1")
    assert t.find("POST", f"{base}/ad_groups/adg_1")[0]["json"] == {"status": "paused"}


def test_unknown_action_is_rejected():
    with pytest.raises(ConnectorError):
        get_connector("meta").execute(FakeTransport(), "t", AccountInfo("act_1", "x", "USD"), "delete", "a1")


def test_campaign_drafts_are_refused_for_providers_that_do_not_support_them():
    tt = get_connector("tiktok")
    assert not tt.supports_campaign_drafts
    with pytest.raises(ConnectorError):
        tt.create_campaign(FakeTransport(), "t", AccountInfo("700", "Shop TT", "USD"),
                           CampaignDraftRequest(name="Launch", daily_budget_minor=1000))
