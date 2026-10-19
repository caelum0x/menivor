"""Wave P P3 verifier fixes (Menivor lane).

1. A grant that happened before a refund, but reaches us after it (a retried
   webhook or the reconcile job), must not reopen the refunded title.
2. Replaying one segment URL must not add delivered minutes (billed to the
   creator) on every request; each segment counts once per session and client.
3. "Ask this video" quotes the transcript, so on a paid title it needs the same
   access as playback.
"""

from __future__ import annotations

import time

import pytest

from app.domains.ott.models import OttTitle
from app.domains.ott_access import service as access, tokens
from app.services.billing import ott_usage

from tests.reelforge import _wp_p3_ott as h
from tests.reelforge.test_wp_pm3_2_commerce_ads import _deliver, _event, _offer, _play, env  # noqa: F401
from tests.reelforge import test_wp_pm3_5_analytics_ai_discovery as discovery_tests


# --------------------------------------------------------------------------- #
# 1. Late grant after a refund
# --------------------------------------------------------------------------- #
def test_a_grant_arriving_after_its_refund_stays_closed(env):  # noqa: F811
    tvod = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    bought_ms = int(time.time() * 1000) - 60_000
    refund = _deliver(env, "entitlement.revoked", _event(env, "ent_r", tvod["sku"], kind="revoked", reason="refund"))
    assert refund.json()["data"]["outcome"] == "revoked:none_active"
    late = _deliver(env, "entitlement.granted", _event(env, "ent_g", tvod["sku"], occurred=bought_ms))
    assert late.json()["data"]["outcome"] == "ignored:revoked_later"
    assert _play(env, env["ids"][0]).status_code == 402


def test_buying_again_after_a_refund_still_unlocks(env):  # noqa: F811
    tvod = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    _deliver(env, "entitlement.granted", _event(env, "ent_1", tvod["sku"], occurred=int(time.time() * 1000) - 5000))
    _deliver(env, "entitlement.revoked", _event(env, "ent_2", tvod["sku"], kind="revoked", reason="refund"))
    assert _play(env, env["ids"][0]).status_code == 402
    again = _deliver(env, "entitlement.granted", _event(env, "ent_3", tvod["sku"],
                                                         occurred=int(time.time() * 1000) + 2000))
    assert again.json()["data"]["outcome"] == "granted"
    assert _play(env, env["ids"][0]).status_code == 200


def test_reconcile_does_not_reopen_a_refunded_purchase(env):  # noqa: F811
    from app.domains.ott_commerce import products, tasks

    tvod = _offer(env, kind="tvod", name="Own the film", price_cents=999, title_id=env["ids"][0])
    bought_ms = int(time.time() * 1000) - 60_000
    _deliver(env, "entitlement.revoked", _event(env, "ent_r", tvod["sku"], kind="revoked", reason="refund",
                                                occurred=bought_ms + 1000))
    env["mint"].events = [_event(env, "ent_g", tvod["sku"], occurred=bought_ms)]
    with env["factory"]() as s:
        tasks.reconcile(s, products.MintSellers(transport=env["mint"]))
        s.commit()
    assert _play(env, env["ids"][0]).status_code == 402


# --------------------------------------------------------------------------- #
# 2. Delivered minutes cannot be inflated by replaying a segment
# --------------------------------------------------------------------------- #
def test_replaying_a_segment_counts_it_once(monkeypatch):
    factory = h.make_factory()
    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    owner = h.owner(factory)
    cid, titles = h.channel(factory, owner, "maya", titles=1)
    counter = ott_usage.MemoryCounter()
    ott_usage.set_counter(counter)
    monkeypatch.setattr(access.limits, "renew", lambda *a, **k: None)
    try:
        token, _grant = tokens.issue(titles[0], "device:x", "TR")
        presign = lambda key, ttl: f"https://r2/{key}"  # noqa: E731
        with factory() as s:
            for _ in range(50):
                access.segment_url(s, token, "v_720p/1.m4s", presign, client="ip-a")
            access.segment_url(s, token, "v_720p/2.m4s", presign, client="ip-a")
            access.segment_url(s, token, "v_720p/1.m4s", presign, client="ip-b")  # another FAST viewer
        hour = ott_usage.hour_key(__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
        assert counter.get(f"ott:usage:delivered:{cid}:{hour}") == 3 * ott_usage.SEGMENT_S
    finally:
        ott_usage.set_counter(None)


def test_segment_dedupe_outage_never_blocks_playback(monkeypatch):
    class Broken:
        def add(self, key, amount):
            raise ConnectionError("down")

        def claim(self, key, ttl):
            raise ConnectionError("down")

    ott_usage.set_counter(Broken())
    try:
        assert ott_usage.first_delivery("s", "v/1.m4s", "c") is False
    finally:
        ott_usage.set_counter(None)


# --------------------------------------------------------------------------- #
# 3. Ask this video on a paid title
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ask_env(monkeypatch):
    from app.domains.ott_access import limits
    from app.domains.ott_discovery import embeddings, router as discovery_router, search

    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (discovery_router,))
    h.enable(monkeypatch, "discovery", "access")
    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    monkeypatch.setenv("OTT_DISCOVERY_EMBEDDER", "hashing")
    monkeypatch.setattr(discovery_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(limits, "_STORE", limits.MemoryStore())
    embeddings.default_embedder.cache_clear()
    search.reset_cache()
    owner = h.owner(factory)
    _cid, ids = h.channel(factory, owner, "maya", titles=2)
    yield {"factory": factory, "client": h.app_client(discovery_router.router), "ids": ids}
    embeddings.default_embedder.cache_clear()


def test_ask_on_a_paid_title_needs_access(ask_env, monkeypatch):
    from app.domains.ott_discovery import ask as asking

    ctx = ask_env
    monkeypatch.setattr(asking, "_default_llm", lambda prompt: "Rest the dough for an hour [01:10].")
    title_id = ctx["ids"][0]
    discovery_tests._transcript(ctx, title_id, discovery_tests.LESSON)
    with ctx["factory"]() as s:
        s.get(OttTitle, title_id).access_tier = "paid"
        s.commit()
    monkeypatch.setenv("OTT_ACCESS_LIVE", "1")
    url = f"/api/v1/ott/titles/{title_id}/ask"
    refused = ctx["client"].post(url, json={"question": "How long does it rest?"})
    assert refused.status_code == 402 and "dough" not in refused.text
    owner = ctx["client"].post(url, json={"question": "How long does it rest?"}, headers={"x-api-key": h.OWNER_KEY})
    assert owner.status_code == 200 and owner.json()["data"]["citations"]
    free = ctx["ids"][1]
    discovery_tests._transcript(ctx, free, discovery_tests.LESSON)
    assert ctx["client"].post(f"/api/v1/ott/titles/{free}/ask", json={"question": "How long?"}).status_code == 200
