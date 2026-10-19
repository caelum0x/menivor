"""Cost-cap admission tests: reject before a provider call, debit, or enqueue."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import cost_guard
from app.models.db.base import Base
from app.models.db.models import CreditLedger, User
from app.models.db.repositories import CreditRepository, JobRepository
from app.services.reelforge import ReelForgeParams


def test_estimate_accounts_for_bring_your_own_voice_and_manual_script():
    estimate = cost_guard.estimate_job_cost(
        ReelForgeParams(
            video_subject="cats",
            video_script="A short script",
            voiceover_key="uploads/voice.wav",
            avatar_provider="latentsync",
            target_duration_s=60,
        )
    )

    assert estimate.llm_usd == 0.0
    assert estimate.tts_usd == 0.0
    assert estimate.avatar_usd == pytest.approx(0.03)


def test_cost_cap_rejects_an_over_budget_job(monkeypatch):
    monkeypatch.setattr(cost_guard, "max_job_cost_usd", lambda: 0.1)
    params = ReelForgeParams(
        video_subject="cats", avatar_provider="heygen", target_duration_s=60
    )

    with pytest.raises(cost_guard.CostCapExceeded, match="exceeds per-job cap"):
        cost_guard.enforce_cost_cap(params)


def test_cost_cap_can_be_explicitly_disabled(monkeypatch):
    monkeypatch.setattr(cost_guard, "max_job_cost_usd", lambda: 0.0)
    params = ReelForgeParams(
        video_subject="cats", avatar_provider="heygen", target_duration_s=60
    )

    assert cost_guard.enforce_cost_cap(params).total_usd > 0


def test_runtime_cap_refund_is_idempotent(monkeypatch):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Factory.begin() as session:
        user = User(email="cost-refund@example.com")
        session.add(user)
        session.flush()
        CreditRepository(session).grant(user.id, 3, "signup")
        job = JobRepository(session).create(user.id, "avatar_reel", {})
        CreditRepository(session).debit(user.id, 1, job.id, "job_debit")
        job_id, user_id = job.id, user.id

    from contextlib import contextmanager

    @contextmanager
    def fake_get_session():
        with Factory.begin() as session:
            yield session

    monkeypatch.setattr("app.models.db.base.get_session", fake_get_session)

    assert cost_guard.refund_cost_capped_job_once(job_id) is True
    assert cost_guard.refund_cost_capped_job_once(job_id) is False
    with Factory() as session:
        ledger = session.query(CreditLedger).filter_by(job_id=job_id).all()
        assert [entry.reason for entry in ledger] == ["job_debit", "cost_cap_refund"]
        assert CreditRepository(session).balance(user_id) == 3


def _faceless(**overrides):
    base = dict(
        video_subject="why cats knock things off tables",
        layout="captions_only",
        voice_name="en-US-JennyNeural-Female",
        target_duration_s=60,
    )
    base.update(overrides)
    return ReelForgeParams(**base)


def test_faceless_tts_with_a_free_voice_prices_script_llm_and_render():
    estimate = cost_guard.estimate_job_cost(_faceless())

    assert cost_guard._is_faceless_tts(_faceless())
    assert estimate.llm_usd > 0
    assert estimate.tts_usd == 0.0  # Edge TTS is free
    assert estimate.avatar_usd == 0.0
    assert estimate.render_usd == pytest.approx(0.01)  # 1 min at the default rate
    assert estimate.total_usd == pytest.approx(estimate.llm_usd + estimate.render_usd)


def test_faceless_tts_with_a_metered_voice_prices_the_characters():
    script = "x" * 2000
    estimate = cost_guard.estimate_job_cost(
        _faceless(voice_name="elevenlabs:abc123:Rachel", video_script=script)
    )

    assert estimate.llm_usd == 0.0  # typed script skips generation
    assert estimate.tts_usd == pytest.approx(0.30)  # 2k chars at $0.15/1k
    assert estimate.avatar_usd == 0.0


def test_faceless_tts_azure_v2_voice_is_metered():
    estimate = cost_guard.estimate_job_cost(
        _faceless(voice_name="en-US-AvaMultilingualNeural-V2-Female")
    )
    assert estimate.tts_usd > 0


def test_captions_only_over_an_uploaded_recording_stays_free():
    estimate = cost_guard.estimate_job_cost(
        _faceless(screen_recording_key="uploads/rec.mp4")
    )
    assert estimate.total_usd == 0.0
    assert not cost_guard._is_faceless_tts(_faceless(voiceover_key="uploads/v.wav"))


def test_render_rate_reads_config_and_falls_back_on_garbage(monkeypatch):
    monkeypatch.setitem(cost_guard.config.app, "reelforge_render_usd_per_min", 0.06)
    assert cost_guard.estimate_job_cost(_faceless(target_duration_s=30)).render_usd == pytest.approx(0.03)
    monkeypatch.setitem(cost_guard.config.app, "reelforge_render_usd_per_min", "nope")
    assert cost_guard.render_usd_per_min() == pytest.approx(0.01)
