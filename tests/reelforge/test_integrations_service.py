"""Integrations service: scope + Brand-space visibility, connect flow, token refresh, reporting pull,
approval gate, onboarding credits, ads agent and the Brand Agent contract.

In-memory SQLite with the real encryption, approvals and credit-ledger code; only HTTP is faked.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.domains.approvals import service as approvals_service
from app.domains.integrations import actions, agent, contract, onboarding, service
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import IntegrationAdAccount, IntegrationAdMetric, IntegrationConnection, \
    IntegrationOAuthState
from app.domains.integrations.scope import resolve
from app.models.db.models import CreditLedger
from app.services import crypto_tokens
from tests.reelforge._integrations_fakes import FakeTransport, Resp, add_brand_kit, add_user, add_workspace, make_db

UTC = timezone.utc
TODAY = date(2026, 10, 6)
META = "https://graph.facebook.com/v21.0"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
APPLE_TOKEN = "https://appleid.apple.com/auth/oauth2/token"
APPLE_BASE = "https://api.searchads.apple.com/api/v5"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-integrations-key")
    monkeypatch.setenv("MENIVOR_INTEGRATIONS_REDIRECT_URL", "https://menivor.test/settings/integrations/callback")
    for key, value in {"MENIVOR_META_APP_ID": "meta-app", "MENIVOR_META_APP_SECRET": "meta-secret",
                       "GOOGLE_ADS_CLIENT_ID": "g", "GOOGLE_ADS_CLIENT_SECRET": "gs",
                       "GOOGLE_ADS_DEVELOPER_TOKEN": "dev"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SNAPCHAT_ADS_CLIENT_ID", raising=False)


@pytest.fixture()
def db(env, monkeypatch):
    factory = make_db()
    for module in (approvals_service, actions, contract):
        monkeypatch.setattr(module, "get_session", factory.scope)
    monkeypatch.setattr(approvals_service, "_publishing_open", lambda: True)
    return factory


@pytest.fixture()
def team(db):
    owner = add_user(db, "owner@example.com")
    member = add_user(db, "member@example.com")
    outsider = add_user(db, "outsider@example.com")
    ws = add_workspace(db, owner, members=[(member, "member")])
    kit_a = add_brand_kit(db, owner, "Brand A", workspace_id=ws)
    kit_b = add_brand_kit(db, owner, "Brand B", workspace_id=ws)
    return {"owner": owner, "member": member, "outsider": outsider, "ws": ws, "kit_a": kit_a, "kit_b": kit_b}


def _scope(db, user_id, ws=None, brand=None):
    with db.scope() as s:
        return resolve(s, user_id, workspace_id=ws, brand_space_id=brand)


def _meta_connect(db, team, *, accounts=None):
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        url = service.start_connect(s, sc, "meta")["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    t = FakeTransport()
    t.add("GET", f"{META}/oauth/access_token", Resp(200, {"access_token": "short"}),
          Resp(200, {"access_token": "meta-long-token", "expires_in": 5184000}))
    t.add("GET", f"{META}/me/adaccounts", Resp(200, {"data": accounts or [
        {"id": "act_1", "name": "Shop US", "currency": "USD", "account_status": 1},
        {"id": "act_2", "name": "Shop EU", "currency": "EUR", "account_status": 1}]}))
    with db.scope() as s:
        out = service.finish_connect(s, team["owner"], code="code", state=state, transport=t)
    return out, state, t


def _apple_creds() -> str:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
                            encryption_algorithm=serialization.NoEncryption()).decode()
    # No whitespace in the JSON itself (connect_api_key rejects a key blob
    # with spaces) -- the PEM's own newlines round-trip fine as `\n` escapes.
    return json.dumps({"client_id": "SEARCHADS.abc", "team_id": "TEAM123", "key_id": "KEY456",
                       "private_key": pem}, separators=(",", ":"))


def _apple_connect(db, team):
    """Connects the workspace's Apple Search Ads account; returns its Scope."""
    sc = _scope(db, team["owner"], team["ws"])
    t = FakeTransport().add("POST", APPLE_TOKEN, Resp(200, {"access_token": "ap-tok", "expires_in": 3600}))
    t.add("GET", f"{APPLE_BASE}/acls", Resp(200, {"data": [{"orgId": 4001, "orgName": "Acme", "currency": "USD"}]}))
    with db.scope() as s:
        service.connect_api_key(s, sc, "apple_search_ads", _apple_creds(), transport=t)
    return sc


def _account_id(db, external_id):
    with db.scope() as s:
        return s.execute(select(IntegrationAdAccount.id).where(
            IntegrationAdAccount.external_id == external_id)).scalar_one()


def _ledger(db, ws):
    with db.scope() as s:
        return [(r.reason, r.delta) for r in s.execute(
            select(CreditLedger).where(CreditLedger.workspace_id == ws).order_by(CreditLedger.id)).scalars()]


def _seed_metrics(db, account_id, rows):
    with db.scope() as s:
        acct = s.get(IntegrationAdAccount, account_id)
        for day, entity, name, spend, imp, clicks, conv, value in rows:
            s.add(IntegrationAdMetric(ad_account_id=account_id, owner_scope=acct.owner_scope, provider=acct.provider,
                                      day=day, entity_id=entity, entity_name=name, group_id="", campaign_id="c1",
                                      spend_minor=spend, impressions=imp, clicks=clicks, conversions=conv,
                                      conversion_value_minor=value, currency=acct.currency))


# --------------------------------------------------------------------------- scope
def test_scope_membership_and_brand_space_rules(db, team):
    with pytest.raises(IntegrationError) as err:
        _scope(db, team["outsider"], team["ws"])
    assert err.value.status_code == 403
    member = _scope(db, team["member"], team["ws"])
    assert member.owner_scope == f"ws:{team['ws']}" and not member.can_manage
    assert _scope(db, team["owner"], team["ws"]).can_manage
    personal = _scope(db, team["outsider"])
    assert personal.owner_scope == f"user:{team['outsider']}" and personal.can_manage
    # A brand kit of another scope is not a Brand space here.
    foreign_kit = add_brand_kit(db, team["outsider"], "Mine")
    with pytest.raises(IntegrationError) as err:
        _scope(db, team["owner"], team["ws"], foreign_kit)
    assert err.value.status_code == 404


# ------------------------------------------------------------------ connect flow
def test_oauth_connect_stores_encrypted_token_syncs_accounts_and_grants_once(db, team):
    out, state, _ = _meta_connect(db, team)
    assert out["provider"] == "meta" and [a["external_id"] for a in out["accounts"]] == ["act_1", "act_2"]
    assert out["credits_granted"] == 50
    with db.scope() as s:
        conn = s.execute(select(IntegrationConnection)).scalar_one()
        assert conn.access_token_enc != "meta-long-token" and "meta-long-token" not in str(vars(conn))
        assert crypto_tokens.decrypt(conn.access_token_enc) == "meta-long-token"
        assert conn.owner_scope == f"ws:{team['ws']}" and conn.status == "connected"
        # Only a hash of the CSRF state is kept, and it is consumed.
        assert s.execute(select(IntegrationOAuthState)).scalars().all() == []
    # Replaying the callback fails.
    with db.scope() as s, pytest.raises(IntegrationError):
        service.finish_connect(s, team["owner"], code="code", state=state, transport=FakeTransport())
    # Reconnecting does not grant the +50 again.
    out2, _, _ = _meta_connect(db, team)
    assert out2["credits_granted"] == 0
    assert _ledger(db, team["ws"]) == [("onboarding:connect_ad_accounts", 50)]


def test_callback_state_is_bound_to_the_user_who_started_it(db, team):
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        url = service.start_connect(s, sc, "meta")["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.finish_connect(s, team["member"], code="c", state=state, transport=FakeTransport())
    assert err.value.status_code == 400


def test_member_cannot_connect_and_unconfigured_provider_is_503(db, team):
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.start_connect(s, _scope(db, team["member"], team["ws"]), "meta")
    assert err.value.status_code == 403
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.start_connect(s, _scope(db, team["owner"], team["ws"]), "snapchat")
    assert err.value.status_code == 503


def test_api_key_connect_validates_before_storing(db, team):
    sc = _scope(db, team["owner"], team["ws"])
    bad = FakeTransport().add("GET", "https://r.applovin.com/report", Resp(401, {"code": 401}))
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.connect_api_key(s, sc, "applovin", "wrong-key-123", transport=bad)
    assert err.value.status_code == 400
    with db.scope() as s:
        assert s.execute(select(IntegrationConnection)).scalars().all() == []
    good = FakeTransport().add("GET", "https://r.applovin.com/report", Resp(200, {"code": 200, "results": []}))
    with db.scope() as s:
        out = service.connect_api_key(s, sc, "applovin", "report-key-123", transport=good)
    assert out["accounts"][0]["external_id"] == "applovin"
    with db.scope() as s:
        conn = s.execute(select(IntegrationConnection)).scalar_one()
        assert crypto_tokens.decrypt(conn.access_token_enc) == "report-key-123"
    with db.scope() as s, pytest.raises(IntegrationError):
        service.connect_api_key(s, sc, "meta", "x" * 20, transport=good)  # Meta signs in, no key
    with db.scope() as s, pytest.raises(IntegrationError) as err:  # a real token still rejects embedded spaces
        service.connect_api_key(s, sc, "applovin", "report key 123", transport=good)
    assert err.value.status_code == 422


def test_api_key_connect_allows_whitespace_inside_a_json_credential_blob(db, team):
    """apple_search_ads's JSON blob carries a PEM private key, which legitimately
    contains spaces ("-----BEGIN PRIVATE KEY-----") and newlines; the internal
    whitespace guard above must not reject it."""
    _apple_connect(db, team)
    with db.scope() as s:
        conn = s.execute(select(IntegrationConnection).where(
            IntegrationConnection.provider == "apple_search_ads")).scalar_one()
        assert conn.status == "connected"


def test_disconnect_removes_tokens_accounts_and_assignments(db, team):
    _meta_connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        service.assign_brand_spaces(s, sc, _account_id(db, "act_1"), [team["kit_a"]])
    with db.scope() as s:
        assert service.disconnect(s, sc, "meta") is True
    with db.scope() as s:
        assert s.execute(select(IntegrationConnection)).scalars().all() == []
        assert s.execute(select(IntegrationAdAccount)).scalars().all() == []
    with db.scope() as s:
        card = next(c for c in service.overview(s, sc)["providers"] if c["provider"] == "meta")
    assert card["connected"] is False and card["account_count"] == 0


# ------------------------------------------------------------------ campaign drafts
def test_draft_campaign_creates_a_paused_campaign_on_the_connected_account(db, team):
    _meta_connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    account_id = _account_id(db, "act_1")
    t = FakeTransport().add("POST", f"{META}/act_1/campaigns", Resp(200, {"id": "cmp_42"}))
    with db.scope() as s:
        out = service.draft_campaign(s, sc, account_id, name="Fall sale", daily_budget_minor=4000,
                                     countries=["US"], transport=t)
    assert out["external_id"] == "cmp_42" and out["status"] == "paused" and out["provider"] == "meta"
    body = t.find("POST", f"{META}/act_1/campaigns")[0]["data"]
    assert body["status"] == "PAUSED"


def test_draft_campaign_member_cannot_manage(db, team):
    _meta_connect(db, team)
    account_id = _account_id(db, "act_1")
    member_sc = _scope(db, team["member"], team["ws"])
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.draft_campaign(s, member_sc, account_id, name="Fall sale", daily_budget_minor=4000,
                               transport=FakeTransport())
    assert err.value.status_code == 403


def test_draft_campaign_auth_error_marks_reauth(db, team):
    _meta_connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    account_id = _account_id(db, "act_1")
    t = FakeTransport().add("POST", f"{META}/act_1/campaigns", Resp(400, {"error": {"code": 190, "message": "bad"}}))
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.draft_campaign(s, sc, account_id, name="Fall sale", daily_budget_minor=4000, transport=t)
    assert err.value.status_code == 409
    with db.scope() as s:
        assert s.execute(select(IntegrationConnection)).scalar_one().status == "needs_reauth"


# ------------------------------------------------------------------- token refresh
def _google_connection(db, team, *, expires_in):
    with db.scope() as s:
        conn = IntegrationConnection(
            owner_scope=f"ws:{team['ws']}", workspace_id=team["ws"], user_id=team["owner"], kind="ads",
            provider="google_ads", status="connected", access_token_enc=crypto_tokens.encrypt("old-access"),
            refresh_token_enc=crypto_tokens.encrypt("refresh-1"),
            token_expires_at=datetime.now(UTC) + expires_in)
        s.add(conn)
        s.flush()
        return conn.id


def test_expiring_token_is_refreshed_and_re_encrypted(db, team):
    conn_id = _google_connection(db, team, expires_in=timedelta(seconds=30))
    t = FakeTransport().add("POST", GOOGLE_TOKEN, Resp(200, {"access_token": "new-access", "expires_in": 3600}))
    with db.scope() as s:
        token = service.valid_token(s, s.get(IntegrationConnection, conn_id), transport=t)
    assert token == "new-access" and t.calls[0]["data"]["refresh_token"] == "refresh-1"
    with db.scope() as s:
        conn = s.get(IntegrationConnection, conn_id)
        assert crypto_tokens.decrypt(conn.access_token_enc) == "new-access"
        assert crypto_tokens.decrypt(conn.refresh_token_enc) == "refresh-1"


def test_fresh_token_is_not_refreshed_and_revoked_refresh_marks_reauth(db, team):
    conn_id = _google_connection(db, team, expires_in=timedelta(hours=1))
    with db.scope() as s:
        assert service.valid_token(s, s.get(IntegrationConnection, conn_id), transport=FakeTransport()) == "old-access"
    conn2 = _google_connection(db, {**team, "ws": add_workspace(db, team["owner"])}, expires_in=timedelta(seconds=-5))
    t = FakeTransport().add("POST", GOOGLE_TOKEN, Resp(400, {"error": "invalid_grant"}))
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.valid_token(s, s.get(IntegrationConnection, conn2), transport=t)
    assert err.value.status_code == 409
    with db.scope() as s:
        assert s.get(IntegrationConnection, conn2).status == "needs_reauth"


# ------------------------------------------------------------- brand visibility
def test_brand_space_assignment_controls_visibility(db, team):
    _meta_connect(db, team)
    owner = _scope(db, team["owner"], team["ws"])
    act_1 = _account_id(db, "act_1")
    with db.scope() as s:
        view = service.assign_brand_spaces(s, owner, act_1, [team["kit_a"]])
    assert view["brand_space_ids"] == [team["kit_a"]]

    def visible(scope):
        with db.scope() as s:
            return sorted(a.external_id for a in service.visible_accounts(s, scope))

    assert visible(owner) == ["act_1", "act_2"]
    assert visible(_scope(db, team["member"], team["ws"], team["kit_a"])) == ["act_1"]
    assert visible(_scope(db, team["member"], team["ws"], team["kit_b"])) == []
    assert visible(_scope(db, team["outsider"])) == []
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.assign_brand_spaces(s, _scope(db, team["member"], team["ws"]), act_1, [team["kit_b"]])
    assert err.value.status_code == 403
    foreign_kit = add_brand_kit(db, team["outsider"], "Elsewhere")
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.assign_brand_spaces(s, owner, act_1, [foreign_kit])
    assert err.value.status_code == 404
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.assign_brand_spaces(s, _scope(db, team["outsider"]), act_1, [])
    assert err.value.status_code == 404


# -------------------------------------------------------------- reporting pull
def test_pull_metrics_upserts_into_common_table(db, team):
    _meta_connect(db, team, accounts=[{"id": "act_1", "name": "Shop", "currency": "USD", "account_status": 1}])
    sc = _scope(db, team["owner"], team["ws"])

    def insights(spend):
        return Resp(200, {"data": [{"ad_id": "a1", "ad_name": "Hook A", "campaign_id": "c1",
                                    "date_start": "2026-10-05", "spend": spend, "impressions": "1000",
                                    "clicks": "50", "actions": [{"action_type": "purchase", "value": "5"}],
                                    "action_values": [{"action_type": "purchase", "value": "200"}]}]})

    t = FakeTransport().add("GET", f"{META}/act_1/insights", insights("10.00"), insights("12.00"))
    with db.scope() as s:
        out = service.pull_metrics(s, sc, transport=t, today=TODAY)
    assert out == {"accounts": 1, "rows": 1, "errors": []}
    with db.scope() as s:
        service.pull_metrics(s, sc, transport=t, today=TODAY)
    with db.scope() as s:
        rows = s.execute(select(IntegrationAdMetric)).scalars().all()
        assert len(rows) == 1 and rows[0].spend_minor == 1200 and rows[0].conversions == 5
    with db.scope() as s:
        report = agent.pull_report(s, sc, today=TODAY)
    creative = report["creatives"][0]
    assert creative["entity_name"] == "Hook A"
    assert creative["metrics"]["ctr"] == 0.05 and creative["metrics"]["cpa"] == 2.4
    assert creative["metrics"]["roas"] == pytest.approx(16.67, 0.01)


# ---------------------------------------------------------------- approval gate
def _poor_and_good(db, team):
    _meta_connect(db, team, accounts=[{"id": "act_1", "name": "Shop", "currency": "USD", "account_status": 1}])
    acct = _account_id(db, "act_1")
    _seed_metrics(db, acct, [
        ("2026-10-04", "good", "Winner", 5000, 10000, 300, 10.0, 30000),
        ("2026-10-04", "bad", "Loser", 4000, 9000, 40, 0.0, 0),
    ])
    return acct


def test_nothing_executes_without_approval(db, team, monkeypatch):
    acct = _poor_and_good(db, team)
    monkeypatch.setattr(agent, "plan_key_for", lambda s, sc: "pro")
    t = FakeTransport().add("POST", f"{META}/bad", Resp(200, {"success": True}))
    actions.set_transport(t)
    owner = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        proposals = agent.propose_optimization(s, owner, today=TODAY)["proposals"]
    assert [p["payload"]["entity_id"] for p in proposals] == ["bad"]
    assert proposals[0]["status"] == "pending" and t.calls == []

    item_id = proposals[0]["id"]
    # A plain member cannot approve; another workspace cannot even see it.
    with pytest.raises(IntegrationError) as err:
        actions.decide(_scope(db, team["member"], team["ws"]), item_id, "approve")
    assert err.value.status_code == 403
    with pytest.raises(IntegrationError) as err:
        actions.decide(_scope(db, team["outsider"]), item_id, "approve")
    assert err.value.status_code == 404
    assert t.calls == []

    out = actions.decide(owner, item_id, "approve", via="web")
    assert out["item"]["status"] == "executed" and len(t.find("POST", f"{META}/bad")) == 1
    assert t.calls[0]["data"]["status"] == "PAUSED"
    again = actions.decide(owner, item_id, "approve")
    assert again["idempotent"] is True and len(t.find("POST", f"{META}/bad")) == 1
    assert ("onboarding:first_approved_action", 10) in _ledger(db, team["ws"])
    assert acct


def test_rejecting_never_calls_the_platform(db, team, monkeypatch):
    _poor_and_good(db, team)
    monkeypatch.setattr(agent, "plan_key_for", lambda s, sc: "pro")
    t = FakeTransport()
    actions.set_transport(t)
    owner = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        item = agent.propose_optimization(s, owner, today=TODAY)["proposals"][0]
    out = actions.decide(owner, item["id"], "reject")
    assert out["item"]["status"] == "rejected" and t.calls == []


def test_propose_rejects_unknown_action_and_read_only_provider(db, team):
    acct = _poor_and_good(db, team)
    owner = _scope(db, team["owner"], team["ws"])
    with db.scope() as s, pytest.raises(IntegrationError):
        actions.propose(s, owner, ad_account_id=acct, action="delete", entity_id="bad")
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        actions.propose(s, _scope(db, team["member"], team["ws"]), ad_account_id=acct, action="pause",
                        entity_id="bad")
    assert err.value.status_code == 403


# -------------------------------------------------------------------- the agent
def test_agent_requires_pro_plan(db, team, monkeypatch):
    monkeypatch.setattr(agent, "plan_key_for", lambda s, sc: "free")
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        agent.ask_campaign_question(s, _scope(db, team["owner"], team["ws"]), "How is it going?", llm=lambda p: "x")
    assert err.value.status_code == 402


def test_agent_answers_from_stored_metrics_through_the_llm_seam(db, team, monkeypatch):
    _poor_and_good(db, team)
    monkeypatch.setattr(agent, "plan_key_for", lambda s, sc: "agency")
    prompts = []

    def fake_llm(prompt):
        prompts.append(prompt)
        return "Winner is carrying the account; pause Loser."

    owner = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        out = agent.ask_campaign_question(s, owner, "Which creative should I cut?", llm=fake_llm, today=TODAY)
    assert out["answer"].startswith("Winner") and out["used_llm"] is True
    assert "Loser" in prompts[0] and "Which creative should I cut?" in prompts[0]
    assert "meta-long-token" not in prompts[0]
    assert out["suggestions"][0]["entity_id"] == "bad" and out["credits_granted"] == 10
    with db.scope() as s:
        again = agent.ask_campaign_question(s, owner, "And now?", llm=lambda p: "Error: down", today=TODAY)
    assert again["used_llm"] is False and "Winner" in again["answer"] and again["credits_granted"] == 0
    assert _ledger(db, team["ws"]).count(("onboarding:first_question", 10)) == 1
    with db.scope() as s, pytest.raises(IntegrationError):
        agent.ask_campaign_question(s, owner, "   ", llm=fake_llm)


def test_onboarding_checklist_and_personal_scope_credits(db, team):
    owner = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        assert onboarding.checklist(s, owner)["earned"] == 0
        assert onboarding.grant_once(s, owner, "first_question") == 10
        assert onboarding.grant_once(s, owner, "first_question") == 0
        listed = onboarding.checklist(s, owner)
    assert [st["key"] for st in listed["steps"]] == ["connect_ad_accounts", "first_question", "first_approved_action"]
    assert listed["earned"] == 10 and listed["total"] == 70
    personal = _scope(db, team["outsider"])
    with db.scope() as s:
        assert onboarding.grant_once(s, personal, "connect_ad_accounts") == 50
        assert onboarding.grant_once(s, personal, "connect_ad_accounts") == 0
    with db.scope() as s:
        rows = s.execute(select(CreditLedger).where(CreditLedger.user_id == team["outsider"])).scalars().all()
        assert [(r.reason, r.delta, r.workspace_id) for r in rows] == [("onboarding:connect_ad_accounts", 50, None)]
    with db.scope() as s, pytest.raises(IntegrationError):
        onboarding.grant_once(s, owner, "free_money")


# --------------------------------------------------------------------- contract
def test_brand_agent_contract_respects_visibility(db, team):
    acct = _poor_and_good(db, team)
    with db.scope() as s:
        service.assign_brand_spaces(s, _scope(db, team["owner"], team["ws"]), acct, [team["kit_a"]])
    listed = contract.list_connected_accounts(team["member"], workspace_id=team["ws"], brand_space_id=team["kit_a"])
    assert [a.external_id for a in listed] == ["act_1"] and listed[0].provider == "meta"
    assert contract.list_connected_accounts(team["member"], workspace_id=team["ws"], brand_space_id=team["kit_b"]) == []
    top = contract.top_performing_creatives(team["member"], acct, workspace_id=team["ws"], period_days=7,
                                            today=TODAY)
    assert [c.entity_id for c in top] == ["good", "bad"] and top[0].roas == 6.0
    assert top[0].as_dict()["entity_name"] == "Winner"
    with pytest.raises(IntegrationError):
        contract.top_performing_creatives(team["outsider"], acct, today=TODAY)


# ----------------------------------------------------------------- overview/social
def test_overview_cards_show_not_connected_states(db, team):
    sc = _scope(db, team["member"], team["ws"])
    with db.scope() as s:
        cards = service.overview(s, sc)["providers"]
    assert [c["provider"] for c in cards] == ["meta", "google_ads", "apple_search_ads", "tiktok", "snapchat",
                                              "reddit", "applovin", "openai_ads"]
    snap = next(c for c in cards if c["provider"] == "snapchat")
    assert snap["connected"] is False and snap["configured"] is False and snap["account_count"] == 0
    assert next(c for c in cards if c["provider"] == "openai_ads")["auth"] == "api_key"


def test_social_overview_reuses_multipost_accounts(db, team, monkeypatch):
    from app.domains.multipost.models import MultipostAccount

    with db.scope() as s:
        s.add(MultipostAccount(user_id=team["owner"], workspace_id=team["ws"], provider="tiktok",
                               external_account_id="open-1", handle="shop", display_name="Shop",
                               access_token_enc=crypto_tokens.encrypt("at")))
    with db.scope() as s:
        out = service.social_overview(s, _scope(db, team["member"], team["ws"]))
    by = {p["provider"]: p for p in out["platforms"]}
    assert list(by) == ["tiktok", "instagram", "youtube"]
    assert by["tiktok"]["account"]["handle"] == "shop" and by["instagram"]["account"] is None
    assert "access_token" not in str(out)


# ----------------------------------------------------------------- keyword insights (Apple Search Ads)
def test_keyword_insights_returns_popularity_and_persists_the_provisioned_context(db, team):
    sc = _apple_connect(db, team)
    t = FakeTransport()
    t.add("POST", f"{APPLE_BASE}/campaigns", Resp(200, {"data": {"id": 9001}}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups", Resp(200, {"data": {"id": 7001}}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups/7001/targetingkeywords/find", Resp(200, {"data": []}))
    t.add("POST", f"{APPLE_BASE}/campaigns/9001/adgroups/7001/targetingkeywords/bulk",
         Resp(200, {"data": [{"text": "fitness", "searchPopularity": 80}]}))
    with db.scope() as s:
        out = service.keyword_insights(s, sc, adam_id="999", country="us", terms=["fitness"], transport=t)
    assert out == [{"term": "fitness", "popularity": 80}]
    with db.scope() as s:
        conn = s.execute(select(IntegrationConnection).where(
            IntegrationConnection.provider == "apple_search_ads")).scalar_one()
        assert conn.meta["keyword_insights"] == {"999:US": {"campaign_id": "9001", "ad_group_id": "7001"}}


def test_keyword_insights_with_no_connected_account_returns_empty(db, team):
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        out = service.keyword_insights(s, sc, adam_id="999", country="us", terms=["fitness"],
                                       transport=FakeTransport())
    assert out == []


def test_keyword_insights_auth_error_marks_reauth(db, team):
    sc = _apple_connect(db, team)
    t = FakeTransport().add("POST", f"{APPLE_BASE}/campaigns",
                            Resp(401, {"error": {"messages": [{"message": "expired"}]}}))
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.keyword_insights(s, sc, adam_id="999", country="us", terms=["fitness"], transport=t)
    assert err.value.status_code == 409
    with db.scope() as s:
        conn = s.execute(select(IntegrationConnection).where(
            IntegrationConnection.provider == "apple_search_ads")).scalar_one()
        assert conn.status == "needs_reauth"
