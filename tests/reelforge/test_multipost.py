"""Multi-account publishing: pacing, OAuth + tokens, campaigns, queue runner, webhooks, HTTP.

Platform clients run against a fake :class:`Transport` that records each request
(the network is the only thing faked). Services run on in-memory SQLite with the
real encryption, state, pacing and queue code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.multipost import accounts as acct
from app.domains.multipost import campaigns as camp
from app.domains.multipost import media as media_mod
from app.domains.multipost import oauth, pacing, runner, settings, webhooks
from app.domains.multipost.clients import instagram as ig
from app.domains.multipost.clients import tiktok as tt
from app.domains.multipost.clients import youtube as yt
from app.domains.multipost.clients.base import AuthError, ClientError, PostSpec, RateLimited
from app.domains.multipost.models import MultipostAccount, MultipostPost
from app.models.const import TASK_STATE_COMPLETE, TASK_STATE_PROCESSING
from app.models.db.base import Base
from app.models.db.models import Job, User, Workspace, WorkspaceMember
from app.services import crypto_tokens

UTC = timezone.utc
T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Fake network
# --------------------------------------------------------------------------- #
class Resp:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._body

    @property
    def text(self):
        return json.dumps(self._body)


class FakeTransport:
    """Routes by (method, url prefix); each route is a list of responses used in order."""

    def __init__(self, routes=None):
        self.routes = {k: list(v) for k, v in (routes or {}).items()}
        self.calls = []

    def add(self, method, prefix, *responses):
        self.routes.setdefault((method, prefix), []).extend(responses)

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "params": params or {},
                           "json": json, "data": data})
        matches = [k for k in self.routes if k[0] == method and url.startswith(k[1])]
        if not matches:
            raise AssertionError(f"unexpected request {method} {url}")
        key = max(matches, key=lambda k: len(k[1]))
        queue = self.routes[key]
        if not queue:
            raise AssertionError(f"no response left for {method} {url}")
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def find(self, method, prefix):
        return [c for c in self.calls if c["method"] == method and c["url"].startswith(prefix)]


class FakeMedia:
    def __init__(self, path, state=media_mod.READY):
        self.path = path
        self.states = {}
        self.default = state

    def state(self, user_id, job_id):
        return self.states.get(job_id, self.default)

    def video_url(self, user_id, job_id):
        return f"https://cdn.menivor.test/{job_id}.mp4"

    def download(self, user_id, job_id):
        return self.path


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-multipost-key")
    monkeypatch.setenv("MULTIPOST_OAUTH_REDIRECT_URL", "https://menivor.test/autopost/callback")
    for p in ("TIKTOK", "INSTAGRAM", "YOUTUBE"):
        monkeypatch.setenv(f"MULTIPOST_{p}_CLIENT_ID", f"{p.lower()}-id")
        monkeypatch.setenv(f"MULTIPOST_{p}_CLIENT_SECRET", f"{p.lower()}-secret")
    for name in ("MULTIPOST_TIKTOK_AUDITED", "MULTIPOST_YOUTUBE_VERIFIED", "MULTIPOST_TIKTOK_SOURCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(media_mod, "content_gate", lambda provider, title, caption: (True, ""))


@pytest.fixture()
def db(env, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(runner, "get_session", _session)
    Factory.scope = _session
    return Factory


@pytest.fixture()
def video(tmp_path):
    path = tmp_path / "reel.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 4000)
    return str(path)


def _user(Factory, email="a@example.com") -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=hashlib.sha256(email.encode()).hexdigest(), credits=0)
        s.add(u)
        s.commit()
        return u.id


def _job(Factory, user_id, state=TASK_STATE_COMPLETE) -> str:
    with Factory() as s:
        j = Job(user_id=user_id, state=state, result_key="results/final.mp4", params={})
        s.add(j)
        s.commit()
        return j.id


def _account(Factory, user_id, provider="tiktok", ext="open-1", *, expires_in=timedelta(hours=20),
             refresh="rt", handle="", **extra) -> str:
    with Factory() as s:
        row = MultipostAccount(
            user_id=user_id, provider=provider, external_account_id=ext, handle=handle or ext,
            display_name=f"{provider} {ext}", access_token_enc=crypto_tokens.encrypt(f"at-{ext}"),
            refresh_token_enc=crypto_tokens.encrypt(refresh) if refresh else None,
            token_expires_at=datetime.now(UTC) + expires_in, **extra,
        )
        s.add(row)
        s.commit()
        return row.id


def _campaign(Factory, uid, job_ids, account_ids, **kw):
    data = camp.CampaignInput(job_ids=tuple(job_ids), account_ids=tuple(account_ids),
                              visibility=kw.pop("visibility", "public"), **kw)
    with Factory.scope() as s:
        return camp.create(s, uid, data)


def _make_due(Factory, now):
    with Factory() as s:
        for post in s.execute(select(MultipostPost)).scalars():
            post.scheduled_at = now - timedelta(minutes=1)
            post.next_attempt_at = None
        s.commit()


def _post(Factory, post_id=None):
    with Factory() as s:
        if post_id:
            return s.get(MultipostPost, post_id)
        return s.execute(select(MultipostPost)).scalars().first()


# --------------------------------------------------------------------------- #
# Pacing
# --------------------------------------------------------------------------- #
def _limits(cap=3, gap=60, hours=(), tz="UTC"):
    return pacing.Limits(daily_cap=cap, gap=timedelta(minutes=gap), hours=tuple(hours), tz=tz)


def test_effective_limits_clamp_into_platform_range():
    lim = pacing.effective_limits(daily_cap=99, gap_minutes=1, platform_cap=15, default_cap=4, default_gap=120,
                                  gap_floor=15, hours=[9, 9, 25, 10], tz="Nowhere/Zone")
    assert lim.daily_cap == 15 and lim.gap == timedelta(minutes=15)
    assert lim.hours == (9, 10) and lim.tz == "UTC"
    default = pacing.effective_limits(daily_cap=0, gap_minutes=0, platform_cap=15, default_cap=4,
                                      default_gap=120, gap_floor=15)
    assert default.daily_cap == 4 and default.gap == timedelta(minutes=120)


def test_check_enforces_spacing_and_rolling_daily_cap():
    lim = _limits(cap=2, gap=60)
    assert pacing.check(T0, [], lim).allowed
    near = pacing.check(T0, [T0 - timedelta(minutes=30)], lim)
    assert not near.allowed and near.reason == "spacing" and near.next_at == T0 + timedelta(minutes=30)
    taken = [T0 - timedelta(hours=10), T0 - timedelta(hours=5)]
    capped = pacing.check(T0, taken, lim)
    assert not capped.allowed and "daily_cap" in capped.reason
    # The oldest post must age out of the rolling 24 h window first.
    assert capped.next_at == T0 - timedelta(hours=10) + pacing.DAY


def test_check_counts_future_posts_inside_the_window():
    lim = _limits(cap=2, gap=10)
    taken = [T0 + timedelta(hours=1), T0 + timedelta(hours=2)]
    verdict = pacing.check(T0, taken, lim)
    assert not verdict.allowed
    assert verdict.next_at >= T0 + timedelta(hours=1) + pacing.DAY


def test_posting_hours_respect_the_account_time_zone():
    lim = _limits(cap=5, gap=10, hours=(9, 10), tz="Europe/Istanbul")  # UTC+3
    late = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)  # 23:00 local
    verdict = pacing.check(late, [], lim)
    assert not verdict.allowed and verdict.reason == "posting_hours"
    assert verdict.next_at == datetime(2026, 10, 7, 6, 0, tzinfo=UTC)  # 09:00 local next day


def test_plan_spread_balances_accounts_and_never_breaks_caps():
    accounts = [pacing.AccountPlan("a", _limits(cap=2, gap=60)), pacing.AccountPlan("b", _limits(cap=2, gap=60))]
    jobs = [f"j{i}" for i in range(6)]
    slots = pacing.plan(jobs, accounts, T0)
    assert [s[0] for s in slots] == jobs
    per = {"a": [], "b": []}
    for _, account_id, at in slots:
        per[account_id].append(at)
    assert len(per["a"]) == 3 and len(per["b"]) == 3
    for times in per.values():
        for at in times:
            assert pacing._cap_ok(at, [t for t in times if t != at], _limits(cap=2, gap=60))
            assert pacing._gap_ok(at, [t for t in times if t != at], _limits(cap=2, gap=60))
    assert per["a"][0] == T0 and per["b"][0] == T0
    assert per["a"][2] >= T0 + pacing.DAY  # the third post waits for the window


def test_plan_every_posts_each_video_to_every_account():
    accounts = [pacing.AccountPlan("a", _limits()), pacing.AccountPlan("b", _limits())]
    slots = pacing.plan(["j1", "j2"], accounts, T0, mode="every")
    assert [(j, a) for j, a, _ in slots] == [("j1", "a"), ("j1", "b"), ("j2", "a"), ("j2", "b")]


def test_backoff_grows_and_caps():
    assert [pacing.backoff(n).total_seconds() // 60 for n in (1, 2, 3, 4, 9)] == [5, 15, 45, 135, 360]


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #
def test_authorize_urls(env):
    t = parse_qs(urlparse(oauth.authorize_url("tiktok", "st")).query)
    assert t["client_key"] == ["tiktok-id"] and "video.publish" in t["scope"][0] and t["disable_auto_auth"] == ["1"]
    i = parse_qs(urlparse(oauth.authorize_url("instagram", "st")).query)
    assert i["scope"] == ["instagram_business_basic,instagram_business_content_publish"]
    y = parse_qs(urlparse(oauth.authorize_url("youtube", "st", verifier="v" * 50)).query)
    assert y["access_type"] == ["offline"] and y["code_challenge_method"] == ["S256"]
    assert "select_account" in y["prompt"][0]
    with pytest.raises(oauth.ConnectError):
        oauth.authorize_url("youtube", "st")


def test_missing_developer_app_is_reported_honestly(monkeypatch):
    for name in ("MULTIPOST_TIKTOK_CLIENT_ID", "TIKTOK_CLIENT_ID", "MULTIPOST_TIKTOK_CLIENT_SECRET",
                 "TIKTOK_CLIENT_SECRET", "MULTIPOST_OAUTH_REDIRECT_URL", "WEB_BASE_URL", "SOCIAL_TOKEN_KEY"):
        monkeypatch.delenv(name, raising=False)
    overview = settings.provider_overview("tiktok")
    assert overview["ready"] is False
    assert "MULTIPOST_TIKTOK_CLIENT_ID" in overview["missing_settings"]
    assert any("private" in note for note in overview["notes"])
    with pytest.raises(oauth.ConnectError) as exc:
        oauth.authorize_url("tiktok", "st")
    assert exc.value.status_code == 503


def _tiktok_exchange_routes(t: FakeTransport, open_id="open-1", name="Shop One"):
    t.add("POST", oauth.TOKEN_URLS["tiktok"], Resp(200, {
        "access_token": f"at-{open_id}", "refresh_token": f"rt-{open_id}", "expires_in": 86400,
        "refresh_expires_in": 31536000, "open_id": open_id, "scope": "user.info.basic,video.publish"}))
    t.add("GET", oauth.TIKTOK_USER_URL, Resp(200, {"data": {"user": {
        "open_id": open_id, "display_name": name, "avatar_url": "https://p/a.jpg"}}}))


def test_exchange_instagram_gets_long_lived_token_and_identity(env):
    t = FakeTransport()
    t.add("POST", oauth.TOKEN_URLS["instagram"], Resp(200, {"access_token": "short", "user_id": 77,
                                                            "permissions": ["instagram_business_basic"]}))
    t.add("GET", oauth.IG_LONG_LIVED_URL, Resp(200, {"access_token": "long", "expires_in": 5184000}))
    t.add("GET", oauth.IG_ME_URL, Resp(200, {"user_id": "1784", "username": "shop.ig", "name": "Shop"}))
    grant, ident = oauth.exchange("instagram", "code#_", transport=t)
    assert grant.access_token == "long" and grant.expires_at > datetime.now(UTC) + timedelta(days=59)
    assert ident.external_account_id == "1784" and ident.handle == "shop.ig"
    assert t.find("POST", oauth.TOKEN_URLS["instagram"])[0]["data"]["code"] == "code"


def test_exchange_youtube_reads_the_channel(env):
    t = FakeTransport()
    t.add("POST", oauth.TOKEN_URLS["youtube"], Resp(200, {"access_token": "ya29", "refresh_token": "1//r",
                                                          "expires_in": 3599}))
    t.add("GET", oauth.YT_CHANNELS_URL, Resp(200, {"items": [{"id": "UC1", "snippet": {
        "title": "Shop Channel", "customUrl": "@shop", "thumbnails": {"default": {"url": "https://y/t.jpg"}}}}]}))
    grant, ident = oauth.exchange("youtube", "c", verifier="ver", transport=t)
    assert grant.refresh_token == "1//r" and ident.external_account_id == "UC1" and ident.handle == "@shop"
    assert t.find("POST", oauth.TOKEN_URLS["youtube"])[0]["data"]["code_verifier"] == "ver"
    t2 = FakeTransport()
    t2.add("POST", oauth.TOKEN_URLS["youtube"], Resp(200, {"access_token": "ya29"}))
    t2.add("GET", oauth.YT_CHANNELS_URL, Resp(200, {"items": []}))
    with pytest.raises(oauth.ConnectError):
        oauth.exchange("youtube", "c", verifier="ver", transport=t2)


# --------------------------------------------------------------------------- #
# Accounts + tokens
# --------------------------------------------------------------------------- #
def _connect(Factory, uid, t, provider="tiktok", **kw):
    with Factory.scope() as s:
        started = acct.start_connect(s, uid, provider, **kw)
    state = parse_qs(urlparse(started["authorize_url"]).query)["state"][0]
    with Factory.scope() as s:
        return acct.finish_connect(s, uid, "code", state, transport=t), state


def test_connect_many_tiktok_accounts_with_encrypted_tokens(db):
    uid = _user(db)
    t = FakeTransport()
    _tiktok_exchange_routes(t, "open-1", "Shop One")
    first, state = _connect(db, uid, t)
    t2 = FakeTransport()
    _tiktok_exchange_routes(t2, "open-2", "Shop Two")
    second, _ = _connect(db, uid, t2)
    assert first["id"] != second["id"] and first["display_name"] == "Shop One"
    assert "at-open-1" not in json.dumps(first)
    with db() as s:
        rows = s.execute(select(MultipostAccount)).scalars().all()
        assert len(rows) == 2
        assert all("at-open" not in r.access_token_enc for r in rows)
        assert crypto_tokens.decrypt(rows[0].access_token_enc).startswith("at-open-")
    # The state was single-use.
    with pytest.raises(oauth.ConnectError), db.scope() as s:
        acct.finish_connect(s, uid, "code", state, transport=t)


def test_reconnecting_the_same_account_updates_it(db):
    uid = _user(db)
    t = FakeTransport()
    _tiktok_exchange_routes(t, "open-1", "Old")
    _connect(db, uid, t)
    t2 = FakeTransport()
    _tiktok_exchange_routes(t2, "open-1", "New name")
    again, _ = _connect(db, uid, t2)
    with db() as s:
        assert len(s.execute(select(MultipostAccount)).scalars().all()) == 1
    assert again["display_name"] == "New name" and again["status"] == "connected"


def test_state_is_bound_to_the_user_who_started(db):
    uid, other = _user(db), _user(db, "b@example.com")
    with db.scope() as s:
        started = acct.start_connect(s, uid, "tiktok")
    state = parse_qs(urlparse(started["authorize_url"]).query)["state"][0]
    with pytest.raises(oauth.ConnectError), db.scope() as s:
        acct.finish_connect(s, other, "code", state, transport=FakeTransport())


def test_valid_token_refreshes_near_expiry_and_rotates_refresh_token(db):
    uid = _user(db)
    aid = _account(db, uid, expires_in=timedelta(minutes=10), refresh="old-rt")
    t = FakeTransport()
    t.add("POST", oauth.TOKEN_URLS["tiktok"], Resp(200, {"access_token": "fresh", "refresh_token": "new-rt",
                                                         "expires_in": 86400}))
    with db.scope() as s:
        row = s.get(MultipostAccount, aid)
        assert acct.valid_token(s, row, transport=t) == "fresh"
    sent = t.find("POST", oauth.TOKEN_URLS["tiktok"])[0]["data"]
    assert sent["grant_type"] == "refresh_token" and sent["refresh_token"] == "old-rt"
    with db() as s:
        row = s.get(MultipostAccount, aid)
        assert crypto_tokens.decrypt(row.refresh_token_enc) == "new-rt"
        assert acct.aware(row.token_expires_at) > datetime.now(UTC) + timedelta(hours=23)


def test_failed_refresh_of_an_expired_token_flags_reauth(db):
    uid = _user(db)
    aid = _account(db, uid, expires_in=timedelta(minutes=-5))
    t = FakeTransport()
    t.add("POST", oauth.TOKEN_URLS["tiktok"], Resp(400, {"error": "invalid_grant"}))
    # Callers catch inside the transaction so the flag is committed (as the runner does).
    with db.scope() as s:
        with pytest.raises(oauth.ConnectError) as exc:
            acct.valid_token(s, s.get(MultipostAccount, aid), transport=t)
    assert exc.value.reauth
    with db() as s:
        assert s.get(MultipostAccount, aid).status == "needs_reauth"


def test_failed_refresh_of_a_still_valid_token_keeps_using_it(db):
    uid = _user(db)
    aid = _account(db, uid, expires_in=timedelta(minutes=10))
    t = FakeTransport()
    t.add("POST", oauth.TOKEN_URLS["tiktok"], Resp(500, {"error": "server"}))
    with db.scope() as s:
        assert acct.valid_token(s, s.get(MultipostAccount, aid), transport=t) == "at-open-1"
    with db() as s:
        assert s.get(MultipostAccount, aid).status == "connected"


def test_instagram_refresh_uses_the_access_token(db):
    uid = _user(db)
    _account(db, uid, "instagram", "1784", expires_in=timedelta(days=3), refresh="")
    t = FakeTransport()
    t.add("GET", oauth.IG_REFRESH_URL, Resp(200, {"access_token": "renewed", "expires_in": 5184000}))
    with db.scope() as s:
        assert acct.refresh_expiring(s, transport=t) == 1
    assert t.find("GET", oauth.IG_REFRESH_URL)[0]["params"]["access_token"] == "at-1784"


def test_account_settings_validate_against_platform_limits(db):
    uid = _user(db)
    aid = _account(db, uid)
    with db.scope() as s:
        out = acct.update(s, uid, aid, acct.AccountUpdate(daily_cap=6, min_gap_minutes=45,
                                                          posting_hours=[9, 18], timezone="Europe/Istanbul"))
    assert out["daily_cap"] == 6 and out["min_gap_minutes"] == 45 and out["posting_hours"] == [9, 18]
    for bad in (acct.AccountUpdate(daily_cap=16), acct.AccountUpdate(min_gap_minutes=5),
                acct.AccountUpdate(timezone="Mars/Base"), acct.AccountUpdate(posting_hours=[24])):
        with pytest.raises(oauth.ConnectError), db.scope() as s:
            acct.update(s, uid, aid, bad)


def test_workspace_sharing_and_roles(db):
    owner, editor, viewer, stranger = (_user(db, f"{n}@example.com") for n in ("o", "e", "v", "s"))
    with db() as s:
        ws = Workspace(name="Team", owner_id=owner)
        s.add(ws)
        s.flush()
        s.add_all([WorkspaceMember(workspace_id=ws.id, user_id=owner, role="owner"),
                   WorkspaceMember(workspace_id=ws.id, user_id=editor, role="editor"),
                   WorkspaceMember(workspace_id=ws.id, user_id=viewer, role="viewer")])
        s.commit()
        ws_id = ws.id
    aid = _account(db, owner, workspace_id=ws_id)
    with db.scope() as s:
        assert [r.id for r in acct.visible(s, editor)] == [aid]
        assert acct.visible(s, stranger) == []
        assert acct.get_for(s, editor, aid).id == aid
        with pytest.raises(oauth.ConnectError) as exc:
            acct.get_for(s, viewer, aid)
        assert exc.value.status_code == 403
        with pytest.raises(oauth.ConnectError):
            acct.update(s, editor, aid, acct.AccountUpdate(paused=True))
        with pytest.raises(oauth.ConnectError) as missing:
            acct.get_for(s, stranger, aid)
        assert missing.value.status_code == 404


def test_disconnect_cancels_open_posts_and_keeps_history(db):
    uid = _user(db)
    aid = _account(db, uid)
    jid = _job(db, uid)
    _campaign(db, uid, [jid], [aid], start_at=datetime.now(UTC) + timedelta(hours=1))
    with db.scope() as s:
        assert acct.disconnect(s, uid, aid) == 1
    with db() as s:
        assert _post(db).status == "canceled"
        row = s.get(MultipostAccount, aid)
        assert row.status == "needs_reauth" and crypto_tokens.decrypt(row.access_token_enc) == "revoked"


# --------------------------------------------------------------------------- #
# Campaigns
# --------------------------------------------------------------------------- #
def test_campaign_spreads_videos_across_accounts(db):
    uid = _user(db)
    a1 = _account(db, uid, ext="open-1")
    a2 = _account(db, uid, ext="open-2")
    a3 = _account(db, uid, "youtube", "UC1")
    jobs = [_job(db, uid) for _ in range(6)]
    start = datetime.now(UTC) + timedelta(minutes=10)
    with db.scope() as s:
        preview = camp.preview(s, uid, camp.CampaignInput(job_ids=tuple(jobs), account_ids=(a1, a2, a3),
                                                          visibility="public", start_at=start))
    assert len(preview["posts"]) == 6
    assert any("AI-generated" in n for n in preview["notes"])
    out = _campaign(db, uid, jobs, [a1, a2, a3], start_at=start, caption="New drop", hashtags=("#shop",))
    assert out["counts"]["scheduled"] == 6 and out["ai_generated"] is True
    per = {}
    for post in out["posts"]:
        per.setdefault(post["account_id"], []).append(post)
    assert sorted(len(v) for v in per.values()) == [2, 2, 2]
    assert len({p["job_id"] for p in out["posts"]}) == 6  # each video once in spread mode


def test_campaign_respects_existing_queue_on_the_account(db):
    uid = _user(db)
    aid = _account(db, uid, daily_cap=2)
    start = datetime.now(UTC) + timedelta(minutes=5)
    _campaign(db, uid, [_job(db, uid), _job(db, uid)], [aid], start_at=start)
    third = _campaign(db, uid, [_job(db, uid)], [aid], start_at=start)
    at = datetime.fromisoformat(third["posts"][0]["scheduled_at"])
    assert at >= start + pacing.DAY - timedelta(minutes=1)


def test_campaign_validation(db):
    uid, other = _user(db), _user(db, "b@example.com")
    aid = _account(db, uid)
    jid = _job(db, uid)
    theirs = _job(db, other)
    cases = [
        dict(job_ids=(jid,), account_ids=(aid,), visibility=""),
        dict(job_ids=(jid,), account_ids=(aid,), visibility="private", brand_content=True),
        dict(job_ids=(theirs,), account_ids=(aid,), visibility="public"),
        dict(job_ids=(jid,), account_ids=(aid,), visibility="public",
             start_at=datetime.now(UTC) - timedelta(days=1)),
        dict(job_ids=(jid,), account_ids=(aid,), visibility="public",
             start_at=datetime.now(UTC) + timedelta(days=120)),
    ]
    for case in cases:
        with pytest.raises(camp.CampaignError), db.scope() as s:
            camp.create(s, uid, camp.CampaignInput(**case))
    with db.scope() as s:
        s.get(MultipostAccount, aid).status = "paused"
    with pytest.raises(camp.CampaignError) as exc, db.scope() as s:
        camp.create(s, uid, camp.CampaignInput(job_ids=(jid,), account_ids=(aid,), visibility="public"))
    assert exc.value.status_code == 409


def test_cancel_and_retry(db):
    uid = _user(db)
    aid = _account(db, uid)
    out = _campaign(db, uid, [_job(db, uid), _job(db, uid)], [aid], start_at=datetime.now(UTC) + timedelta(hours=1))
    first, second = out["posts"]
    with db.scope() as s:
        assert camp.cancel_post(s, uid, first["id"])["status"] == "canceled"
        with pytest.raises(camp.CampaignError):
            camp.retry_post(s, uid, second["id"])  # not failed
        s.get(MultipostPost, second["id"]).status = "failed"
    with db.scope() as s:
        assert camp.retry_post(s, uid, second["id"])["status"] == "scheduled"
        s.get(MultipostPost, second["id"]).status = "held"
    with db.scope() as s:
        assert camp.cancel_post(s, uid, second["id"])["status"] == "canceled"  # held posts can be dropped
        s.get(MultipostPost, second["id"]).status = "scheduled"
    with db.scope() as s:
        canceled = camp.cancel_campaign(s, uid, out["id"])
    assert canceled["status"] == "canceled" and canceled["counts"]["canceled"] == 2


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def _tiktok_publish_routes(t, *, options=("PUBLIC_TO_EVERYONE", "SELF_ONLY")):
    t.add("POST", tt.CREATOR_INFO_URL, Resp(200, {"data": {
        "creator_nickname": "Shop One", "creator_username": "shopone", "privacy_level_options": list(options),
        "comment_disabled": False, "duet_disabled": True, "stitch_disabled": False,
        "max_video_post_duration_sec": 600}, "error": {"code": "ok"}}))
    t.add("POST", tt.DIRECT_INIT_URL, Resp(200, {"data": {"publish_id": "v_pub_1",
                                                          "upload_url": "https://open-upload.tiktokapis.com/video/?id=u1"},
                                                 "error": {"code": "ok"}}))
    t.add("PUT", "https://open-upload.tiktokapis.com/video/?id=", Resp(201, {}))


def test_runner_publishes_tiktok_file_upload_with_ai_label(db, video):
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid], caption="Hello", hashtags=("shop",), allow_comments=True,
              allow_duet=True)
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    _tiktok_publish_routes(t)
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"processing": 1}
    init = t.find("POST", tt.DIRECT_INIT_URL)[0]["json"]
    info = init["post_info"]
    assert info["is_aigc"] is True and info["privacy_level"] == "SELF_ONLY"  # unaudited app
    assert info["title"] == "Hello #shop"
    assert info["disable_comment"] is False and info["disable_duet"] is True  # TikTok disabled duet
    assert info["disable_stitch"] is True  # off unless the creator turned it on
    assert init["source_info"]["source"] == "FILE_UPLOAD"
    put = t.find("PUT", "https://open-upload.tiktokapis.com/video/?id=")[0]
    assert put["headers"]["Content-Range"].startswith("bytes 0-") and put["data"]
    post = _post(db)
    assert post.status == "processing" and post.publish_ref == "v_pub_1"
    with db() as s:
        assert s.get(MultipostAccount, aid).handle == "shopone"

    t.add("POST", tt.STATUS_URL, Resp(200, {"data": {"status": "PUBLISH_COMPLETE",
                                                     "publicaly_available_post_id": [7311]},
                                            "error": {"code": "ok"}}))
    assert runner.sweep_processing(now=now, transport=t) == {"published": 1}
    post = _post(db)
    assert post.status == "published" and post.url == "https://www.tiktok.com/@shopone/video/7311"


def test_runner_uses_audited_privacy_and_rejects_disallowed_levels(db, video, monkeypatch):
    monkeypatch.setenv("MULTIPOST_TIKTOK_AUDITED", "true")
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid], visibility="public")
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    _tiktok_publish_routes(t, options=("SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS"))
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"failed": 1}
    assert "does not allow PUBLIC_TO_EVERYONE" in _post(db).error
    assert not t.find("POST", tt.DIRECT_INIT_URL)


def test_runner_tiktok_draft_mode_uses_inbox(db, video):
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid], tiktok_mode="draft")
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    _tiktok_publish_routes(t)
    t.add("POST", tt.INBOX_INIT_URL, Resp(200, {"data": {"publish_id": "inbox_1",
                                                         "upload_url": "https://open-upload.tiktokapis.com/video/?id=u2"},
                                                "error": {"code": "ok"}}))
    runner.run_due(now=now, transport=t, media=FakeMedia(video))
    body = t.find("POST", tt.INBOX_INIT_URL)[0]["json"]
    assert "post_info" not in body and body["source_info"]["source"] == "FILE_UPLOAD"


def test_runner_instagram_container_flow_with_disclosure(db, video):
    uid = _user(db)
    aid = _account(db, uid, "instagram", "1784", handle="shop.ig", expires_in=timedelta(days=50))
    _campaign(db, uid, [_job(db, uid)], [aid], caption="Drop day")
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    t.add("GET", f"{ig.GRAPH}/1784/content_publishing_limit",
          Resp(200, {"data": [{"quota_usage": 3, "config": {"quota_total": 50}}]}))
    t.add("POST", f"{ig.GRAPH}/1784/media", Resp(200, {"id": "c-9"}))
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"processing": 1}
    params = t.find("POST", f"{ig.GRAPH}/1784/media")[0]["params"]
    assert params["media_type"] == "REELS" and params["video_url"].startswith("https://cdn.menivor.test/")
    assert params["caption"].endswith("Made with AI.") and params["caption"].startswith("Drop day")
    # The token travels in a header, never in the URL.
    assert all("access_token" not in c["params"] for c in t.calls)
    assert t.find("POST", f"{ig.GRAPH}/1784/media")[0]["headers"]["Authorization"] == "Bearer at-1784"

    t.add("GET", f"{ig.GRAPH}/c-9", Resp(200, {"status_code": "IN_PROGRESS"}), Resp(200, {"status_code": "FINISHED"}))
    assert runner.sweep_processing(now=now, transport=t) == {"processing": 1}
    t.add("POST", f"{ig.GRAPH}/1784/media_publish", Resp(200, {"id": "m-1"}))
    t.add("GET", f"{ig.GRAPH}/m-1", Resp(200, {"permalink": "https://www.instagram.com/reel/abc/"}))
    assert runner.sweep_processing(now=now, transport=t) == {"published": 1}
    post = _post(db)
    assert post.status == "published" and post.url == "https://www.instagram.com/reel/abc/"


def test_runner_instagram_live_quota_defers(db, video):
    uid = _user(db)
    aid = _account(db, uid, "instagram", "1784", expires_in=timedelta(days=50))
    _campaign(db, uid, [_job(db, uid)], [aid])
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    t.add("GET", f"{ig.GRAPH}/1784/content_publishing_limit",
          Resp(200, {"data": [{"quota_usage": 50, "config": {"quota_total": 50}}]}))
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"deferred": 1}
    post = _post(db)
    assert post.status == "scheduled" and acct.aware(post.next_attempt_at) >= now + timedelta(minutes=59)
    assert not t.find("POST", f"{ig.GRAPH}/1784/media")


def test_runner_youtube_upload_declares_synthetic_media(db, video):
    uid = _user(db)
    aid = _account(db, uid, "youtube", "UC1")
    _campaign(db, uid, [_job(db, uid)], [aid], caption="How it works", visibility="public")
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    t.add("POST", yt.UPLOAD_URL, Resp(200, {}, headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=s1"}))
    t.add("PUT", "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=s1", Resp(200, {"id": "vid1", "status": {"uploadStatus": "uploaded"}}))
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"processing": 1}
    meta = t.find("POST", yt.UPLOAD_URL)[0]["json"]
    assert meta["status"]["containsSyntheticMedia"] is True
    assert meta["status"]["selfDeclaredMadeForKids"] is False
    assert meta["status"]["privacyStatus"] == "private"  # unverified Google app
    t.add("GET", yt.VIDEOS_URL, Resp(200, {"items": [{"status": {"uploadStatus": "processed"}}]}))
    assert runner.sweep_processing(now=now, transport=t) == {"published": 1}
    assert _post(db).url == "https://www.youtube.com/shorts/vid1"


def test_runner_youtube_project_quota_is_shared_across_channels(db, video, monkeypatch):
    monkeypatch.setenv("MULTIPOST_YOUTUBE_PROJECT_DAILY_UPLOADS", "1")
    uid = _user(db)
    a1 = _account(db, uid, "youtube", "UC1")
    a2 = _account(db, uid, "youtube", "UC2")
    _campaign(db, uid, [_job(db, uid), _job(db, uid)], [a1, a2])
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    t.add("POST", yt.UPLOAD_URL, Resp(200, {}, headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=s1"}))
    t.add("PUT", "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=s1", Resp(200, {"id": "vid1"}))
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"processing": 1, "deferred": 1}
    with db() as s:
        waiting = s.execute(select(MultipostPost).where(MultipostPost.status == "scheduled")).scalars().one()
        assert waiting.provider_status == "waiting:youtube_project_quota"


def test_runner_enforces_account_cap_at_publish_time(db, video):
    uid = _user(db)
    aid = _account(db, uid, daily_cap=1)
    jobs = [_job(db, uid), _job(db, uid)]
    _campaign(db, uid, jobs, [aid])
    now = datetime.now(UTC)
    _make_due(db, now)  # force both due now, as if a render delay stacked them
    t = FakeTransport()
    _tiktok_publish_routes(t)
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"processing": 1, "deferred": 1}
    assert len(t.find("POST", tt.DIRECT_INIT_URL)) == 1
    with db() as s:
        waiting = s.execute(select(MultipostPost).where(MultipostPost.status == "scheduled")).scalars().one()
        assert "daily_cap" in waiting.provider_status
        assert acct.aware(waiting.next_attempt_at) >= now + pacing.DAY - timedelta(seconds=1)


def test_runner_waits_for_rendering_video(db, video):
    uid = _user(db)
    aid = _account(db, uid)
    jid = _job(db, uid, state=TASK_STATE_PROCESSING)
    _campaign(db, uid, [jid], [aid])
    now = datetime.now(UTC)
    _make_due(db, now)
    media = FakeMedia(video, state=media_mod.RENDERING)
    assert runner.run_due(now=now, transport=FakeTransport(), media=media) == {"deferred": 1}
    assert _post(db).provider_status == "waiting_for_video"
    media.default = media_mod.FAILED
    _make_due(db, now)
    assert runner.run_due(now=now, transport=FakeTransport(), media=media) == {"failed": 1}


def test_runner_platform_rate_limit_requeues(db, video):
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid])
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    _tiktok_publish_routes(t)
    t.routes[("POST", tt.DIRECT_INIT_URL)] = [Resp(200, {"error": {"code": "spam_risk_too_many_posts",
                                                                     "message": "too many"}})]
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"deferred": 1}
    post = _post(db)
    assert post.status == "scheduled" and acct.aware(post.next_attempt_at) >= now + timedelta(minutes=59)
    assert post.attempts == 0


def test_runner_auth_error_flags_account(db, video):
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid])
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    t.add("POST", tt.CREATOR_INFO_URL, Resp(401, {"error": {"code": "access_token_invalid", "message": "x"}}))
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"failed": 1}
    with db() as s:
        assert s.get(MultipostAccount, aid).status == "needs_reauth"


def test_runner_retries_transient_errors_then_fails(db, video):
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid])
    t = FakeTransport()
    _tiktok_publish_routes(t)
    t.routes[("POST", tt.DIRECT_INIT_URL)] = [Resp(503, {"error": {"code": "internal_error", "message": "down"}})]
    now = datetime.now(UTC)
    results = []
    for _ in range(runner.MAX_ATTEMPTS):
        _make_due(db, now)
        results.append(runner.run_due(now=now, transport=t, media=FakeMedia(video)))
    assert results[:-1] == [{"deferred": 1}] * (runner.MAX_ATTEMPTS - 1)
    assert results[-1] == {"failed": 1}
    assert _post(db).attempts == runner.MAX_ATTEMPTS


def test_claim_is_exclusive_and_stale_publishing_is_failed_not_reposted(db):
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid])
    now = datetime.now(UTC)
    _make_due(db, now)
    post = _post(db)
    assert runner._claim(post.id, now) is True
    assert runner._claim(post.id, now) is False
    assert runner.sweep_stale(now=now + timedelta(hours=1)) == 1
    assert "interrupted" in _post(db).error


def test_content_gate_holds_post(db, video, monkeypatch):
    monkeypatch.setattr(media_mod, "content_gate", lambda p, t, c: (False, "held for review (block): unsafe"))
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid])
    now = datetime.now(UTC)
    _make_due(db, now)
    assert runner.run_due(now=now, transport=FakeTransport(), media=FakeMedia(video)) == {"held": 1}


# --------------------------------------------------------------------------- #
# Clients
# --------------------------------------------------------------------------- #
def test_tiktok_large_file_is_chunked(tmp_path):
    path = tmp_path / "big.mp4"
    size = 70 * 1024 * 1024 + 123
    path.write_bytes(b"\0" * size)
    t = FakeTransport()
    t.add("POST", tt.DIRECT_INIT_URL, Resp(200, {"data": {"publish_id": "p", "upload_url": "https://open-upload.tiktokapis.com/x"}}))
    t.add("PUT", "https://open-upload.tiktokapis.com/", Resp(206, {}))
    tt.publish("tok", PostSpec(video_path=str(path), visibility="private"), info={}, audited=False, source="file",
               transport=t)
    src = t.find("POST", tt.DIRECT_INIT_URL)[0]["json"]["source_info"]
    assert src["chunk_size"] == 10 * 1024 * 1024 and src["total_chunk_count"] == 7
    puts = t.find("PUT", "https://open-upload.tiktokapis.com/")
    assert len(puts) == 7 and puts[-1]["headers"]["Content-Range"] == f"bytes {6 * 10 * 1024 * 1024}-{size - 1}/{size}"


def test_client_error_mapping():
    with pytest.raises(AuthError):
        yt._raise_for(Resp(401, {"error": {"message": "bad"}}), "x")
    with pytest.raises(RateLimited):
        yt._raise_for(Resp(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}), "x")
    with pytest.raises(RateLimited):
        ig._raise_for(Resp(400, {"error": {"code": 9, "message": "limit"}}), "x")
    err = None
    try:
        ig._raise_for(Resp(500, {"error": {"code": 1, "message": "oops"}}), "x")
    except ClientError as exc:
        err = exc
    assert err is not None and err.retryable


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #
def _signed(body: dict, secret="tiktok-secret", stamp=None):
    raw = json.dumps(body).encode()
    t = str(stamp or int(time.time()))
    sig = hmac.new(secret.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    return raw, f"t={t},s={sig}"


def test_tiktok_webhook_signature(env):
    raw, header = _signed({"event": "x"})
    webhooks.verify_tiktok(raw, header)
    with pytest.raises(webhooks.WebhookError):
        webhooks.verify_tiktok(raw + b" ", header)
    old_raw, old = _signed({"event": "x"}, stamp=int(time.time()) - 3600)
    with pytest.raises(webhooks.WebhookError):
        webhooks.verify_tiktok(old_raw, old)


def test_tiktok_webhook_completes_post_once(db):
    uid = _user(db)
    aid = _account(db, uid, handle="shopone")
    _campaign(db, uid, [_job(db, uid)], [aid])
    with db() as s:
        post = s.execute(select(MultipostPost)).scalars().one()
        post.status, post.publish_ref = "processing", "v_pub_9"
        s.commit()
    raw, _ = _signed({"event": "post.publish.publicly_available", "user_openid": "open-1",
                      "content": json.dumps({"publish_id": "v_pub_9", "post_id": "7400"})})
    with db.scope() as s:
        assert webhooks.apply_tiktok(s, raw)["applied"] is True
    with db.scope() as s:
        assert webhooks.apply_tiktok(s, raw)["reason"] == "duplicate"
    post = _post(db)
    assert post.status == "published" and post.url == "https://www.tiktok.com/@shopone/video/7400"


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(db, monkeypatch):
    from fastapi import FastAPI
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient

    from app.domains.multipost import router as router_mod
    from app.models.exception import HttpException
    from app.utils import utils

    monkeypatch.setattr(router_mod, "get_session", db.scope)
    monkeypatch.setattr(router_mod, "require_publishing_enabled", lambda request_id: None)
    app = FastAPI()
    app.include_router(router_mod.router)
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def test_http_accounts_are_token_free_and_campaign_needs_consent(client, db):
    uid = _user(db, "owner@example.com")
    aid = _account(db, uid)
    jid = _job(db, uid)
    headers = {"x-api-key": "owner@example.com"}
    listed = client.get("/api/v1/multipost/accounts", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"]["accounts"][0]["id"] == aid and "at-open-1" not in listed.text
    providers = client.get("/api/v1/multipost/providers", headers=headers).json()["data"]["providers"]
    assert {p["provider"] for p in providers} == {"tiktok", "instagram", "youtube"}
    body = {"job_ids": [jid], "account_ids": [aid], "visibility": "public"}
    assert client.post("/api/v1/multipost/campaigns", headers=headers, json=body).status_code == 400
    missing_visibility = {"job_ids": [jid], "account_ids": [aid], "consent": True}
    assert client.post("/api/v1/multipost/campaigns", headers=headers, json=missing_visibility).status_code == 422
    made = client.post("/api/v1/multipost/campaigns", headers=headers, json={**body, "consent": True})
    assert made.status_code == 200, made.text
    queue = client.get("/api/v1/multipost/posts", headers=headers).json()["data"]["posts"]
    assert len(queue) == 1 and queue[0]["status"] == "scheduled"
    _user(db, "other@example.com")
    other = client.get(f"/api/v1/multipost/campaigns/{made.json()['data']['id']}",
                       headers={"x-api-key": "other@example.com"})
    assert other.status_code == 404, other.text


def test_http_tiktok_webhook_rejects_unsigned(client):
    resp = client.post("/api/v1/multipost/webhooks/tiktok", content=b"{}")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Variations: re-run with a new opening hook
# --------------------------------------------------------------------------- #
def test_rerun_hook_style_override_and_conflict():
    from pydantic import ValidationError

    from app.domains.reels.router import _apply_rerun_overrides, _rerun_hook_conflict
    from app.models.schema import RerunOverrides, RerunRequest

    body = RerunRequest(overrides=RerunOverrides(hook_style="question"))
    generated = {"video_subject": "Desk lamp", "video_script": ""}
    assert _apply_rerun_overrides(generated, body)["hook_style"] == "question"
    assert generated == {"video_subject": "Desk lamp", "video_script": ""}  # source untouched
    assert _rerun_hook_conflict(generated, body) is False
    assert _rerun_hook_conflict({"video_script": "My own words"}, body) is True
    assert _rerun_hook_conflict({"video_script": "My own words"}, RerunRequest(overrides=RerunOverrides())) is False
    with pytest.raises(ValidationError):
        RerunOverrides(hook_style="clickbait")


# --------------------------------------------------------------------------- #
# Verifier fixes (merge review)
# --------------------------------------------------------------------------- #
def test_upload_urls_must_stay_on_platform_hosts(env, video):
    t = FakeTransport()
    t.add("POST", tt.DIRECT_INIT_URL, Resp(200, {"data": {"publish_id": "p1",
                                                          "upload_url": "https://169.254.169.254/latest"},
                                                 "error": {"code": "ok"}}))
    spec = PostSpec(video_path=video, visibility="private")
    with pytest.raises(ClientError, match="outside its own servers"):
        tt.publish("tok", spec, info={}, audited=False, source="file", transport=t)
    assert not [c for c in t.calls if c["method"] == "PUT"]

    y = FakeTransport()
    y.add("POST", yt.UPLOAD_URL, Resp(200, {}, headers={"Location": "https://evil.example/upload"}))
    with pytest.raises(ClientError, match="outside its own servers"):
        yt.publish("tok", spec, verified=False, transport=y)
    assert not [c for c in y.calls if c["method"] == "PUT"]  # the bearer token never left Google
    for bad in ("http://www.googleapis.com/x", "https://googleapis.com.evil.example/x",
                "https://user:pw@www.googleapis.com/x"):
        with pytest.raises(ClientError):
            from app.domains.multipost.clients.base import require_platform_url
            require_platform_url("youtube", bad, yt.UPLOAD_HOSTS)


def test_instagram_ids_are_validated_before_reaching_a_url(env):
    with pytest.raises(ClientError):
        ig.publish("tok", "../me", PostSpec(video_url="https://cdn.menivor.test/a.mp4"), disclosure="",
                   transport=FakeTransport())
    with pytest.raises(ClientError):
        ig.advance("tok", "1784", "c/../x", transport=FakeTransport())


def test_runner_stops_posting_for_a_member_removed_from_the_workspace(db, video):
    owner, editor = _user(db, "own@example.com"), _user(db, "ed@example.com")
    with db() as s:
        ws = Workspace(name="Team", owner_id=owner)
        s.add(ws)
        s.flush()
        s.add_all([WorkspaceMember(workspace_id=ws.id, user_id=owner, role="owner"),
                   WorkspaceMember(workspace_id=ws.id, user_id=editor, role="editor")])
        s.commit()
        ws_id = ws.id
    aid = _account(db, owner, workspace_id=ws_id)
    _campaign(db, editor, [_job(db, editor)], [aid])
    with db() as s:
        s.execute(WorkspaceMember.__table__.update()
                  .where(WorkspaceMember.user_id == editor).values(role="viewer"))
        s.commit()
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"failed": 1}
    assert "permission" in _post(db).error and t.calls == []


def test_timeout_during_the_publish_call_is_not_retried(db, video):
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid])
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    _tiktok_publish_routes(t)
    real = t.request

    def flaky(method, url, **kw):
        if url.startswith(tt.DIRECT_INIT_URL):
            t.calls.append({"method": method, "url": url})
            raise TimeoutError("read timed out")
        return real(method, url, **kw)

    t.request = flaky
    assert runner.run_due(now=now, transport=t, media=FakeMedia(video)) == {"failed": 1}
    post = _post(db)
    assert post.status == "failed" and "posted twice" in post.error


def test_storage_failure_before_sending_is_retried(db, video):
    uid = _user(db)
    aid = _account(db, uid)
    _campaign(db, uid, [_job(db, uid)], [aid])
    now = datetime.now(UTC)
    _make_due(db, now)
    t = FakeTransport()
    _tiktok_publish_routes(t)

    class BrokenMedia(FakeMedia):
        def download(self, user_id, job_id):
            raise OSError("R2 unreachable")

    assert runner.run_due(now=now, transport=t, media=BrokenMedia(video)) == {"deferred": 1}
    assert _post(db).status == "scheduled" and not t.find("POST", tt.DIRECT_INIT_URL)


def test_http_callback_burns_the_state_even_when_the_exchange_fails(client, db, monkeypatch):
    uid = _user(db, "owner@example.com")
    headers = {"x-api-key": "owner@example.com"}
    with db.scope() as s:
        started = acct.start_connect(s, uid, "tiktok")
    state = parse_qs(urlparse(started["authorize_url"]).query)["state"][0]

    def refuse(*args, **kwargs):
        raise oauth.ConnectError("TikTok would not issue a token: invalid_grant")

    monkeypatch.setattr(oauth, "exchange", refuse)
    first = client.post("/api/v1/multipost/connect/callback", headers=headers, json={"code": "c", "state": state})
    assert first.status_code == 400
    again = client.post("/api/v1/multipost/connect/callback", headers=headers, json={"code": "c", "state": state})
    assert again.status_code == 400 and "already used" in again.text
