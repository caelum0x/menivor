"""Pricing rule: a standard credit never pays for ElevenLabs or AI-video calls.

Premium voice credits and AI-video credits (3x provider cost, 1 credit = 1
US cent) are separate SKUs with their own ledger. Covers the ledger, reel
admission (downgrade to a free voice / 402 for presenters), refunds and
settlement, the pipeline guards, Dodo pack fulfilment and refunds, the
premium endpoints, premium dubbing and the per-job actuals rows.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.jobs as jobs_mod
import app.models.db.base as db_base
from app.core.launch import formats
from app.domains.reels import premium
from app.models.db.base import Base
from app.models.db.models import Job, JobEvent, User
from app.models.db.repositories import CreditRepository, JobRepository
from app.models.exception import HttpException
from app.services.billing import dodo_billing, dodo_client, premium_credits as pc
from app.utils import utils
from tests.reelforge.test_byov_api import _FakePipeline

_API_KEY = "premium-testkey"
_HEADERS = {"x-api-key": _API_KEY}


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    return factory


def _user(factory, *, credits=5, voice=0, ai=0) -> str:
    with factory() as s:
        user = User(
            email=f"u{credits}{voice}{ai}@example.com",
            api_key_hash=hashlib.sha256(_API_KEY.encode()).hexdigest(),
            credits=0,
        )
        s.add(user)
        s.flush()
        if credits:
            CreditRepository(s).grant(user.id, credits, reason="signup")
        if voice:
            pc.grant(s, user.id, pc.KIND_PREMIUM_VOICE, voice, "test_grant")
        if ai:
            pc.grant(s, user.id, pc.KIND_AI_VIDEO, ai, "test_grant")
        s.commit()
        return user.id


def _pro(factory, uid, plan="pro") -> None:
    """Give ``uid`` a live personal plan (presenter reels are Pro and up, MD8)."""
    from app.models.db.creator_subscription import CreatorSubscription

    with factory() as s:
        s.add(CreatorSubscription(user_id=uid, plan_key=plan, status="active"))
        s.commit()


def _balances(factory, uid):
    with factory() as s:
        return (
            CreditRepository(s).balance(uid),
            pc.balance(s, uid, pc.KIND_PREMIUM_VOICE),
            pc.balance(s, uid, pc.KIND_AI_VIDEO),
        )


# --------------------------------------------------------------------------- #
# Ledger and pricing
# --------------------------------------------------------------------------- #
def test_ai_video_credits_are_three_times_provider_cost_in_cents():
    assert pc.ai_video_credits_for_usd(0.75) == 225
    assert pc.ai_video_credits_for_usd(0.005) == 2  # ceil(1.5)
    assert pc.ai_video_credits_for_usd(0) == 0
    assert pc.ai_video_credits_for_usd(float("nan")) == 0


def test_premium_ledger_is_separate_from_standard_credits(db):
    uid = _user(db, credits=5, voice=2)
    assert _balances(db, uid) == (5, 2, 0)
    with db() as s:
        pc.debit(s, uid, pc.KIND_PREMIUM_VOICE, 2, "x", None)
        s.commit()
    assert _balances(db, uid) == (5, 0, 0)
    with db() as s, pytest.raises(pc.InsufficientPremiumCredits):
        pc.debit(s, uid, pc.KIND_PREMIUM_VOICE, 1, "x", None)
    with db() as s, pytest.raises(ValueError):
        pc.grant(s, uid, "gold", 1, "x")


def test_refund_is_idempotent_and_settle_keeps_three_times_measured(db):
    uid = _user(db, ai=500)
    with db() as s:
        pc.debit(s, uid, pc.KIND_AI_VIDEO, 300, "premium_debit:j1", "j1")
        pc.debit(s, uid, pc.KIND_AI_VIDEO, 100, "premium_debit:j2", "j2")
        s.commit()
    # j1 measured $0.50 -> keeps 150, returns 150; a second settle is a no-op.
    assert pc.settle_ai_video_once("j1", 0.50) == 150
    assert pc.settle_ai_video_once("j1", 0.50) == 0
    # Settle never charges more than was reserved.
    assert pc.settle_ai_video_once("j2", 9.99) == 0
    # A failure returns what the job still holds, once.
    assert pc.refund_job_once("j2")[pc.KIND_AI_VIDEO] == 100
    assert pc.refund_job_once("j2")[pc.KIND_AI_VIDEO] == 0
    assert _balances(db, uid)[2] == 500 - 150


# --------------------------------------------------------------------------- #
# Reel admission (unit)
# --------------------------------------------------------------------------- #
def _params(**over):
    base = dict(layout="captions_only", voice_name="elevenlabs:abc", language="en",
                voiceover_key="", screen_recording_key="", video_script="",
                target_duration_s=30, avatar_provider="heygen")
    base.update(over)
    from app.services.reelforge import ReelForgeParams

    fields = {k: v for k, v in base.items() if k in ReelForgeParams.__dataclass_fields__}
    return ReelForgeParams(video_subject="cats", **fields)


def test_unfunded_premium_voice_is_narrated_with_a_free_voice(db, monkeypatch):
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
    uid = _user(db)
    with db() as s:
        plan = premium.plan_job(s, uid, _params(), 1)
    assert plan.voice_downgraded and plan.voice_credits == 0
    assert plan.params.voice_name == formats.free_voice_for("en")


def test_funded_premium_voice_keeps_elevenlabs_and_costs_its_price_per_variant(db, monkeypatch):
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
    uid = _user(db, voice=4)
    with db() as s:
        # MG3: 30 s of ElevenLabs is ~$0.135; 3x that is 2 credits at $0.36 each.
        plan = premium.plan_job(s, uid, _params(), 2)
        assert plan.voice_credits == 2 and plan.params.voice_name == "elevenlabs:abc"
        # Three variants need six credits: not enough, so the voice is free.
        assert premium.plan_job(s, uid, _params(), 3).voice_downgraded


def test_elevenlabs_music_needs_its_own_premium_credit(db, monkeypatch):
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
    monkeypatch.setattr(premium, "uses_elevenlabs_music", lambda params: bool(params.music_prompt))
    monkeypatch.setattr(premium, "_without_elevenlabs_music",
                        lambda params: __import__("dataclasses").replace(params, music_prompt=""))
    uid = _user(db, voice=2)
    with db() as s:
        plan = premium.plan_job(s, uid, _params(music_prompt="lofi"), 1)
    # Two credits: the voice (2) gets them, the music (3) falls back (no ElevenLabs call).
    assert (plan.voice_credits, plan.music_credits) == (2, 0)
    assert plan.music_downgraded and plan.params.music_prompt == ""
    uid2 = _user(db, credits=1, voice=5)
    with db() as s:
        plan = premium.plan_job(s, uid2, _params(music_prompt="lofi"), 1)
        assert plan.premium_credits == 5
        premium.debit_job(s, uid2, "job-m", plan)
        assert pc.balance(s, uid2, pc.KIND_PREMIUM_VOICE) == 0


def test_compose_skips_unfunded_elevenlabs_music(monkeypatch):
    from app.services import reelforge

    monkeypatch.setattr(premium, "uses_elevenlabs_music", lambda params: True)
    monkeypatch.setattr(premium, "premium_music_funded", lambda job_id, ctx=None: False)

    def must_not_generate(**_kwargs):
        raise AssertionError("ElevenLabs music must not be called")

    monkeypatch.setattr("app.services.bgm_ai.generate_ai_bgm", must_not_generate)
    params = _params(music_prompt="lofi")
    assert reelforge._prepare_ai_music("job-1", params, "/tmp/v.mp4", "/tmp", 30.0) == (None, "")


def test_presenter_reel_needs_ai_video_credits(db, monkeypatch):
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: False)
    uid = _user(db, ai=100)
    params = _params(layout="avatar_bottom_screen_top", voice_name="en-US-AriaNeural-Female")
    needed = premium.ai_video_credits_needed(params)
    assert needed == pc.ai_video_credits_for_usd(0.375)  # 30 s of HeyGen, 3x
    with db() as s, pytest.raises(premium.PremiumCreditsRequired) as exc:
        premium.plan_job(s, uid, params, 1)
    assert exc.value.needed == needed and exc.value.available == 100
    uid2 = _user(db, credits=1, ai=needed)
    with db() as s:
        assert premium.plan_job(s, uid2, params, 1).ai_video_credits == needed


# --------------------------------------------------------------------------- #
# HTTP: POST /jobs never lets a standard credit pay a premium provider
# --------------------------------------------------------------------------- #
@pytest.fixture()
def api(db, monkeypatch):
    pipeline = _FakePipeline()
    monkeypatch.setattr(jobs_mod, "_import_pipeline", lambda rid: pipeline)
    monkeypatch.setattr(jobs_mod, "_validate_enabled_feature_secrets", lambda params, rid: None)
    app = FastAPI()
    app.include_router(jobs_mod.router)

    def handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, handler)
    return TestClient(app), pipeline


def test_presenter_job_without_ai_credits_is_402_and_charges_nothing(db, api):
    client, pipeline = api
    uid = _user(db, credits=5)
    _pro(db, uid)
    res = client.post("/api/v1/jobs", json={"params": {"video_subject": "cats"}}, headers=_HEADERS)
    assert res.status_code == 402, res.text
    assert res.json()["data"]["code"] == "ai_video_credits_required"
    assert _balances(db, uid) == (5, 0, 0)
    assert pipeline.start_calls == []
    with db() as s:
        assert JobRepository(s).list_for_user(uid) == []


def test_presenter_job_reserves_ai_credits_and_standard_credit(db, api):
    client, pipeline = api
    uid = _user(db, credits=10, ai=1000)
    _pro(db, uid)
    res = client.post("/api/v1/jobs", json={"params": {"video_subject": "cats"}}, headers=_HEADERS)
    assert res.status_code == 200, res.text
    standard, _voice, ai = _balances(db, uid)
    # MD8: a presenter reel is 5 standard credits plus its AI-video reservation.
    assert standard == 5 and 0 < ai < 1000
    job_id = res.json()["data"]["job_id"]
    with db() as s:
        stored = JobRepository(s).get(job_id).params
    assert stored[premium.MARKER_KEY]["ai_video_credits"] == 1000 - ai
    assert premium.ai_video_funded(job_id) is True
    # Terminal failure returns the reservation.
    premium.refund_job(job_id)
    assert _balances(db, uid)[2] == 1000


def test_premium_voice_job_without_credit_stores_the_free_voice(db, api, monkeypatch):
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
    client, pipeline = api
    uid = _user(db, credits=5)
    body = {"params": {"video_subject": "cats", "layout": "captions_only", "voice_name": "elevenlabs:abc"}}
    res = client.post("/api/v1/jobs", json=body, headers=_HEADERS)
    assert res.status_code == 200, res.text
    _, enqueued = pipeline.start_calls[0]
    assert enqueued.voice_name == formats.free_voice_for("en")
    job_id = res.json()["data"]["job_id"]
    assert premium.premium_voice_funded(job_id) is False
    assert _balances(db, uid) == (4, 0, 0)


def test_premium_voice_job_with_credit_debits_its_price(db, api, monkeypatch):
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
    client, pipeline = api
    uid = _user(db, credits=5, voice=3)
    body = {"params": {"video_subject": "cats", "layout": "captions_only", "voice_name": "elevenlabs:abc"}}
    res = client.post("/api/v1/jobs", json=body, headers=_HEADERS)
    assert res.status_code == 200, res.text
    _, enqueued = pipeline.start_calls[0]
    assert enqueued.voice_name == "elevenlabs:abc"
    assert premium.premium_voice_funded(res.json()["data"]["job_id"]) is True
    assert _balances(db, uid) == (4, 1, 0)


# --------------------------------------------------------------------------- #
# Pipeline guards
# --------------------------------------------------------------------------- #
def test_guards_fail_closed_and_honour_operator_and_wallet(db, monkeypatch):
    uid = _user(db)
    with db() as s:
        plain = Job(user_id=uid, kind="avatar_reel", params={})
        wallet = Job(user_id=uid, kind="avatar_reel", params={"_wallet": {"reserved_micros": 1}})
        s.add_all([plain, wallet])
        s.commit()
        plain_id, wallet_id = plain.id, wallet.id
    assert premium.ai_video_funded(plain_id) is False
    assert premium.premium_voice_funded(plain_id) is False
    assert premium.ai_video_funded("missing-job") is False
    assert premium.ai_video_funded("missing-job", {premium.OPERATOR_FUNDED_CTX_KEY: True}) is True
    monkeypatch.setattr("app.domains.reels.wallet_bridge.read_marker", lambda p: bool(p.get("_wallet")))
    assert premium.ai_video_funded(wallet_id) is True


def test_avatar_stage_refuses_an_unfunded_presenter_call(monkeypatch):
    from app.services import reelforge

    monkeypatch.setattr(premium, "ai_video_funded", lambda job_id, ctx=None: False)

    def must_not_call(_pid):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr("app.services.avatar.get_avatar_provider", must_not_call)
    params = _params(layout="avatar_bottom_screen_top", avatar_id="a1")
    with pytest.raises(reelforge.ReelForgeStageError, match="AI-video credits"):
        reelforge.stage_avatar("job-1", params, {"audio_url": "https://x/a.mp3"})


# --------------------------------------------------------------------------- #
# Dodo packs: checkout, fulfilment once, refund clawback
# --------------------------------------------------------------------------- #
@pytest.fixture()
def dodo(monkeypatch):
    from app.config import config

    monkeypatch.setattr(
        config,
        "dodo",
        {"api_key": "k", "premium_voice_25_product_id": "pdt_voice", "ai_video_2000_product_id": "pdt_ai"},
        raising=False,
    )
    calls = []

    def fake_checkout(**kwargs):
        calls.append(kwargs)
        return {"session_id": "cks_1", "checkout_url": "https://checkout.dodopayments.com/cks_1"}

    monkeypatch.setattr(dodo_client, "create_checkout", fake_checkout)
    return calls


def test_premium_pack_payment_grants_once_and_refund_claws_back(db, dodo):
    uid = _user(db, credits=0)
    view = {"payment_id": "pay_1", "product_ids": ["pdt_ai"], "metadata": {"user_id": uid}, "status": "succeeded"}
    first = dodo_billing.fulfill_payment(view, external_event_id="evt_1")
    again = dodo_billing.fulfill_payment(view, external_event_id="return:pay_1")
    assert first["kind"] == pc.KIND_AI_VIDEO and first["granted"] == 2000
    assert again["granted"] == 0
    assert _balances(db, uid) == (0, 0, 2000)
    assert pc.clawback_by_reference("dodo", "pay_1") == 2000
    assert pc.clawback_by_reference("dodo", "pay_1") == 0
    assert _balances(db, uid) == (0, 0, 0)


def test_premium_endpoints(db, dodo, monkeypatch):
    from app.controllers.v1 import premium_credits as ctrl
    from app.services.billing import payments_mode

    uid = _user(db, voice=4)
    monkeypatch.setattr(ctrl, "get_session", db_base.get_session)
    monkeypatch.setattr(ctrl, "require_checkout_enabled", lambda rid: None)
    monkeypatch.setattr(ctrl, "resolve_principal", lambda *_a: SimpleNamespace(id=uid, email="b@example.com"))
    app = FastAPI()
    app.include_router(ctrl.router)

    def handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, handler)
    client = TestClient(app)

    status = client.get("/api/v1/billing/premium").json()["data"]
    assert status["balances"][pc.KIND_PREMIUM_VOICE] == 4
    assert {p["key"] for p in status["packs"]} == {"premium_voice_25", "ai_video_2000"}
    assert status["ai_video_markup"] == 3

    monkeypatch.setattr(payments_mode, "active_provider", lambda: payments_mode.NONE)
    assert client.post("/api/v1/billing/premium/checkout", json={"pack_key": "ai_video_2000"}).status_code == 409

    monkeypatch.setattr(payments_mode, "active_provider", lambda: payments_mode.DODO)
    assert client.post("/api/v1/billing/premium/checkout", json={"pack_key": "nope"}).status_code == 400
    res = client.post("/api/v1/billing/premium/checkout", json={"pack_key": "premium_voice_25"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["checkout_url"].startswith("https://checkout.dodopayments.com/")
    assert dodo[-1]["product_id"] == "pdt_voice"
    assert dodo[-1]["metadata"]["kind"] == dodo_client.KIND_PREMIUM_PACK


# --------------------------------------------------------------------------- #
# Premium dubbing and per-job actuals
# --------------------------------------------------------------------------- #
def test_elevenlabs_dub_costs_premium_voice_credits_not_extra_standard_credits():
    from app.domains.dub import catalog

    free = catalog.resolve_plan(source_language="en", target_language="es", voice_engine="edge")
    paid = catalog.resolve_plan(
        source_language="en", target_language="es", voice_engine="elevenlabs",
        voice="Rachel", elevenlabs_ok=True,
    )
    assert (free.credits_cost, free.premium_voice_credits) == (catalog.DEFAULT_FREE_COST, 0)
    assert paid.credits_cost == free.credits_cost
    assert paid.premium_voice_credits == catalog.DEFAULT_PREMIUM_VOICE_CREDITS


def test_stage_actuals_rows():
    from app.workers.tasks import _stage_cost_row

    params = SimpleNamespace(video_script="", voice_name="elevenlabs:abc", avatar_provider="heygen")
    calls = [{"model": "litellm/anthropic/claude-sonnet-5", "prompt_chars": 400, "completion_chars": 800, "ok": True}]
    usd, meta = _stage_cost_row("script", params, {}, {}, 1200, calls)
    assert meta["model"] == "litellm/anthropic/claude-sonnet-5"
    assert (meta["prompt_tokens"], meta["completion_tokens"]) == (100, 200)
    assert usd > 0

    ctx = {"script": "x" * 1000}
    usd, meta = _stage_cost_row("tts", params, ctx, {"tts_voice": "en-US-AriaNeural-Female"}, 10, None)
    assert usd == 0.0 and meta["voice_engine"] == "free" and meta["voice_chars"] == 1000
    usd, meta = _stage_cost_row("tts", params, ctx, {"tts_voice": "elevenlabs:abc"}, 10, None)
    assert usd > 0 and meta["voice_engine"] == "elevenlabs"

    assert _stage_cost_row("avatar", params, {"audio_duration": 30.0}, {"avatar_key": ""}, 10, None) is None
    usd, meta = _stage_cost_row("avatar", params, {}, {"avatar_key": "k", "avatar_duration": 60.0}, 10, None)
    assert meta["provider_seconds"] == 60.0 and usd > 0

    usd, meta = _stage_cost_row("compose", params, {}, {}, 90_000, None)
    assert meta["render_seconds"] == 90.0 and usd >= 0
    assert _stage_cost_row("captions", params, {}, {}, 10, None) is None


def test_llm_usage_is_captured_per_stage(monkeypatch):
    from app.services import llm
    from app.telemetry import llm_usage

    monkeypatch.setattr(llm, "_generate_response_uncounted", lambda prompt, app_config=None: "hello world")
    token = llm_usage.begin()
    llm._generate_response("abcd" * 10, app_config={"llm_provider": "litellm", "litellm_model_name": "anthropic/claude-sonnet-5"})
    calls = llm_usage.end(token)
    assert calls == [{"model": "litellm/anthropic/claude-sonnet-5", "prompt_chars": 40, "completion_chars": 11, "ok": True}]
    # Outside a capture nothing is recorded (and nothing breaks).
    llm._generate_response("x")


def test_measured_avatar_cost_reads_cost_events(db):
    uid = _user(db)
    with db() as s:
        job = Job(user_id=uid, kind="avatar_reel", params={})
        s.add(job)
        s.flush()
        s.add_all([
            JobEvent(job_id=job.id, stage="avatar", status="cost", cost_usd=0.2),
            JobEvent(job_id=job.id, stage="tts", status="cost", cost_usd=0.9),
        ])
        s.commit()
        job_id = job.id
    assert premium.measured_avatar_usd(job_id) == pytest.approx(0.2)


# --------------------------------------------------------------------------- #
# Copied jobs (re-run, dub) and stored downgrades
# --------------------------------------------------------------------------- #
def test_planned_params_store_downgrades_and_drop_a_copied_wallet_marker():
    plan = premium.PremiumPlan(
        params=_params(voice_name="en-US-AriaNeural", music_prompt=""),
        voice_downgraded=True,
        music_downgraded=True,
    )
    source = {
        "voice_name": "elevenlabs:abc",
        "music_prompt": "lofi",
        "bgm_provider": "elevenlabs",
        "_wallet": {"reserved_micros": 1, "mint_hold_id": "hold-of-the-source"},
    }
    copied = jobs_mod._planned_params(source, plan.params, plan, copied=True)
    assert "_wallet" not in copied
    assert copied["voice_name"] == "en-US-AriaNeural"
    assert copied["music_prompt"] == ""
    assert copied[premium.MARKER_KEY]["voice_credits"] == 0
    # The source dict is never mutated, and a retry keeps its own wallet marker.
    assert source["_wallet"]["mint_hold_id"] == "hold-of-the-source"
    retried = jobs_mod._planned_params(source, plan.params, plan, copied=False)
    assert retried["_wallet"] == source["_wallet"]


def test_rerun_of_a_wallet_job_is_not_wallet_funded(db, api, monkeypatch):
    monkeypatch.setattr(formats, "elevenlabs_configured", lambda: True)
    client, pipeline = api
    uid = _user(db, credits=5)
    with db() as s:
        source = Job(
            user_id=uid,
            kind="avatar_reel",
            state=1,
            params={
                "video_subject": "cats",
                "layout": "captions_only",
                "voice_name": "elevenlabs:abc",
                "_wallet": {"reserved_micros": 1, "mint_hold_id": "hold-of-the-source"},
            },
        )
        s.add(source)
        s.commit()
        source_id = source.id
    res = client.post(f"/api/v1/jobs/{source_id}/rerun", json={}, headers=_HEADERS)
    assert res.status_code == 200, res.text
    new_id = res.json()["data"]["job_id"]
    with db() as s:
        stored = JobRepository(s).get(new_id).params
    assert "_wallet" not in stored
    assert stored["voice_name"] == formats.free_voice_for("en")
    assert premium.premium_voice_funded(new_id) is False
