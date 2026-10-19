"""Wave P PM3.1: MV6 viewer accounts and MV7 OTT plans and meters.

1. A viewer of channel A is not a viewer of channel B without signing in
   there; resume works across web and mobile; deleting a viewer deletes their
   history.
2. OTT meters (GB stored, minutes delivered, encode minutes, AI minutes) post
   hourly to Dodo and Rago, idempotent; overage off until opted in.
3. Until OD-MV2, OTT is included in existing plans with caps (not sellable).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app.domains.ott_access import limits, router as access_router, tokens
from app.domains.ott_viewers import auth, router as viewers_router, session as viewer_session
from app.domains.ott_viewers.models import OttUsageHour, OttViewer, OttWatchProgress
from app.integrations.railyard.meters import MeterOutbox
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.dodo_usage_event import DodoUsageEvent
from app.services.billing import ott_plans, ott_usage
from app.services.ott_transcode.models import DONE, OttEncodeJob

from tests.reelforge import _wp_p3_ott as h


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (viewers_router, access_router))
    h.enable(monkeypatch, "viewers", "storefront", "plans")
    monkeypatch.setenv(auth.SECRET_ENV, h.AUTH_SECRET)
    monkeypatch.setenv(viewer_session.SECRET_ENV, h.VIEWER_SECRET)
    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    monkeypatch.setattr(limits, "_STORE", limits.MemoryStore())
    limited = []
    monkeypatch.setattr(viewers_router, "enforce_rate_limit", lambda request, bucket, limit, window: limited.append(
        (bucket, limit, window)))
    owner_id = h.owner(factory)
    a = h.channel(factory, owner_id, "alpha")
    other = h.owner(factory, "b@example.com", "b-key")
    b = h.channel(factory, other, "beta")
    return {"factory": factory, "owner": owner_id, "a": a, "b": b, "other": other, "limited": limited}


def _sign_in(client, handle, token, device="web"):
    return client.post(f"/api/v1/ott/viewers/{handle}/session", json={"access_token": token, "device": device})


# --------------------------------------------------------------------------- #
# Scribase Auth token checks
# --------------------------------------------------------------------------- #
def test_scribase_auth_token_rules():
    env = {auth.SECRET_ENV: h.AUTH_SECRET}
    ident = auth.verify(h.auth_token("sub-1", "Ana@Example.com"), env)
    assert ident == auth.Identity(subject="sub-1", email="ana@example.com")
    for bad in (h.auth_token("s", "a@x.io", aud="anon"), h.auth_token("s", "a@x.io", ttl=-120),
                h.auth_token("s", "a@x.io", secret="another-secret-that-is-long-enough-000"),
                jwt.encode({"sub": "s", "aud": "authenticated", "exp": int(time.time()) + 60}, h.AUTH_SECRET),
                "not-a-token"):
        with pytest.raises(auth.AuthRefused):
            auth.verify(bad, env)
    with pytest.raises(auth.AuthRefused, match="not configured"):
        auth.verify(h.auth_token("s", "a@x.io"), {})
    with pytest.raises(auth.AuthRefused):
        auth.verify(h.auth_token("s", "a@x.io", iss="https://evil"), {**env, auth.ISSUER_ENV: "https://scribase"})


def test_scribase_auth_accepts_asymmetric_tokens_through_jwks(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode({"sub": "s2", "email": "e@x.io", "aud": "authenticated", "exp": int(time.time()) + 60},
                       key, algorithm="ES256", headers={"kid": "k1"})

    class Client:
        def get_signing_key_from_jwt(self, raw):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr(auth, "_jwks_client", lambda url: Client())
    assert auth.verify(token, {auth.JWKS_ENV: "https://sb.example/auth/v1/.well-known/jwks.json"}).subject == "s2"
    with pytest.raises(auth.AuthRefused):  # an asymmetric token needs the JWKS setting
        auth.verify(token, {auth.SECRET_ENV: h.AUTH_SECRET})


# --------------------------------------------------------------------------- #
# MV6: isolation, resume, delete
# --------------------------------------------------------------------------- #
def test_a_viewer_of_channel_a_is_not_a_viewer_of_channel_b(env):
    client = h.app_client(viewers_router.router)
    token = h.auth_token("sub-ana", "ana@example.com")
    signed = _sign_in(client, "alpha", token)
    assert signed.status_code == 200 and signed.headers["cache-control"].startswith("no-store")
    session_a = signed.json()["data"]["session"]
    assert client.get("/api/v1/ott/viewers/alpha/me", headers={"x-ott-viewer": session_a}).status_code == 200
    refused = client.get("/api/v1/ott/viewers/beta/me", headers={"x-ott-viewer": session_a})
    assert refused.status_code == 401 and "Sign in to this channel" in refused.json()["message"]
    _cid_b, b_titles = env["b"]
    wrong = client.put(f"/api/v1/ott/viewers/alpha/progress/{b_titles[0]}", json={"position_s": 5},
                       headers={"x-ott-viewer": session_a})
    assert wrong.status_code == 404
    session_b = _sign_in(client, "beta", token).json()["data"]["session"]
    assert client.get("/api/v1/ott/viewers/beta/me", headers={"x-ott-viewer": session_b}).status_code == 200
    with env["factory"]() as s:
        rows = s.execute(select(OttViewer)).scalars().all()
    assert len(rows) == 2 and len({r.channel_id for r in rows}) == 2 and {r.auth_subject for r in rows} == {"sub-ana"}


def test_resume_works_across_web_and_mobile(env):
    client = h.app_client(viewers_router.router)
    token = h.auth_token("sub-ana", "ana@example.com")
    web = _sign_in(client, "alpha", token, "web").json()["data"]
    phone = _sign_in(client, "alpha", h.auth_token("sub-ana", "ana@example.com"), "ios").json()["data"]
    assert web["created"] is True and phone["created"] is False and web["viewer"]["id"] == phone["viewer"]["id"]
    _cid, titles = env["a"]
    saved = client.put(f"/api/v1/ott/viewers/alpha/progress/{titles[0]}",
                       json={"position_s": 312.4, "duration_s": 600, "device": "web"},
                       headers={"x-ott-viewer": web["session"]})
    assert saved.status_code == 200
    resume = client.get(f"/api/v1/ott/viewers/alpha/progress/{titles[0]}",
                        headers={"x-ott-viewer": phone["session"]}).json()["data"]
    assert resume["position_s"] == 312.4 and resume["device"] == "web"
    client.put(f"/api/v1/ott/viewers/alpha/progress/{titles[0]}", json={"position_s": 330, "device": "ios"},
               headers={"x-ott-viewer": phone["session"]})
    items = client.get("/api/v1/ott/viewers/alpha/continue", headers={"x-ott-viewer": web["session"]}
                       ).json()["data"]["items"]
    assert [(i["title_id"], i["position_s"], i["device"]) for i in items] == [(titles[0], 330.0, "ios")]
    # Finished titles leave "continue watching" and resume from the start.
    client.put(f"/api/v1/ott/viewers/alpha/progress/{titles[0]}", json={"position_s": 590, "device": "tv"},
               headers={"x-ott-viewer": phone["session"]})
    assert client.get("/api/v1/ott/viewers/alpha/continue", headers={"x-ott-viewer": web["session"]}
                      ).json()["data"]["items"] == []
    again = client.get(f"/api/v1/ott/viewers/alpha/progress/{titles[0]}", headers={"x-ott-viewer": web["session"]})
    assert again.json()["data"]["finished"] is True and again.json()["data"]["position_s"] == 0.0


def test_deleting_a_viewer_deletes_their_history_and_sessions(env):
    client = h.app_client(viewers_router.router)
    data = _sign_in(client, "alpha", h.auth_token("sub-ana", "ana@example.com")).json()["data"]
    _cid, titles = env["a"]
    for title in titles:
        client.put(f"/api/v1/ott/viewers/alpha/progress/{title}", json={"position_s": 10},
                   headers={"x-ott-viewer": data["session"]})
    deleted = client.delete("/api/v1/ott/viewers/alpha/me", headers={"x-ott-viewer": data["session"]})
    assert deleted.json()["data"] == {"deleted": True, "history_deleted": 2, "purchases_ended": 0}
    with env["factory"]() as s:
        assert s.execute(select(OttWatchProgress)).scalars().all() == []
        assert s.execute(select(OttViewer)).scalars().all() == []
    assert client.get("/api/v1/ott/viewers/alpha/me", headers={"x-ott-viewer": data["session"]}).status_code == 401


def test_sign_out_everywhere_and_rename(env):
    client = h.app_client(viewers_router.router)
    token = h.auth_token("sub-ana", "ana@example.com")
    one = _sign_in(client, "alpha", token).json()["data"]["session"]
    two = _sign_in(client, "alpha", token, "tv").json()["data"]["session"]
    renamed = client.patch("/api/v1/ott/viewers/alpha/me", json={"display_name": "  Ana   K "},
                           headers={"x-ott-viewer": one})
    assert renamed.json()["data"]["display_name"] == "Ana K"
    assert client.post("/api/v1/ott/viewers/alpha/sign-out", headers={"x-ott-viewer": two}).status_code == 200
    for stale in (one, two):
        assert client.get("/api/v1/ott/viewers/alpha/me", headers={"x-ott-viewer": stale}).status_code == 401


def test_sign_in_refusals(env, monkeypatch):
    client = h.app_client(viewers_router.router)
    _sign_in(client, "alpha", "x" * 20)
    assert env["limited"] == [("ott:viewer-sign-in", 10, 60)]
    bad = _sign_in(client, "alpha", h.auth_token("s", "a@x.io", secret="another-secret-that-is-long-enough-000"))
    assert bad.status_code == 401 and "new code" in bad.json()["message"]
    assert _sign_in(client, "nobody", h.auth_token("s", "a@x.io")).status_code == 404
    monkeypatch.setenv(viewer_session.SECRET_ENV, "short")
    assert _sign_in(client, "alpha", h.auth_token("s", "a@x.io")).status_code == 503


def test_viewer_routes_404_until_the_flag(env, monkeypatch):
    monkeypatch.delenv("OTT_VIEWERS_LIVE")
    client = h.app_client(viewers_router.router)
    assert _sign_in(client, "alpha", h.auth_token("s", "a@x.io")).status_code == 404


def test_signed_in_viewer_streams_as_that_viewer(env, monkeypatch):
    client = h.app_client(viewers_router.router, access_router.router)
    signed = _sign_in(client, "alpha", h.auth_token("sub-ana", "ana@example.com"))
    assert signed.status_code == 200, signed.text
    data = signed.json()["data"]
    _cid, titles = env["a"]
    assert client.post(f"/api/v1/ott/play/{titles[0]}", json={},
                       headers={"x-ott-viewer": data["session"]}).status_code == 200
    assert list(limits._STORE.sessions) == [f"viewer:{data['viewer']['id']}"]


# --------------------------------------------------------------------------- #
# MV7: plans, caps and hourly meters
# --------------------------------------------------------------------------- #
NOW = datetime(2026, 10, 14, 10, 30, tzinfo=timezone.utc)
HOUR = "2026-10-14T09"


def _subscribe(factory, user_id, plan="creator", customer="cus_1"):
    with factory() as s:
        s.add(CreatorSubscription(user_id=user_id, plan_key=plan, provider="dodo", status="active",
                                  customer_ref=customer, current_period_end=NOW + timedelta(days=10)))
        s.commit()


def _encode(factory, user_id, minutes, at):
    with factory() as s:
        s.add(OttEncodeJob(title_id="t", user_id=user_id, source_key="k", source_seconds=minutes * 60, lane="mac",
                           status=DONE, finished_at=at))
        s.commit()


def test_hourly_meters_post_to_rago_and_dodo_once(env):
    factory = env["factory"]
    _subscribe(factory, env["owner"])
    cid, _ = env["a"]
    counter = ott_usage.MemoryCounter()
    ott_usage.set_counter(counter)
    try:
        start = ott_usage.hour_start(HOUR).timestamp()
        for _ in range(90):  # 90 segments of 2 s = 3 minutes delivered
            ott_usage.count_delivered(cid, now=start + 60)
        ott_usage.count_ai_minutes(env["owner"], 4.0, now=start + 120)
        _encode(factory, env["owner"], 12, ott_usage.hour_start(HOUR) + timedelta(minutes=20))
        _encode(factory, env["owner"], 99, ott_usage.hour_start(HOUR) + timedelta(hours=1, minutes=1))  # next hour
        mine = {f"ott-uploads/{env['owner']}/": 3 * ott_usage.GB, f"ott/{cid}/": ott_usage.GB // 2}
        sizer = lambda prefix: mine.get(prefix, 0)
        with factory() as s:
            first = ott_usage.run_hour(s, HOUR, sizer=sizer)
            s.commit()
        with factory() as s:
            second = ott_usage.run_hour(s, HOUR, sizer=sizer)
            s.commit()
            rows = {r.meter: r for r in s.execute(select(OttUsageHour)).scalars()}
            outbox = {r.transaction_id: r.payload for r in s.execute(select(MeterOutbox)).scalars()}
            dodo = {r.event_id: r for r in s.execute(select(DodoUsageEvent)).scalars()}
    finally:
        ott_usage.set_counter(None)
    assert first == {"rows": 4, "rago": 4, "dodo": 4} and second == {"rows": 0, "rago": 0, "dodo": 0}
    assert rows["minutes_delivered"].quantity == pytest.approx(3.0)
    assert rows["encode_minutes"].quantity == pytest.approx(12.0)
    assert rows["ai_minutes"].quantity == pytest.approx(4.0)
    assert rows["gb_stored"].quantity == pytest.approx(3.5)
    owner = env["owner"]
    assert outbox[f"menivor:ott.minutes_delivered:{owner}:{HOUR}"]["code"] == "menivor.ott.minutes_delivered"
    assert outbox[f"menivor:ai.minutes:{owner}:{HOUR}"]["properties"]["quantity"] == pytest.approx(4.0)
    event = dodo[f"ott_encode_minutes_{owner}_{HOUR}"]
    assert event.customer_id == "cus_1" and event.event_name == "ott.encode_minutes"
    assert event.meta["quantity"] == pytest.approx(12.0) and event.overage is False


def test_nothing_past_the_cap_is_billed_until_opt_in(env):
    factory = env["factory"]
    owner = env["owner"]
    _subscribe(factory, owner, plan="creator")  # 300 encode minutes included (target)
    with factory() as s:
        s.add(OttUsageHour(user_id=owner, hour="2026-10-02T09", meter="encode_minutes", quantity=290, billable=290))
        s.commit()
    _encode(factory, owner, 25, ott_usage.hour_start(HOUR) + timedelta(minutes=5))
    ott_usage.set_counter(ott_usage.MemoryCounter())
    try:
        with factory() as s:
            ott_usage.run_hour(s, HOUR)
            s.commit()
            row = s.execute(select(OttUsageHour).where(OttUsageHour.hour == HOUR)).scalar_one()
            event = s.execute(select(DodoUsageEvent)).scalar_one()
            assert row.quantity == pytest.approx(25) and row.billable == pytest.approx(10)
            assert event.meta["quantity"] == pytest.approx(10)
            assert ott_plans.over_cap(s, owner, "encode_minutes", now=NOW) is True
            ott_plans.set_overage(s, owner, True)
            assert ott_plans.over_cap(s, owner, "encode_minutes", now=NOW) is False
            s.commit()
        _encode(factory, owner, 6, ott_usage.hour_start("2026-10-14T10") + timedelta(minutes=5))
        with factory() as s:
            ott_usage.run_hour(s, "2026-10-14T10")
            s.commit()
            late = s.execute(select(DodoUsageEvent).where(DodoUsageEvent.event_id.like("%T10"))).scalar_one()
            assert late.meta["quantity"] == pytest.approx(6) and late.overage is True
    finally:
        ott_usage.set_counter(None)


def test_creators_without_a_dodo_plan_go_to_rago_only(env):
    factory = env["factory"]
    _encode(factory, env["owner"], 3, ott_usage.hour_start(HOUR) + timedelta(minutes=5))
    ott_usage.set_counter(ott_usage.MemoryCounter())
    try:
        with factory() as s:
            assert ott_usage.run_hour(s, HOUR) == {"rows": 1, "rago": 1, "dodo": 0}
    finally:
        ott_usage.set_counter(None)


def test_delivered_seconds_are_counted_per_segment_not_for_manifests(env, monkeypatch):
    from app.domains.ott_access import service as access

    counted = []
    monkeypatch.setattr(ott_usage, "count_delivered", lambda cid, seconds, now=None: counted.append((cid, seconds)))
    monkeypatch.setattr(ott_usage, "_COUNTER", ott_usage.MemoryCounter())  # segment dedupe (verifier fix)
    cid, titles = env["a"]
    token, _grant = tokens.issue(titles[0], "device:x", "TR")
    with env["factory"]() as s:
        access.segment_url(s, token, "v_720p/1.m4s", lambda key, ttl: f"https://r2/{key}")
        access.segment_url(s, token, "v_720p/init.mp4", lambda key, ttl: f"https://r2/{key}")
    assert counted == [(cid, ott_usage.SEGMENT_S)]


def test_a_counter_outage_never_blocks_playback(monkeypatch):
    class Broken:
        def add(self, key, amount):
            raise ConnectionError("redis down")

    ott_usage.set_counter(Broken())
    try:
        ott_usage.count_delivered("c1")  # no exception
    finally:
        ott_usage.set_counter(None)


def test_plan_view_shows_caps_as_targets_and_overage_off(env):
    with env["factory"]() as s:
        view = ott_plans.plan_view(s, env["owner"], now=NOW)
    assert view["plan"] == "free" and view["overage"]["opted_in"] is False and view["ott_plans_sellable"] is False
    storage = next(m for m in view["meters"] if m["meter"] == "gb_stored")
    assert storage["included"] == 2 * 31 * 24 and storage["cap_is_target"] is True and storage["unit"] == "GB-hours"


def test_plan_routes_and_upload_cap(env, monkeypatch):
    from app.services.ott_transcode import router as transcode_router

    h.patch_sessions(monkeypatch, env["factory"], (transcode_router,))
    h.enable(monkeypatch, "upload")
    monkeypatch.setattr(transcode_router, "storage", lambda: type("S", (), {"ott": type("O", (), {
        "create": staticmethod(lambda key, ct: "upload-1")})()})())
    client = h.app_client(ott_plans.router, transcode_router.router)
    auth_h = {"x-api-key": h.OWNER_KEY}
    assert client.get("/api/v1/ott/studio/plan", headers=auth_h).json()["data"]["plan"] == "free"
    with env["factory"]() as s:
        month = f"{datetime.now(timezone.utc):%Y-%m}"
        s.add(OttUsageHour(user_id=env["owner"], hour=f"{month}-01T00", meter="encode_minutes", quantity=30,
                           billable=30))
        s.commit()
    body = {"filename": "film.mp4", "size_bytes": 10_000_000, "content_type": "video/mp4"}
    blocked = client.post("/api/v1/ott/uploads", json=body, headers=auth_h)
    assert blocked.status_code == 402 and "overage" in blocked.json()["message"]
    opted = client.post("/api/v1/ott/studio/plan/overage", json={"opt_in": True}, headers=auth_h)
    assert opted.json()["data"]["overage"]["opted_in"] is True
    assert client.post("/api/v1/ott/uploads", json=body, headers=auth_h).status_code == 200
    monkeypatch.delenv("OTT_PLANS_LIVE")
    assert client.get("/api/v1/ott/studio/plan", headers=auth_h).status_code == 404


def test_hourly_beat_is_registered():
    from app.services.billing import ott_usage_tasks

    entry = ott_usage_tasks.BEAT_SCHEDULE["menivor-ott-usage-hourly"]
    assert entry["task"] == ott_usage_tasks.USAGE_TASK and entry["schedule"].minute == {5}


def test_due_hours_never_include_the_current_hour():
    hours = ott_usage.due_hours(None, now=NOW, back=2)
    assert hours == ["2026-10-14T08", "2026-10-14T09"]
