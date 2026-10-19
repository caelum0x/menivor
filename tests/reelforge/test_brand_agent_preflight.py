"""Preflight before Approve: never ask for approval and then fail on something knowable.

The agent used to show Approve and only then fail with "no product preset for this brand",
three times in a row. Now: missing product / credits / sign-in / account becomes one inline
step that fixes it; Approve shows only when nothing is missing; a repeat points back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domains.adclone import agent_port as adclone_port
from app.domains.adclone import preset_store
from app.domains.adclone import service as adclone_service
from app.domains.adclone.schemas import CloneBrief
from app.domains.adstudio.catalog_models import StoreCatalogImport, StoreCatalogProduct
from app.domains.brand_agent import agent, gate, sessions, spaces
from app.domains.brand_agent.models import AgentAction
from app.models.db.models import CreditLedger
from tests.reelforge._brand_agent_support import connect_account, make_deps, make_factory, make_user

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adclone" / "brief-tiktok-price-shock.json"
TIKTOK = "https://www.tiktok.com/@brand/video/7300000000000000000"


@pytest.fixture()
def db(monkeypatch):
    factory = make_factory()
    import app.models.db.base as base

    monkeypatch.setattr(base, "get_session", factory.scope)  # stored presets load through it
    return factory


@pytest.fixture()
def clone_env(monkeypatch, tmp_path):
    monkeypatch.setenv(adclone_service.ENABLED_ENV, "1")
    monkeypatch.setenv(adclone_service.LLM_ENV, "0")
    monkeypatch.setenv("ADCLONE_MJ_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv(adclone_port.PRESET_ENV, raising=False)


@pytest.fixture()
def brief() -> CloneBrief:
    return CloneBrief.model_validate(json.loads(FIXTURE.read_text()))


def _session(db, uid):
    with db.scope() as s:
        space = spaces.ensure_default(s, uid)
        return space.id, sessions.create(s, uid, space.id).id


def _say(db, deps, uid, sid, text):
    with db.scope() as s:
        return agent.handle_text(s, deps, uid, sid, text)


def _chip(db, deps, uid, sid, choice, action_id, value=None):
    with db.scope() as s:
        return agent.handle_chip(s, deps, uid, sid, choice=choice, action_id=action_id, value=value)


def _catalog(db, uid, title="Linen Overshirt", url="https://shop.example.com/products/linen"):
    with db.scope() as s:
        imp = StoreCatalogImport(user_id=uid, provider="shopify", store_url="https://shop.example.com",
                                 store_name="Shop", status="completed")
        s.add(imp)
        s.flush()
        row = StoreCatalogProduct(import_id=imp.id, user_id=uid, external_id="p1", title=title,
                                  description="a breathable linen overshirt", url=url)
        s.add(row)
        s.flush()
        return row.id


def _actions(db, uid):
    with db.scope() as s:
        return s.query(AgentAction).filter_by(user_id=uid).all()


def _choices(message):
    return [c["choice"] for c in message.get("chips") or []]


def test_missing_product_shows_a_picker_not_approve(db, clone_env, brief):
    uid = make_user(db)
    _catalog(db, uid)
    deps = make_deps(ad_clone=adclone_port.AdCloneAgentPort(analyze=lambda url, llm=None: brief))
    _, sid = _session(db, uid)
    msg = _say(db, deps, uid, sid, f"clone this ad {TIKTOK}")[-1]
    assert "approve" not in _choices(msg) and _choices(msg) == ["use_product"]
    assert msg["chips"][0]["label"] == "Use Linen Overshirt"
    assert msg["action"]["status"] == gate.STATUS_BLOCKED
    assert "Which product is this ad for?" in msg["content"]


def test_a_repeat_points_back_instead_of_a_new_failing_card(db, clone_env, brief):
    uid = make_user(db)
    _catalog(db, uid)
    deps = make_deps(ad_clone=adclone_port.AdCloneAgentPort(analyze=lambda url, llm=None: brief))
    _, sid = _session(db, uid)
    first = _say(db, deps, uid, sid, f"clone this ad {TIKTOK}")[-1]
    for _ in range(2):
        again = _say(db, deps, uid, sid, f"clone this ad {TIKTOK}")[-1]
        assert again.get("action") is None and not again.get("chips")
        assert again["content"].startswith("That is still waiting on the step above")
    assert len(_actions(db, uid)) == 1
    out = _chip(db, deps, uid, sid, "approve", first["action"]["id"])[-1]  # approving the blocked one
    assert out["content"].startswith("Still waiting on the step above") and not out.get("chips")


def test_use_this_creates_the_preset_then_approve_runs_it(db, clone_env, brief):
    uid = make_user(db)
    product_id = _catalog(db, uid)
    deps = make_deps(ad_clone=adclone_port.AdCloneAgentPort(analyze=lambda url, llm=None: brief))
    space_id, sid = _session(db, uid)
    blocked = _say(db, deps, uid, sid, f"clone this ad {TIKTOK}")[-1]
    ready = _chip(db, deps, uid, sid, "use_product", blocked["action"]["id"], f"catalog:{product_id}")[-1]
    assert _choices(ready) == ["approve", "reject"]
    assert ready["content"].startswith("Set up Linen Overshirt in Ad Clone.")
    with db.scope() as s:
        preset = preset_store.for_space(s, uid, space_id)
    assert preset["product"] == "Linen Overshirt" and preset["domain"] == "shop.example.com"
    assert preset["cta"]["text"] == "Linen Overshirt. Get yours at shop.example.com."
    assert ready["action"]["payload"]["preset"] == preset["id"]
    done = _chip(db, deps, uid, sid, "approve", blocked["action"]["id"])[-1]
    assert done["action"]["status"] == gate.STATUS_EXECUTED, done
    assert done["action"]["result"]["preset"] == preset["id"]
    plan_text = json.dumps(done["action"]["result"]["plans"])
    assert "Linen Overshirt. Get yours at shop.example.com." in plan_text
    # The next clone in this space goes straight to Approve.
    nxt = _say(db, deps, uid, sid, "clone https://www.tiktok.com/@other/video/7300000000000000001")[-1]
    assert _choices(nxt) == ["approve", "reject"]


def test_brand_memory_products_are_offered_when_there_is_no_catalog(db, clone_env):
    uid = make_user(db)
    port = adclone_port.AdCloneAgentPort()
    with db.scope() as s:
        options = port.product_options(s, uid, brand={"product": {"products": [
            {"name": "Basepoint Cloud", "what_it_is": "managed Postgres"}]}})
        need = port.preflight(s, uid, brand={}, space_id="sp1")
    assert options == [{"id": "memory:0", "name": "Basepoint Cloud", "source": "brand_memory",
                        "detail": "managed Postgres", "thumbnail_url": ""}]
    assert need["id"] == "product" and need["options"] == [] and "Import your products" in need["detail"]


def test_no_products_anywhere_offers_import_and_check_again(db, clone_env):
    uid = make_user(db)
    deps = make_deps(ad_clone=adclone_port.AdCloneAgentPort())
    _, sid = _session(db, uid)
    msg = _say(db, deps, uid, sid, f"clone this ad {TIKTOK}")[-1]
    assert [(c["choice"], c.get("href")) for c in msg["chips"]] == [("open", "/settings/integrations"),
                                                                    ("recheck", None)]


def test_zero_credits_shows_get_credits_before_approve_then_check_again(db):
    uid = make_user(db, credits=0)
    deps = make_deps()
    _, sid = _session(db, uid)
    msg = _say(db, deps, uid, sid, "make a 10 second video ad")[-1]
    assert [(c["label"], c.get("href")) for c in msg["chips"]] == [("Get credits", "/billing"),
                                                                   ("Check again", None)]
    assert "You have 0 credits" in msg["content"] and deps.generation.calls == []
    action_id = msg["action"]["id"]
    still = _chip(db, deps, uid, sid, "recheck", action_id)[-1]
    assert still["content"].startswith("Still waiting on the step above") and not still.get("chips")
    with db.scope() as s:
        s.add(CreditLedger(user_id=uid, delta=50, reason="purchase", balance_after=50))
    ready = _chip(db, deps, uid, sid, "recheck", action_id)[-1]
    assert _choices(ready) == ["approve", "reject"]


def test_signed_out_guest_is_asked_to_sign_in_first(db):
    uid = make_user(db, email="device-abc@accounts.reelforge.app")
    deps = make_deps()
    _, sid = _session(db, uid)
    msg = _say(db, deps, uid, sid, "make an image ad for our launch")[-1]
    assert [(c["label"], c.get("href")) for c in msg["chips"]] == [("Sign in", "/sign-in")]
    assert msg["action"]["status"] == gate.STATUS_BLOCKED


def test_publish_needs_a_connected_account_and_a_video(db):
    uid = make_user(db)
    deps = make_deps()
    _, sid = _session(db, uid)
    msg = _say(db, deps, uid, sid, "publish my latest video to TikTok")[-1]
    titles = [n["id"] for n in msg["action"]["needs"]]
    assert titles == ["video", "account"] and ("open", "/autopost") in [(c["choice"], c.get("href"))
                                                                        for c in msg["chips"]]
    connect_account(db, uid, "tiktok")
    assert deps.publisher.calls == []


def test_ad_clone_switched_off_is_said_before_approve(db, monkeypatch):
    monkeypatch.setenv(adclone_service.ENABLED_ENV, "0")
    uid = make_user(db)
    deps = make_deps(ad_clone=adclone_port.AdCloneAgentPort())
    _, sid = _session(db, uid)
    msg = _say(db, deps, uid, sid, f"clone this ad {TIKTOK}")[-1]
    assert "switched off" in msg["content"] and "approve" not in _choices(msg)


def test_catalog_options_carry_thumbnails_and_chips_cap_at_six(db, clone_env):
    from app.domains.brand_agent import preflight

    uid = make_user(db)
    for i in range(9):
        _catalog(db, uid, title=f"Product {i}")
    with db.scope() as s:
        s.query(StoreCatalogProduct).update({"image_urls": ["https://cdn.example.com/p.jpg"]})
    port = adclone_port.AdCloneAgentPort()
    with db.scope() as s:
        need = port.preflight(s, uid, brand={}, space_id="sp1")
    assert len(need["options"]) == 9 and need["options"][0]["thumbnail_url"] == "https://cdn.example.com/p.jpg"
    chips = preflight.chips("a1", [preflight.need("product", need["title"], "", need["options"])])
    assert len(chips) == 6 and all(c["choice"] == "use_product" for c in chips)
