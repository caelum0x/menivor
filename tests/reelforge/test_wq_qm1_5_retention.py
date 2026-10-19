"""Wave Q QM1.5: viewer retention and platform events (U4, U17, U37, U39).

1. Watchlist and ratings are per channel viewer and are erased with the account
   (push opt-ins too).
2. Paid titles carry a short viewer code for the moving overlay; free titles do not.
3. ``ott.title.published``, ``ott.purchase.granted`` and ``ott.live.started`` are
   signed with the subscription secret and delivered through the MN8 outbox and
   retry path, after the caller's commit.
4. Cast and crew are edited in the studio and appear in MRSS out.
5. Push goes only to viewers who opted in, and carries only a new episode or a
   live start.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import func, select

import app.domains.ott_live.models  # noqa: F401
from app.domains.ott import events, feeds, router as ott_router
from app.domains.ott.models import OttTitle
from app.domains.ott_access import limits, router as access_router, tokens
from app.domains.ott_commerce import products, router as commerce_router, webhooks as mint_webhooks
from app.domains.ott_live import service as live
from app.domains.ott_live.models import OttLiveStream
from app.domains.ott_viewers import auth, router as viewers_router, session as viewer_session
from app.domains.ott_viewers.models import OttRating, OttViewerPush, OttWatchlistItem
from app.models.db.models import WebhookDelivery, Workspace, WorkspaceMember
from app.services import push, webhook_subscriptions, webhooks
from app.services.billing import standard_webhooks

from tests.reelforge import _wp_p3_ott as h

REPO = Path(__file__).resolve().parents[2]
OWNER = {"x-api-key": h.OWNER_KEY}
HOOK_URL = "https://93.184.216.34/hook"
WHSEC = "whsec_" + "bWludC1zZWxsZXItd2ViaG9vay1zZWNyZXQtZm9yLW1lbml2b3I="
TOKEN_A = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaa]"
TOKEN_B = "ExponentPushToken[bbbbbbbbbbbbbbbbbbbb]"


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (viewers_router, access_router, commerce_router, ott_router, feeds))
    h.enable(monkeypatch, "viewers", "storefront", "access", "commerce", "cms", "feeds", "live")
    monkeypatch.setenv(auth.SECRET_ENV, h.AUTH_SECRET)
    monkeypatch.setenv(viewer_session.SECRET_ENV, h.VIEWER_SECRET)
    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    monkeypatch.setenv("OTT_ANALYTICS_SALT", "salt-for-tests")
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "test-webhook-signing-key")
    monkeypatch.setenv("MINT_URL", "https://mint.example")
    monkeypatch.setenv(products.KEY_ENV, "menivor-seller-key-0123456789abcdef")
    monkeypatch.setenv(mint_webhooks.SECRET_ENV, WHSEC)
    monkeypatch.setattr(limits, "_STORE", limits.MemoryStore())
    monkeypatch.setattr(viewers_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr("app.domains.ott.catalog_public._art", lambda key: "")
    monkeypatch.setattr(commerce_router, "mint", lambda: products.MintSellers(
        transport=lambda m, u, b, hd: (201, {"product": b, "created": True})))
    # Events run in-process in tests (the worker path is the same function).
    sent: list[tuple] = []

    class _Task:
        @staticmethod
        def delay(*args):
            sent.append(args)
            events.emit_now(*args, session=None)

    monkeypatch.setattr(events, "emit_task", _Task)
    import app.models.db.base as db_base
    monkeypatch.setattr(db_base, "get_session", h.session_cm(factory))
    owner = h.owner(factory)
    cid, ids = h.channel(factory, owner, "maya", titles=2, access_tier="paid")
    other_owner = h.owner(factory, email="o2@example.com", key="k2")
    other_cid, other_ids = h.channel(factory, other_owner, "noor", titles=1)
    client = h.app_client(viewers_router.router, access_router.router, commerce_router.router, ott_router.router,
                          feeds.router)
    viewer = client.post("/api/v1/ott/viewers/maya/session",
                         json={"access_token": h.auth_token("sub-v", "v@example.com")}).json()["data"]
    return {"factory": factory, "client": client, "cid": cid, "ids": ids, "owner": owner, "other_ids": other_ids,
            "viewer": viewer, "sent": sent}


def _vh(env):
    return {"x-ott-viewer": env["viewer"]["session"]}


def _hooks(env, monkeypatch, statuses):
    """A subscription on the owner's workspace and a transport that answers ``statuses`` in turn."""
    posted: list[dict] = []
    answers = list(statuses)

    class _Response:
        def __init__(self, code):
            self.status_code = code

    def _post(url, *, data, headers, timeout, pinned_ip):
        posted.append({"url": url, "body": data, "headers": dict(headers)})
        return _Response(answers.pop(0) if answers else 200)

    monkeypatch.setattr(webhooks, "_post", _post)
    monkeypatch.setattr(webhooks, "_validate_and_resolve", lambda url: (None, "93.184.216.34"))
    with env["factory"]() as s:
        ws = Workspace(owner_id=env["owner"], name="Studio")
        s.add(ws)
        s.flush()
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=env["owner"], role="owner"))
        _sub, secret = webhook_subscriptions.create(s, ws.id, HOOK_URL, list(events.EVENT_TYPES))
        s.commit()
    return posted, secret


def _signed_ok(post, secret):
    expected = "sha256=" + hmac.new(secret.encode(), post["body"], hashlib.sha256).hexdigest()
    return hmac.compare_digest(post["headers"]["X-Menivor-Signature"], expected)


# --------------------------------------------------------------------------- #
# 1. Watchlist and ratings, per channel, erased with the account
# --------------------------------------------------------------------------- #
def test_watchlist_and_ratings_are_per_channel_and_erased_with_the_account(env, monkeypatch):
    c, t0, t1 = env["client"], env["ids"][0], env["ids"][1]
    assert c.put(f"/api/v1/ott/viewers/maya/watchlist/{t0}", headers=_vh(env)).json()["data"]["added"] is True
    assert c.put(f"/api/v1/ott/viewers/maya/watchlist/{t0}", headers=_vh(env)).json()["data"]["added"] is False
    c.put(f"/api/v1/ott/viewers/maya/watchlist/{t1}", headers=_vh(env))
    items = c.get("/api/v1/ott/viewers/maya/watchlist", headers=_vh(env)).json()["data"]["items"]
    assert {i["id"] for i in items} == {t0, t1}
    # Another channel's title is not on this channel.
    assert c.put(f"/api/v1/ott/viewers/maya/watchlist/{env['other_ids'][0]}", headers=_vh(env)).status_code == 404
    # The same person on another channel has their own, empty list.
    noor = c.post("/api/v1/ott/viewers/noor/session",
                  json={"access_token": h.auth_token("sub-v", "v@example.com")}).json()["data"]["session"]
    assert c.get("/api/v1/ott/viewers/noor/watchlist", headers={"x-ott-viewer": noor}).json()["data"]["items"] == []
    # The maya session does not open noor's list.
    assert c.get("/api/v1/ott/viewers/noor/watchlist", headers=_vh(env)).status_code in (401, 403, 404)

    assert c.put(f"/api/v1/ott/viewers/maya/ratings/{t0}", json={"stars": 4}, headers=_vh(env)).json()["data"] == {
        "title_id": t0, "mine": 4, "count": 1, "average": 4.0}
    assert c.put(f"/api/v1/ott/viewers/maya/ratings/{t0}", json={"stars": 6}, headers=_vh(env)).status_code == 422
    assert c.put(f"/api/v1/ott/viewers/maya/ratings/{t0}", json={"stars": 2}, headers=_vh(env)).json()["data"][
        "average"] == 2.0
    assert c.put("/api/v1/ott/viewers/maya/push", headers=_vh(env), json={
        "token": TOKEN_A, "platform": "ios", "topics": ["episodes"]}).status_code == 200
    assert c.delete(f"/api/v1/ott/viewers/maya/watchlist/{t1}", headers=_vh(env)).json()["data"]["removed"] is True

    with env["factory"]() as s:
        assert all(s.execute(select(func.count(m.id))).scalar_one() >= 1
                   for m in (OttWatchlistItem, OttRating, OttViewerPush))
    assert c.delete("/api/v1/ott/viewers/maya/me", headers=_vh(env)).json()["data"]["deleted"] is True
    with env["factory"]() as s:
        for model in (OttWatchlistItem, OttRating, OttViewerPush):
            assert s.execute(select(func.count(model.id))).scalar_one() == 0


# --------------------------------------------------------------------------- #
# 2. Viewer code for the overlay
# --------------------------------------------------------------------------- #
def test_paid_titles_carry_a_short_viewer_code(env):
    paid = env["client"].post(f"/api/v1/ott/play/{env['ids'][0]}", json={}, headers=_vh(env))
    # The viewer bought nothing yet: a paid title refuses; the owner can play it.
    assert paid.status_code == 402
    owner_play = env["client"].post(f"/api/v1/ott/play/{env['ids'][0]}", json={}, headers=OWNER).json()["data"]
    mark = owner_play["viewer_mark"]
    assert len(mark) == 8 and mark.isalnum() and mark == mark.upper()
    again = env["client"].post(f"/api/v1/ott/play/{env['ids'][0]}", json={}, headers=OWNER).json()["data"]
    assert again["viewer_mark"] == mark
    free = env["client"].post(f"/api/v1/ott/play/{env['other_ids'][0]}", json={"viewer_id": "dev-1"}).json()["data"]
    assert "viewer_mark" not in free
    from app.domains.ott_access.service import viewer_mark
    assert viewer_mark("viewer:a") != viewer_mark("viewer:b")


# --------------------------------------------------------------------------- #
# 3. Signed ott.* events through the MN8 path
# --------------------------------------------------------------------------- #
def test_title_published_is_signed_and_retried_through_mn8(env, monkeypatch):
    posted, secret = _hooks(env, monkeypatch, [409])
    with env["factory"]() as s:
        draft = OttTitle(channel_id=env["cid"], title="Episode three", kind="episode", genres=[], geo_countries=[],
                         status="draft", package_status="ready", duration_s=600, access_tier="free", position=5,
                         manifest_key="ott/x/master.m3u8")
        s.add(draft)
        s.commit()
        draft_id = draft.id
    res = env["client"].post(f"/api/v1/ott/studio/titles/{draft_id}/publish", headers=OWNER)
    assert res.status_code == 200, res.text
    assert len(posted) == 1 and _signed_ok(posted[0], secret)
    body = json.loads(posted[0]["body"])
    assert body["event_type"] == "ott.title.published" and body["title_id"] == draft_id
    assert body["event_id"].startswith("ott.title.published:")
    with env["factory"]() as s:
        (row,) = s.execute(select(WebhookDelivery)).scalars().all()
        assert row.status == webhook_subscriptions.DELIVERY_PENDING
        retried = webhook_subscriptions.retry_pending(s, now=datetime.now(timezone.utc) + timedelta(hours=2))
        assert [r.status for r in retried] == [webhook_subscriptions.DELIVERY_DELIVERED]
        s.commit()
    assert len(posted) == 2 and posted[1]["body"] == posted[0]["body"] and _signed_ok(posted[1], secret)
    # Hide and publish again: the title was already announced, so no second event.
    env["client"].post(f"/api/v1/ott/studio/titles/{draft_id}/unpublish", headers=OWNER)
    env["client"].post(f"/api/v1/ott/studio/titles/{draft_id}/publish", headers=OWNER)
    assert len(posted) == 2


def test_purchase_granted_and_live_started_are_signed(env, monkeypatch):
    posted, secret = _hooks(env, monkeypatch, [])
    offer = env["client"].post("/api/v1/ott/studio/commerce/offers", headers=OWNER, json={
        "kind": "tvod", "name": "Own it", "price_cents": 999, "title_id": env["ids"][0]}).json()["data"]
    payload = json.dumps({"type": "entitlement.granted", "data": {
        "id": "ent_1", "seller": products.seller_id(env["cid"]), "kind": "granted", "reason": None,
        "buyer_ref": env["viewer"]["viewer"]["id"], "sku": offer["sku"], "provider": "dodo",
        "provider_event_id": "pay_1", "occurred_at_ms": int(time.time() * 1000), "expires_at_ms": None}}).encode()
    ts = str(int(time.time()))
    sig = "v1," + standard_webhooks.sign(WHSEC, "ent_1", ts, payload)
    res = env["client"].post("/api/v1/ott/webhooks/mint", content=payload, headers={
        "webhook-id": "ent_1", "webhook-timestamp": ts, "webhook-signature": sig, "content-type": "application/json"})
    assert res.json()["data"]["outcome"] == "granted"
    granted = [json.loads(p["body"]) for p in posted]
    assert [g["event_type"] for g in granted] == ["ott.purchase.granted"]
    assert granted[0]["sku"] == offer["sku"] and granted[0]["event_id"] == "ott.purchase.granted:ent_1"
    assert env["viewer"]["viewer"]["id"] not in posted[0]["body"].decode()
    assert "price" not in granted[0] and "amount" not in granted[0]
    # The same Mint event again: duplicate, no second webhook.
    env["client"].post("/api/v1/ott/webhooks/mint", content=payload, headers={
        "webhook-id": "ent_1", "webhook-timestamp": ts, "webhook-signature": sig, "content-type": "application/json"})
    assert len(posted) == 1

    with env["factory"]() as s:
        stream = OttLiveStream(channel_id=env["cid"], title="Friday stream", path="mayalive", key_hash="x" * 64)
        s.add(stream)
        s.commit()
    with env["factory"]() as s:
        live.on_ready(s, live.PATH_PREFIX + "mayalive")
        s.commit()
    with env["factory"]() as s:
        live.on_ready(s, live.PATH_PREFIX + "mayalive")  # already live: no second event
        s.commit()
    started = [json.loads(p["body"]) for p in posted[1:]]
    assert [e["event_type"] for e in started] == ["ott.live.started"]
    assert started[0]["url"].endswith(f"/c/maya/live/{stream.id}")
    assert all(_signed_ok(p, secret) for p in posted)


def test_event_types_are_subscribable():
    from app.models.schema import WEBHOOK_EVENT_TYPES

    assert set(events.EVENT_TYPES) <= set(WEBHOOK_EVENT_TYPES)
    from app.workers.celery_app import OPTIONAL_TASK_MODULES

    assert "app.domains.ott.events" in OPTIONAL_TASK_MODULES


# --------------------------------------------------------------------------- #
# 4. Cast and crew in the studio and MRSS out
# --------------------------------------------------------------------------- #
def test_credits_in_studio_and_mrss(env):
    # Feeds list free titles only, so the free channel (noor) carries the credits.
    t0, noor_owner = env["other_ids"][0], {"x-api-key": "k2"}
    res = env["client"].patch(f"/api/v1/ott/studio/titles/{t0}", headers=noor_owner, json={"credits": [
        {"name": "Ana Lee", "role": "Director"}, {"name": "Sam Ortiz", "role": "Host"}]})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["credits"] == [{"name": "Ana Lee", "role": "Director"},
                                             {"name": "Sam Ortiz", "role": "Host"}]
    too_many = env["client"].patch(f"/api/v1/ott/studio/titles/{t0}", headers=noor_owner,
                                   json={"credits": [{"name": f"P{n}", "role": "Crew"} for n in range(31)]})
    assert too_many.status_code == 422
    xml = env["client"].get("/api/v1/ott/c/noor/mrss.xml")
    assert xml.status_code == 200
    root = ET.fromstring(xml.content)
    ns = {"media": "http://search.yahoo.com/mrss/"}
    credits = [(c.text, c.get("role"), c.get("scheme")) for c in root.iter(f"{{{ns['media']}}}credit")]
    assert ("Ana Lee", "director", "urn:ebu") in credits and ("Sam Ortiz", "host", "urn:ebu") in credits


# --------------------------------------------------------------------------- #
# 5. Push: opted-in viewers only, new episode or live start only
# --------------------------------------------------------------------------- #
def test_push_reaches_only_opted_in_viewers_with_episode_or_live(env, monkeypatch):
    batches: list[list[dict]] = []
    monkeypatch.setattr(push, "_post_batch", lambda messages: batches.append(messages) or [
        {"status": "ok"} for _ in messages])
    c = env["client"]
    assert c.put("/api/v1/ott/viewers/maya/push", headers=_vh(env), json={
        "token": TOKEN_A, "platform": "ios", "topics": ["episodes"]}).json()["data"]["topics"] == ["episodes"]
    second = c.post("/api/v1/ott/viewers/maya/session",
                    json={"access_token": h.auth_token("sub-w", "w@example.com")}).json()["data"]["session"]
    c.put("/api/v1/ott/viewers/maya/push", headers={"x-ott-viewer": second}, json={
        "token": TOKEN_B, "platform": "android", "topics": ["live"]})
    assert c.put("/api/v1/ott/viewers/maya/push", headers=_vh(env), json={
        "token": "not-a-token-at-all-xxxxxxx", "platform": "ios", "topics": ["episodes"]}).status_code == 400
    assert c.put("/api/v1/ott/viewers/maya/push", headers=_vh(env), json={
        "token": TOKEN_A, "platform": "ios", "topics": ["promos"]}).status_code == 400

    with env["factory"]() as s:
        draft = OttTitle(channel_id=env["cid"], title="Episode four", kind="episode", genres=[], geo_countries=[],
                         status="draft", package_status="ready", duration_s=600, access_tier="free", position=6)
        s.add(draft)
        s.commit()
        draft_id = draft.id
    c.post(f"/api/v1/ott/studio/titles/{draft_id}/publish", headers=OWNER)
    assert [[m["to"] for m in b] for b in batches] == [[TOKEN_A]]
    message = batches[0][0]
    assert message["title"] == "New on Maya" and message["body"] == "Episode four"
    assert message["data"] == {"handle": "maya", "kind": "episode", "title_id": draft_id}

    with env["factory"]() as s:
        s.add(OttLiveStream(channel_id=env["cid"], title="Q and A", path="mayaqa", key_hash="y" * 64))
        s.commit()
    with env["factory"]() as s:
        live.on_ready(s, live.PATH_PREFIX + "mayaqa")
        s.commit()
    assert [m["to"] for m in batches[1]] == [TOKEN_B]
    assert batches[1][0]["title"] == "Maya is live" and batches[1][0]["data"]["kind"] == "live"
    assert set(batches[1][0]) == {"to", "title", "body", "data", "sound"}

    assert c.request("DELETE", "/api/v1/ott/viewers/maya/push", headers=_vh(env), json={"token": TOKEN_A}).json()[
        "data"]["removed"] == 1


def test_watchlist_migration_is_additive_and_idempotent():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    path = next((REPO / "migrations/versions").glob("*_a4d6f8b0c2e6_ott_watchlist.py"))
    spec = importlib.util.spec_from_file_location("ott_watchlist_mig", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE ott_titles (id VARCHAR(32) PRIMARY KEY, title VARCHAR(120))"))
        conn.execute(text("INSERT INTO ott_titles (id, title) VALUES ('t1', 'Old title')"))
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        module.upgrade()
        insp = inspect(conn)
        assert {"ott_watchlist", "ott_ratings", "ott_viewer_push"} <= set(insp.get_table_names())
        assert "credits" in {c["name"] for c in insp.get_columns("ott_titles")}
        assert conn.execute(text("SELECT credits FROM ott_titles WHERE id = 't1'")).scalar_one() == "[]"
        module.downgrade()
        module.downgrade()
        assert "ott_watchlist" not in inspect(conn).get_table_names()
        assert "credits" not in {c["name"] for c in inspect(conn).get_columns("ott_titles")}


def test_events_skip_workspaces_the_owner_only_belongs_to(env, monkeypatch):
    """QM verify: a seat in someone else's team must not route this channel's events there."""
    posted, _secret = _hooks(env, monkeypatch, [200])
    other = "https://93.184.216.35/their-hook"
    with env["factory"]() as s:
        theirs = Workspace(owner_id=env["owner"], name="Their team")
        s.add(theirs)
        s.flush()
        s.add(WorkspaceMember(workspace_id=theirs.id, user_id=env["owner"], role="editor"))
        webhook_subscriptions.create(s, theirs.id, other, list(events.EVENT_TYPES))
        draft = OttTitle(channel_id=env["cid"], title="Episode four", kind="episode", genres=[], geo_countries=[],
                         status="draft", package_status="ready", duration_s=600, access_tier="free", position=6,
                         manifest_key="ott/x/master.m3u8")
        s.add(draft)
        s.commit()
        draft_id = draft.id
    assert env["client"].post(f"/api/v1/ott/studio/titles/{draft_id}/publish", headers=OWNER).status_code == 200
    assert [p["url"] for p in posted] == [HOOK_URL]


def test_rating_read_is_scoped_to_the_viewers_channel(env):
    """QM verify: the ratings of a title on another channel are not readable from this one."""
    res = env["client"].get(f"/api/v1/ott/viewers/maya/ratings/{env['other_ids'][0]}", headers=_vh(env))
    assert res.status_code == 404
    own = env["client"].get(f"/api/v1/ott/viewers/maya/ratings/{env['ids'][0]}", headers=_vh(env))
    assert own.status_code == 200 and own.json()["data"]["count"] == 0


def test_a_refresh_with_the_current_token_keeps_the_stream_session(env):
    """QM verify: the cast receiver's refresh does not take a second stream slot mid-title."""
    title = env["ids"][0]
    with env["factory"]() as s:
        s.get(OttTitle, title).access_tier = "free"
        s.commit()
    first = env["client"].post(f"/api/v1/ott/play/{title}", json={"viewer_id": "dev-1"}, headers=_vh(env))
    assert first.status_code == 200, first.text
    grant = first.json()["data"]
    token = grant["manifest_url"].split("/ott/stream/")[1].split("/")[0]
    again = env["client"].post(f"/api/v1/ott/play/{title}", json={"viewer_id": "dev-1", "previous_token": token},
                               headers=_vh(env)).json()["data"]
    assert again["session_id"] == grant["session_id"]
    fresh = env["client"].post(f"/api/v1/ott/play/{title}", json={"viewer_id": "dev-1"}, headers=_vh(env))
    assert fresh.json()["data"]["session_id"] != grant["session_id"]
    other = env["client"].post(f"/api/v1/ott/play/{env['ids'][1]}", json={"previous_token": token}, headers=_vh(env))
    if other.status_code == 200:  # a token for another title never carries its session over
        assert other.json()["data"]["session_id"] != grant["session_id"]
