"""Slack for the Ads agent: signature check, OAuth install, slash command, app mention, approve/reject buttons."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.domains.approvals import service as approvals_service
from app.domains.integrations import actions, agent, contract, slack
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import IntegrationAdMetric, IntegrationConnection
from app.domains.integrations.scope import resolve
from app.domains.integrations.service import store_connection, sync_accounts
from app.domains.integrations.connectors.base import AccountInfo, Grant
from app.services import crypto_tokens
from tests.reelforge._integrations_fakes import FakeTransport, Resp, add_user, add_workspace, make_db

SECRET = "slack-signing-secret"
META = "https://graph.facebook.com/v21.0"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-integrations-key")
    monkeypatch.setenv("SLACK_CLIENT_ID", "slack-client")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "slack-client-secret")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("MENIVOR_META_APP_ID", "meta-app")
    monkeypatch.setenv("MENIVOR_META_APP_SECRET", "meta-secret")


@pytest.fixture()
def db(env, monkeypatch):
    factory = make_db()
    for module in (approvals_service, actions, contract, slack):
        monkeypatch.setattr(module, "get_session", factory.scope)
    monkeypatch.setattr(agent, "plan_key_for", lambda s, sc: "pro")
    return factory


@pytest.fixture()
def team(db):
    owner = add_user(db, "owner@example.com")
    member = add_user(db, "member@example.com")
    ws = add_workspace(db, owner, members=[(member, "member")])
    return {"owner": owner, "member": member, "ws": ws}


def _sign(body: bytes, ts: str, secret: str = SECRET) -> str:
    return "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()


def _install(db, team, team_id="T1", installer="U_OWNER"):
    with db.scope() as s:
        scope = resolve(s, team["owner"], workspace_id=team["ws"])
        url = slack.start_install(s, scope)["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    t = FakeTransport().add("POST", "https://slack.com/api/oauth.v2.access", Resp(200, {
        "ok": True, "access_token": "xoxb-bot-token", "scope": slack.SCOPES, "bot_user_id": "UBOT",
        "team": {"id": team_id, "name": "Acme"}, "authed_user": {"id": installer}}))
    with db.scope() as s:
        return slack.finish_install(s, team["owner"], code="code", state=state, transport=t), t


def _ads_with_loser(db, team):
    with db.scope() as s:
        conn = store_connection(s, owner_scope=f"ws:{team['ws']}", workspace_id=team["ws"], user_id=team["owner"],
                                kind="ads", provider="meta", grant=Grant(access_token="meta-token"))
        acct = sync_accounts(s, conn, [AccountInfo("act_1", "Shop", "USD")])[0]
        for entity, name, spend, conv in (("good", "Winner", 5000, 10.0), ("bad", "Loser", 4000, 0.0)):
            s.add(IntegrationAdMetric(ad_account_id=acct.id, owner_scope=acct.owner_scope, provider="meta",
                                      day=time.strftime("%Y-%m-%d"), entity_id=entity, entity_name=name,
                                      spend_minor=spend, impressions=1000, clicks=50, conversions=conv,
                                      conversion_value_minor=int(conv * 3000), currency="USD"))
        return acct.id


# ------------------------------------------------------------------ signature
def test_signature_verification(env):
    body = b"token=x&team_id=T1&text=hello"
    now = int(time.time())
    ts = str(now)
    assert slack.verify_signature(body, ts, _sign(body, ts), now=now)
    assert not slack.verify_signature(body, ts, _sign(body, ts, "other-secret"), now=now)
    assert not slack.verify_signature(body + b"x", ts, _sign(body, ts), now=now)
    old = str(now - 600)
    assert not slack.verify_signature(body, old, _sign(body, old), now=now)
    assert not slack.verify_signature(body, "not-a-number", "v0=00", now=now)
    assert not slack.verify_signature(body, ts, "", now=now)


def test_signature_fails_closed_without_secret(env, monkeypatch):
    monkeypatch.delenv("SLACK_SIGNING_SECRET")
    body, ts = b"x", str(int(time.time()))
    assert not slack.verify_signature(body, ts, _sign(body, ts))


# -------------------------------------------------------------------- install
def test_install_is_plan_gated_and_manager_only(db, team, monkeypatch):
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        slack.start_install(s, resolve(s, team["member"], workspace_id=team["ws"]))
    assert err.value.status_code == 403
    monkeypatch.setattr(agent, "plan_key_for", lambda s, sc: "creator")
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        slack.start_install(s, resolve(s, team["owner"], workspace_id=team["ws"]))
    assert err.value.status_code == 402


def test_install_stores_encrypted_bot_token_and_default_approver(db, team):
    out, t = _install(db, team)
    assert out == {"provider": "slack", "team_id": "T1", "team_name": "Acme", "approvers": ["U_OWNER"]}
    assert t.calls[0]["data"]["client_secret"] == "slack-client-secret"
    with db.scope() as s:
        conn = s.execute(select(IntegrationConnection).where(IntegrationConnection.provider == "slack")).scalar_one()
        assert conn.external_id == "T1" and conn.kind == "slack"
        assert crypto_tokens.decrypt(conn.access_token_enc) == "xoxb-bot-token"
        assert "xoxb" not in conn.access_token_enc


def test_one_slack_team_cannot_serve_two_workspaces(db, team):
    _install(db, team)
    other_ws = add_workspace(db, team["owner"])
    with db.scope() as s:
        url = slack.start_install(s, resolve(s, team["owner"], workspace_id=other_ws))["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    t = FakeTransport().add("POST", "https://slack.com/api/oauth.v2.access", Resp(200, {
        "ok": True, "access_token": "xoxb-2", "team": {"id": "T1", "name": "Acme"}, "authed_user": {"id": "U2"}}))
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        slack.finish_install(s, team["owner"], code="c", state=state, transport=t)
    assert err.value.status_code == 409


# ------------------------------------------------------------ command/mention
def test_slash_command_answers_questions(db, team):
    _install(db, team)
    _ads_with_loser(db, team)
    msg = slack.command_message({"team_id": "T1", "user_id": "U_ANYONE", "text": "how are my ads?"},
                                llm=lambda prompt: "Winner leads." if "Loser" in prompt else "no data")
    assert msg["response_type"] == "ephemeral" and "Winner leads." in msg["text"]
    assert slack.command_message({"team_id": "T404", "user_id": "U", "text": "hi"})["text"].startswith("Menivor")
    assert "propose" in slack.command_message({"team_id": "T1", "user_id": "U", "text": "  "})["text"]


def test_propose_from_slack_posts_buttons_and_only_approvers_can_propose(db, team):
    _install(db, team)
    _ads_with_loser(db, team)
    refused = slack.command_message({"team_id": "T1", "user_id": "U_STRANGER", "text": "propose"})
    assert "approver" in refused["text"]
    msg = slack.command_message({"team_id": "T1", "user_id": "U_OWNER", "text": "propose"})
    buttons = [e for b in msg["blocks"] if b["type"] == "actions" for e in b["elements"]]
    assert {b["action_id"] for b in buttons} == {"ad_action_approve", "ad_action_reject"}
    assert len({b["value"] for b in buttons}) == 1


def test_buttons_call_the_approval_api_and_check_the_approver(db, team):
    _install(db, team)
    _ads_with_loser(db, team)
    t = FakeTransport().add("POST", f"{META}/bad", Resp(200, {"success": True}))
    actions.set_transport(t)
    msg = slack.command_message({"team_id": "T1", "user_id": "U_OWNER", "text": "propose"})
    item_id = next(e for b in msg["blocks"] if b["type"] == "actions" for e in b["elements"])["value"]

    def click(user, action):
        return slack.interaction_message({"type": "block_actions", "team": {"id": "T1"}, "user": {"id": user},
                                          "actions": [{"action_id": action, "value": item_id}]})

    assert "approver" in click("U_STRANGER", "ad_action_approve")["text"] and t.calls == []
    done = click("U_OWNER", "ad_action_approve")
    assert done["replace_original"] is True and "Approved" in done["text"]
    assert len(t.find("POST", f"{META}/bad")) == 1
    item = approvals_service.get_item(team["owner"], item_id)
    assert item["decided_via"] == "slack" and item["status"] == "executed"
    again = click("U_OWNER", "ad_action_reject")
    assert "already" in again["text"] and len(t.find("POST", f"{META}/bad")) == 1


def test_app_mention_posts_answer_with_bot_token(db, team):
    _install(db, team)
    _ads_with_loser(db, team)
    t = FakeTransport().add("POST", "https://slack.com/api/chat.postMessage", Resp(200, {"ok": True}))
    slack.handle_event({"type": "event_callback", "team_id": "T1",
                        "event": {"type": "app_mention", "user": "U_X", "channel": "C1", "ts": "1.2",
                                  "text": "<@UBOT> which ad is best?"}},
                       transport=t, llm=lambda prompt: "Winner." if "which ad is best?" in prompt else "?")
    call = t.calls[0]
    assert call["headers"]["Authorization"] == "Bearer xoxb-bot-token"
    assert call["json"]["channel"] == "C1" and call["json"]["thread_ts"] == "1.2" and "Winner." in call["json"]["text"]
    assert slack.handle_event({"type": "url_verification", "challenge": "abc"}, transport=t) == {"challenge": "abc"}


def test_response_url_must_be_slack():
    t = FakeTransport().add("POST", "https://hooks.slack.com/commands/1", Resp(200, {}))
    assert slack.post_response(t, "https://hooks.slack.com/commands/1", {"text": "hi"}) is True
    assert slack.post_response(t, "https://evil.example/hook", {"text": "hi"}) is False
    assert slack.post_response(t, "http://hooks.slack.com/x", {"text": "hi"}) is False
    assert len(t.calls) == 1


def test_help_text_and_payload_parsing():
    payload = json.dumps({"type": "block_actions"})
    assert slack.parse_interaction_body(f"payload={payload}".encode())["type"] == "block_actions"
    assert slack.parse_interaction_body(b"garbage") == {}
