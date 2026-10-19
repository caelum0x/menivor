"""Integrations HTTP routes: overview, key connect, scope errors, approval routes, signed Slack endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.domains.approvals import service as approvals_service
from app.domains.integrations import actions, agent, contract, router as integrations_router, slack
from app.domains.integrations.models import IntegrationAdMetric
from app.models.exception import HttpException
from tests.reelforge._integrations_fakes import FakeTransport, Resp, add_brand_kit, add_user, add_workspace, make_db

SECRET = "slack-signing-secret"


@pytest.fixture()
def ctx(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-integrations-key")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("MENIVOR_META_APP_ID", "meta-app")
    monkeypatch.setenv("MENIVOR_META_APP_SECRET", "meta-secret")
    db = make_db()
    for module in (approvals_service, actions, contract, slack, integrations_router):
        monkeypatch.setattr(module, "get_session", db.scope)
    monkeypatch.setattr(integrations_router, "require_database", lambda rid: None)
    monkeypatch.setattr(integrations_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(integrations_router, "resolve_principal",
                        lambda request, session, rid: SimpleNamespace(id=request.headers["x-test-user"]))
    monkeypatch.setattr(agent, "plan_key_for", lambda s, sc: "pro")
    transport = FakeTransport()
    integrations_router.set_transport(transport)
    actions.set_transport(transport)
    app = FastAPI()
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content={"status": exc.status_code, "message": exc.message}))
    app.include_router(integrations_router.router)
    owner = add_user(db, "owner@example.com")
    outsider = add_user(db, "out@example.com")
    ws = add_workspace(db, owner)
    kit = add_brand_kit(db, owner, "Brand A", workspace_id=ws)
    return SimpleNamespace(db=db, client=TestClient(app), t=transport, owner=owner, outsider=outsider, ws=ws, kit=kit)


def _get(ctx, path, user, **params):
    return ctx.client.get(f"/api/v1{path}", params=params, headers={"x-test-user": user})


def _post(ctx, path, user, body=None, **params):
    return ctx.client.post(f"/api/v1{path}", params=params, json=body, headers={"x-test-user": user})


def test_overview_has_every_section(ctx):
    res = _get(ctx, "/integrations", ctx.owner, workspace_id=ctx.ws)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert len(data["ads"]["providers"]) == 8 and data["agent"]["name"] == "Ads agent"
    assert [s["key"] for s in data["agent"]["onboarding"]["steps"]][0] == "connect_ad_accounts"
    assert [p["provider"] for p in data["social"]["platforms"]] == ["tiktok", "instagram", "youtube"]
    assert data["brand_spaces"] == [{"id": ctx.kit, "name": "Brand A"}]
    assert data["slack"]["command"] == "/menivor-ads"


def test_outsider_gets_403_for_someone_elses_workspace(ctx):
    assert _get(ctx, "/integrations", ctx.outsider, workspace_id=ctx.ws).status_code == 403


def test_key_connect_and_report_routes(ctx):
    ctx.t.add("GET", "https://r.applovin.com/report", Resp(200, {"code": 200, "results": []}))
    res = _post(ctx, "/integrations/ads/applovin/key", ctx.owner, {"api_key": "report-key-123"}, workspace_id=ctx.ws)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["credits_granted"] == 50
    assert "report-key-123" not in res.text
    report = _get(ctx, "/integrations/ads/report", ctx.owner, workspace_id=ctx.ws)
    assert report.status_code == 200 and report.json()["data"]["accounts"][0]["provider"] == "applovin"
    assert _post(ctx, "/integrations/ads/myspace/key", ctx.owner, {"api_key": "x" * 10}).status_code == 422


def test_propose_and_approve_routes(ctx):
    from app.domains.integrations.connectors.base import AccountInfo, Grant
    from app.domains.integrations.service import store_connection, sync_accounts

    with ctx.db.scope() as s:
        conn = store_connection(s, owner_scope=f"ws:{ctx.ws}", workspace_id=ctx.ws, user_id=ctx.owner, kind="ads",
                                provider="meta", grant=Grant(access_token="meta-token"))
        acct = sync_accounts(s, conn, [AccountInfo("act_1", "Shop", "USD")])[0]
        today = time.strftime("%Y-%m-%d")
        s.add(IntegrationAdMetric(ad_account_id=acct.id, owner_scope=acct.owner_scope, provider="meta", day=today,
                                  entity_id="good", entity_name="Winner", spend_minor=5000, impressions=1000,
                                  clicks=50, conversions=10.0, conversion_value_minor=30000, currency="USD"))
        s.add(IntegrationAdMetric(ad_account_id=acct.id, owner_scope=acct.owner_scope, provider="meta", day=today,
                                  entity_id="bad", entity_name="Loser", spend_minor=4000, impressions=1000,
                                  clicks=5, conversions=0.0, conversion_value_minor=0, currency="USD"))
    res = _post(ctx, "/integrations/agent/propose", ctx.owner, {}, workspace_id=ctx.ws)
    assert res.status_code == 200, res.text
    item_id = res.json()["data"]["proposals"][0]["id"]
    assert ctx.t.calls == []
    listed = _get(ctx, "/integrations/agent/proposals", ctx.owner, workspace_id=ctx.ws).json()["data"]["items"]
    assert [i["id"] for i in listed] == [item_id]
    ctx.t.add("POST", "https://graph.facebook.com/v21.0/bad", Resp(200, {"success": True}))
    done = _post(ctx, f"/integrations/agent/proposals/{item_id}/approve", ctx.owner, {}, workspace_id=ctx.ws)
    assert done.status_code == 200, done.text
    assert done.json()["data"]["item"]["status"] == "executed"
    assert len(ctx.t.find("POST", "https://graph.facebook.com/v21.0/bad")) == 1


def test_draft_campaign_route_creates_a_paused_campaign(ctx):
    from app.domains.integrations.connectors.base import AccountInfo, Grant
    from app.domains.integrations.service import store_connection, sync_accounts

    with ctx.db.scope() as s:
        conn = store_connection(s, owner_scope=f"ws:{ctx.ws}", workspace_id=ctx.ws, user_id=ctx.owner, kind="ads",
                                provider="meta", grant=Grant(access_token="meta-token"))
        acct = sync_accounts(s, conn, [AccountInfo("act_1", "Shop", "USD")])[0]
        account_id = acct.id
    ctx.t.add("POST", "https://graph.facebook.com/v21.0/act_1/campaigns", Resp(200, {"id": "cmp_9"}))
    res = _post(ctx, f"/integrations/ad-accounts/{account_id}/campaigns/draft", ctx.owner,
               {"name": "Launch", "daily_budget_minor": 1500, "countries": ["US"]}, workspace_id=ctx.ws)
    assert res.status_code == 200, res.text
    assert res.json()["data"] == {"provider": "meta", "ad_account_id": account_id, "external_id": "cmp_9",
                                  "name": "Launch", "status": "paused",
                                  "manage_url": "https://adsmanager.facebook.com/adsmanager/manage/campaigns?"
                                               "act=1&selected_campaign_ids=cmp_9"}


def test_draft_campaign_route_rejects_a_zero_budget(ctx):
    res = _post(ctx, f"/integrations/ad-accounts/{'0' * 32}/campaigns/draft", ctx.owner,
               {"name": "Launch", "daily_budget_minor": 0}, workspace_id=ctx.ws)
    assert res.status_code == 422


def _signed(body: bytes) -> dict:
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(SECRET.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
            "Content-Type": "application/x-www-form-urlencoded"}


def test_slack_routes_require_a_valid_signature(ctx):
    body = urlencode({"team_id": "T1", "user_id": "U1", "text": "hi",
                      "response_url": "https://hooks.slack.com/commands/T1/1"}).encode()
    bad = ctx.client.post("/api/v1/integrations/slack/commands", content=body,
                          headers={**_signed(body), "X-Slack-Signature": "v0=deadbeef"})
    assert bad.status_code == 401
    ctx.t.add("POST", "https://hooks.slack.com/commands/T1/1", Resp(200, {}))
    ok = ctx.client.post("/api/v1/integrations/slack/commands", content=body, headers=_signed(body))
    assert ok.status_code == 200 and ok.json()["text"] == "Working on it..."
    posted = ctx.t.find("POST", "https://hooks.slack.com/commands/T1/1")
    assert posted and posted[0]["json"]["text"].startswith("Menivor is not connected")

    event = json.dumps({"type": "url_verification", "challenge": "c-123"}).encode()
    res = ctx.client.post("/api/v1/integrations/slack/events", content=event, headers=_signed(event))
    assert res.json() == {"challenge": "c-123"}
    nope = ctx.client.post("/api/v1/integrations/slack/interactions", content=b"payload=%7B%7D",
                           headers={"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=00"})
    assert nope.status_code == 401
