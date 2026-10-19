"""Wave E M-1 (hand-off H3): every render surface prices like a create.

* Series / Autopilot debit the per-SKU price (``reels/pricing.py``), not a flat
  credit, and presenter renders keep the Pro gate and AI-video credits.
* The winner loop's remake estimate is per-SKU.
* A wallet-funded create enforces the Pro presenter gate.
* Refunded or failed presenter jobs do not count toward the monthly cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.domains.reels import policy
from app.models import const
from app.models.db.models import CreditLedger, Job
from app.models.db.repositories import CreditRepository, JobRepository
from app.services.billing import premium_credits as pc
from tests.reelforge.test_mn1_series_charge import (  # noqa: F401 - fixtures
    _Enqueue,
    _channel,
    _jobs,
    _user as _series_user,
    factory,
    signals,
)
from tests.reelforge.test_premium_credits import (  # noqa: F401 - fixtures
    _HEADERS,
    _balances,
    _pro,
    _user,
    api,
    db,
)


# --------------------------------------------------------------------------- #
# render_credits
# --------------------------------------------------------------------------- #
def test_render_credits_reads_stored_dicts_and_objects():
    assert policy.render_credits({"layout": "captions_only", "target_duration_s": 30}) == 1
    assert policy.render_credits({"layout": "captions_only", "target_duration_s": 90}) == 2
    assert policy.render_credits({"layout": "captions_only", "target_duration_s": 181}) == 4
    assert policy.render_credits({"layout": "split", "target_duration_s": 30}) == (
        policy.DEFAULT_PRESENTER_CREDITS
    )
    assert policy.render_credits(SimpleNamespace(layout="captions_only", target_duration_s=61)) == 2


# --------------------------------------------------------------------------- #
# Series / Autopilot
# --------------------------------------------------------------------------- #
@dataclass
class _Params:
    video_script: str
    aspect: str
    platforms: tuple
    layout: str = "captions_only"
    target_duration_s: int = 30
    avatar_provider: str = ""


class _Contract:
    def __init__(self, **fields):
        self.fields = fields

    def build_script(self, item, *, max_words):
        return str(item.get("body") or "")

    def build_params(self, script, *, subject, aspect, voice_id, platforms):
        return _Params(video_script=script, aspect=aspect, platforms=tuple(platforms), **self.fields)


def _run(maker, user_id, channel_id, n_items, contract, enqueue=None):
    from app.domains.series.repository import ChannelClipRepository
    from app.domains.series.runner import ChannelRunConfig, RunnerDeps, run_channel

    enqueue = enqueue or _Enqueue()
    with maker() as s:
        deps = RunnerDeps(
            job_repo=JobRepository(s),
            clip_repo=ChannelClipRepository(s),
            start_pipeline=enqueue,
            schedule_publish=lambda *a, **k: None,
            session=s,
            contract=contract,
            raise_when_unfunded=False,
        )
        config = ChannelRunConfig(channel_id=channel_id, user_id=user_id, max_per_account=0)
        try:
            return run_channel(
                config, source_items=[{"body": f"story {i}"} for i in range(n_items)], deps=deps
            ), enqueue
        finally:
            s.commit()


def _balance(maker, user_id) -> int:
    with maker() as s:
        return CreditRepository(s).balance(user_id)


def _job_debits(maker) -> list[int]:
    with maker() as s:
        rows = s.query(CreditLedger).filter(CreditLedger.delta < 0).order_by(CreditLedger.id)
        return [int(r.delta) for r in rows]


def test_series_long_form_debits_per_started_minute(factory, signals):  # noqa: F811
    user_id = _series_user(factory, 5)
    channel_id = _channel(factory, user_id)
    result, enqueue = _run(factory, user_id, channel_id, 3, _Contract(target_duration_s=90))
    # 5 credits pay two 2-credit renders; the third is unfunded.
    assert result.rendered == 2 and len(enqueue.calls) == 2
    assert _job_debits(factory) == [-2, -2]
    assert _balance(factory, user_id) == 1
    assert result.paused_reason == "credits"
    assert result.unfunded_needed == 2


def test_series_unfunded_402_names_the_per_sku_price(factory, signals):  # noqa: F811
    from app.domains.reels.charge import CreditsRequired
    from app.domains.series.repository import ChannelClipRepository
    from app.domains.series.runner import ChannelRunConfig, RunnerDeps, run_channel

    user_id = _series_user(factory, 1)
    channel_id = _channel(factory, user_id)
    with factory() as s:
        deps = RunnerDeps(
            job_repo=JobRepository(s),
            clip_repo=ChannelClipRepository(s),
            start_pipeline=_Enqueue(),
            schedule_publish=lambda *a, **k: None,
            session=s,
            contract=_Contract(target_duration_s=150),
        )
        config = ChannelRunConfig(channel_id=channel_id, user_id=user_id, max_per_account=0)
        with pytest.raises(CreditsRequired) as exc:
            run_channel(config, source_items=[{"body": "x"}], deps=deps)
    assert exc.value.needed == 3


def test_series_presenter_below_pro_renders_nothing_and_debits_nothing(factory, signals):  # noqa: F811
    user_id = _series_user(factory, 20)
    channel_id = _channel(factory, user_id)
    result, enqueue = _run(factory, user_id, channel_id, 2, _Contract(layout="split"))
    assert result.rendered == 0 and enqueue.calls == []
    assert _jobs(factory) == 0
    assert _balance(factory, user_id) == 20


def test_series_presenter_on_pro_debits_floor_and_ai_video_credits(factory, signals):  # noqa: F811
    from app.models.db.creator_subscription import CreatorSubscription

    user_id = _series_user(factory, 20)
    with factory() as s:
        s.add(CreatorSubscription(user_id=user_id, plan_key="pro", status="active"))
        pc.grant(s, user_id, pc.KIND_AI_VIDEO, 10_000, "test_grant")
        s.commit()
    channel_id = _channel(factory, user_id)
    result, _enqueue = _run(
        factory, user_id, channel_id, 1, _Contract(layout="split", avatar_provider="heygen")
    )
    assert result.rendered == 1
    assert _balance(factory, user_id) == 20 - policy.DEFAULT_PRESENTER_CREDITS
    with factory() as s:
        assert pc.balance(s, user_id, pc.KIND_AI_VIDEO) < 10_000


# --------------------------------------------------------------------------- #
# Winner loop estimate
# --------------------------------------------------------------------------- #
def test_winner_loop_estimate_is_per_sku():
    from app.domains.insights.winner_loop_service import _remake_unit_credits

    short = SimpleNamespace(params={"layout": "captions_only", "target_duration_s": 30})
    long = SimpleNamespace(params={"layout": "captions_only", "target_duration_s": 150})
    presenter = SimpleNamespace(params={"layout": "split", "target_duration_s": 30})
    assert _remake_unit_credits([short]) == 1
    assert _remake_unit_credits([short, long]) == 3
    assert _remake_unit_credits([presenter]) == policy.DEFAULT_PRESENTER_CREDITS


# --------------------------------------------------------------------------- #
# Wallet-funded create: Pro presenter gate
# --------------------------------------------------------------------------- #
@pytest.fixture()
def wallet_stub(monkeypatch):
    from app.domains.reels import wallet_bridge

    reserved: list[str] = []
    monkeypatch.setattr(wallet_bridge, "validate_intent", lambda session, intent, rid: None)

    def _reserve(session, *, user_id, intent, job_id, request_id):
        reserved.append(job_id)
        return {"_wallet": {"reserved_micros": intent.max_cost_micros}}

    monkeypatch.setattr(wallet_bridge, "reserve_for_job", _reserve)
    return reserved


def _wallet_presenter() -> dict:
    return {
        "params": {"video_subject": "cats", "target_duration_s": 30},
        "generation_profile_id": "presenter-fast",
        "quote": {"max_cost_micros": 500_000},
    }


@pytest.mark.parametrize("plan", [None, "creator"])
def test_wallet_funded_presenter_is_refused_below_pro(db, api, wallet_stub, plan):  # noqa: F811
    client, pipeline = api
    uid = _user(db, credits=10)
    if plan:
        _pro(db, uid, plan)
    res = client.post("/api/v1/jobs", json=_wallet_presenter(), headers=_HEADERS)
    assert res.status_code == 402, res.text
    assert res.json()["data"]["code"] == "sku_locked"
    assert wallet_stub == [] and pipeline.start_calls == []
    with db() as s:
        assert JobRepository(s).list_for_user(uid) == []


def test_wallet_funded_presenter_on_pro_is_accepted(db, api, wallet_stub):  # noqa: F811
    client, _pipeline = api
    uid = _user(db, credits=10)
    _pro(db, uid)
    res = client.post("/api/v1/jobs", json=_wallet_presenter(), headers=_HEADERS)
    assert res.status_code == 200, res.text
    assert len(wallet_stub) == 1


# --------------------------------------------------------------------------- #
# Presenter cap excludes refunded jobs
# --------------------------------------------------------------------------- #
def _presenter() -> dict:
    return {"params": {"video_subject": "cats", "target_duration_s": 30}}


@pytest.mark.parametrize("how", ["ledger_refund", "failed_state"])
def test_refunded_presenter_job_does_not_use_the_cap(db, api, monkeypatch, how):  # noqa: F811
    monkeypatch.setenv("MENIVOR_PRESENTER_MONTHLY_CAP", "1")
    client, _pipeline = api
    uid = _user(db, credits=20, ai=10_000)
    _pro(db, uid)
    first = client.post("/api/v1/jobs", json=_presenter(), headers=_HEADERS)
    assert first.status_code == 200, first.text
    job_id = first.json()["data"]["job_id"]
    with db() as s:
        assert policy.presenter_reels_this_month(s, uid) == 1
        if how == "ledger_refund":
            CreditRepository(s).grant(uid, policy.DEFAULT_PRESENTER_CREDITS, "failure_refund", job_id=job_id)
        else:
            s.get(Job, job_id).state = const.TASK_STATE_FAILED
        s.commit()
    with db() as s:
        assert policy.presenter_reels_this_month(s, uid) == 0
    second = client.post("/api/v1/jobs", json=_presenter(), headers=_HEADERS)
    assert second.status_code == 200, second.text
    third = client.post("/api/v1/jobs", json=_presenter(), headers=_HEADERS)
    assert third.status_code == 402 and third.json()["data"]["code"] == "sku_locked"


def test_retried_presenter_job_counts_again(db, api, monkeypatch):  # noqa: F811
    """Refund then a new debit (retry): the newest row is a debit, so it counts."""
    client, _pipeline = api
    uid = _user(db, credits=20, ai=10_000)
    _pro(db, uid)
    job_id = client.post("/api/v1/jobs", json=_presenter(), headers=_HEADERS).json()["data"]["job_id"]
    with db() as s:
        CreditRepository(s).grant(uid, 5, "refund", job_id=job_id)
        CreditRepository(s).debit(uid, 5, job_id, policy.JOB_DEBIT_REASON)
        s.commit()
    with db() as s:
        assert policy.presenter_reels_this_month(s, uid) == 1


# --------------------------------------------------------------------------- #
# Wave E verifier: Autopilot presenter renders are funded end to end
# --------------------------------------------------------------------------- #
def _pro_with_ai(maker, user_id, ai: int = 10_000) -> None:
    from app.models.db.creator_subscription import CreatorSubscription

    with maker() as s:
        s.add(CreatorSubscription(user_id=user_id, plan_key="pro", status="active"))
        pc.grant(s, user_id, pc.KIND_AI_VIDEO, ai, "test_grant")
        s.commit()


def test_series_presenter_job_carries_the_ai_video_marker(factory, signals):  # noqa: F811
    """The avatar stage reads ``_premium.ai_video_credits`` from ``Job.params``;
    without it a paid Autopilot presenter render fails at the avatar stage."""
    from app.domains.reels.premium import MARKER_KEY

    user_id = _series_user(factory, 20)
    _pro_with_ai(factory, user_id)
    channel_id = _channel(factory, user_id)
    result, _enqueue = _run(
        factory, user_id, channel_id, 1, _Contract(layout="split", avatar_provider="heygen")
    )
    assert result.rendered == 1
    with factory() as s:
        job = s.get(Job, result.job_ids[0])
        marker = (job.params or {}).get(MARKER_KEY) or {}
        assert int(marker.get("ai_video_credits") or 0) > 0


def test_series_premium_debit_failure_rolls_back_the_standard_debit(
    factory, signals, monkeypatch  # noqa: F811
):
    """A concurrent AI-video spend between plan and debit leaves no standard debit."""
    from app.domains.reels import premium

    user_id = _series_user(factory, 20)
    _pro_with_ai(factory, user_id)
    channel_id = _channel(factory, user_id)

    def _drained(*_a, **_k):
        raise premium.PremiumCreditsRequired(100, 0)

    monkeypatch.setattr(premium, "debit_job", _drained)
    result, enqueue = _run(
        factory, user_id, channel_id, 1, _Contract(layout="split", avatar_provider="heygen")
    )
    assert result.rendered == 0 and enqueue.calls == []
    assert _balance(factory, user_id) == 20
    assert _job_debits(factory) == []
