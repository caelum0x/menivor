"""MN1: Autopilot (series channel) renders pay one credit each.

Real SQLite ledger + jobs + channel definitions; only the story contract and
the Celery enqueue are fakes.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.reels import charge as charge_mod
from app.domains.series import channels as channel_store
from app.domains.series import runner as runner_mod
from app.domains.series.repository import ChannelClipRepository
from app.domains.series.runner import (
    CHANNEL_PAUSED,
    ChannelRunConfig,
    RunnerDeps,
    channel_signals,
    run_channel,
)
from app.models.db.base import Base
from app.models.db.models import CreditLedger, Job, User
from app.models.db.repositories import CreditRepository, JobRepository


@dataclass
class _Params:
    video_script: str
    aspect: str
    platforms: tuple


class _Contract:
    def build_script(self, item, *, max_words):
        return str(item.get("body") or "")

    def build_params(self, script, *, subject, aspect, voice_id, platforms):
        return _Params(video_script=script, aspect=aspect, platforms=tuple(platforms))


class _Enqueue:
    def __init__(self, fail: bool = False):
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, job_id, params):
        self.calls.append(job_id)
        if self.fail:
            raise RuntimeError("broker down")
        return "task"


@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    from app.models.db import base as db_base

    monkeypatch.setattr(db_base, "get_session", _session)
    return maker


@pytest.fixture()
def signals(monkeypatch):
    seen: list = []
    monkeypatch.setattr(runner_mod, "channel_signals", type(channel_signals)())
    runner_mod.channel_signals.subscribe(CHANNEL_PAUSED, seen.append)
    return seen


def _user(maker, credits: int) -> str:
    with maker() as s:
        user = User(email="a@example.com", api_key_hash=hashlib.sha256(b"a").hexdigest())
        s.add(user)
        s.flush()
        if credits:
            CreditRepository(s).grant(user.id, credits, "purchase")
        s.commit()
        return user.id


def _channel(maker, user_id: str) -> str:
    with maker() as s:
        row = channel_store.create_channel(
            s, user_id=user_id, name="Stories", config={}, source_items=[], autorun=True
        )
        s.commit()
        return row.channel_id


def _run(maker, user_id, channel_id, n_items, enqueue):
    with maker() as s:
        deps = RunnerDeps(
            job_repo=JobRepository(s),
            clip_repo=ChannelClipRepository(s),
            start_pipeline=enqueue,
            schedule_publish=lambda *a, **k: None,
            session=s,
            contract=_Contract(),
        )
        config = ChannelRunConfig(channel_id=channel_id, user_id=user_id, max_per_account=0)
        try:
            return run_channel(
                config, source_items=[{"body": f"story {i}"} for i in range(n_items)], deps=deps
            )
        finally:
            s.commit()


def _jobs(maker) -> int:
    with maker() as s:
        return int(s.execute(select(func.count()).select_from(Job)).scalar())


def _balance(maker, user_id) -> int:
    with maker() as s:
        return CreditRepository(s).balance(user_id)


def _paused_reason(maker, channel_id):
    with maker() as s:
        return (channel_store.get_definition(s, channel_id).params or {}).get("paused_reason")


def test_zero_balance_is_402_and_nothing_queued(factory, signals):
    user_id = _user(factory, 0)
    channel_id = _channel(factory, user_id)
    enqueue = _Enqueue()
    with pytest.raises(charge_mod.CreditsRequired) as exc:
        _run(factory, user_id, channel_id, 3, enqueue)
    assert exc.value.status_code == 402
    assert exc.value.data["code"] == "credits_required"
    assert enqueue.calls == []
    assert _jobs(factory) == 0
    assert _paused_reason(factory, channel_id) == "credits"
    assert len(signals) == 1 and signals[0].payload["reason"] == "credits"


def test_500_items_with_one_credit_renders_one_and_pauses(factory, signals):
    user_id = _user(factory, 1)
    channel_id = _channel(factory, user_id)
    enqueue = _Enqueue()
    result = _run(factory, user_id, channel_id, 500, enqueue)
    assert result.rendered == 1
    assert len(enqueue.calls) == 1
    assert result.paused_reason == "credits"
    assert result.summary()["paused_for_credits"] == 1
    assert result.unfunded == 499
    assert _jobs(factory) == 1
    assert _balance(factory, user_id) == 0
    assert _paused_reason(factory, channel_id) == "credits"
    assert [e.type for e in signals] == [CHANNEL_PAUSED]
    assert signals[0].key == channel_id and signals[0].payload["rendered"] == 1


def test_balance_n_queues_at_most_n(factory, signals):
    user_id = _user(factory, 3)
    channel_id = _channel(factory, user_id)
    enqueue = _Enqueue()
    result = _run(factory, user_id, channel_id, 10, enqueue)
    assert result.rendered == 3 and len(enqueue.calls) == 3


def test_pause_signals_once_and_top_up_resumes(factory, signals):
    user_id = _user(factory, 0)
    channel_id = _channel(factory, user_id)
    for _ in range(2):
        with pytest.raises(charge_mod.CreditsRequired):
            _run(factory, user_id, channel_id, 2, _Enqueue())
    assert len(signals) == 1  # still paused: no second email trigger
    with factory() as s:
        CreditRepository(s).grant(user_id, 2, "purchase")
        s.commit()
    result = _run(factory, user_id, channel_id, 2, _Enqueue())
    assert result.rendered == 2 and not result.paused_reason
    assert _paused_reason(factory, channel_id) is None


def test_failed_enqueue_refunds_exactly_once(factory, signals):
    user_id = _user(factory, 2)
    channel_id = _channel(factory, user_id)
    result = _run(factory, user_id, channel_id, 1, _Enqueue(fail=True))
    assert result.enqueue_failures == 1 and result.rendered == 0
    assert _balance(factory, user_id) == 2
    with factory() as s:
        job_id = s.execute(select(Job.id)).scalar()
    from app.domains.reels.refunds import refund_failed_reel_once

    assert refund_failed_reel_once(job_id) == 0  # the worker hook finds it already refunded
    assert _balance(factory, user_id) == 2
    with factory() as s:
        refunds = s.execute(
            select(func.count()).select_from(CreditLedger).where(CreditLedger.delta > 0, CreditLedger.job_id == job_id)
        ).scalar()
    assert refunds == 1


def test_failed_render_refunds_exactly_once(factory, signals):
    user_id = _user(factory, 1)
    channel_id = _channel(factory, user_id)
    _run(factory, user_id, channel_id, 1, _Enqueue())
    assert _balance(factory, user_id) == 0
    with factory() as s:
        job_id = s.execute(select(Job.id)).scalar()
        JobRepository(s).mark_failed(job_id, "compose", "boom")
        s.commit()
    from app.domains.reels.refunds import refund_failed_reel_once

    assert refund_failed_reel_once(job_id) == 1
    assert refund_failed_reel_once(job_id) == 0
    assert _balance(factory, user_id) == 1
