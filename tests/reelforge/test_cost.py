"""Unit tests for per-job USD cost telemetry (CTO plan §0 unit economics).

Covers:

* the three pure estimators (``estimate_llm_cost`` / ``estimate_tts_cost`` /
  ``estimate_avatar_cost``) — defaults, overrides, and defensive clamping;
* :func:`app.telemetry.cost.record_cost` writing a ``JobEvent`` row carrying the
  ``cost_usd`` / ``duration_ms`` fields against an in-memory SQLite DB.
"""

from __future__ import annotations

import math

import pytest

from app.telemetry import cost


# --------------------------------------------------------------------------- #
# estimate_llm_cost
# --------------------------------------------------------------------------- #
def test_estimate_llm_cost_default_model_is_under_a_cent_for_a_script() -> None:
    # A typical UGC script call: small prompt, ~250 output tokens. Plan target:
    # LLM cost < $0.01/job.
    result = cost.estimate_llm_cost("anthropic/claude-sonnet-5", 400, 250)
    # 400/1e6*3 + 250/1e6*15 = 0.0012 + 0.00375 = 0.00495
    assert result == pytest.approx(0.00495)
    assert result < 0.01


def test_estimate_llm_cost_unknown_model_falls_back_to_default() -> None:
    known = cost.estimate_llm_cost("anthropic/claude-sonnet-5", 1000, 1000)
    unknown = cost.estimate_llm_cost("some-brand-new-model", 1000, 1000)
    assert unknown == known


def test_estimate_llm_cost_accepts_price_override() -> None:
    prices = {"default": (10.0, 20.0)}
    # 1e6 input @ $10/1M + 1e6 output @ $20/1M = 30.0
    assert cost.estimate_llm_cost("x", 1_000_000, 1_000_000, prices=prices) == 30.0


def test_estimate_llm_cost_clamps_negative_tokens_to_zero() -> None:
    assert cost.estimate_llm_cost("anthropic/claude-sonnet-5", -100, -100) == 0.0


# --------------------------------------------------------------------------- #
# estimate_tts_cost
# --------------------------------------------------------------------------- #
def test_estimate_tts_cost_matches_plan_figure() -> None:
    # ~150-word narration ≈ 1000 chars → ~$0.15 (plan §6 unit economics).
    assert cost.estimate_tts_cost(1000) == pytest.approx(0.15)


def test_estimate_tts_cost_scales_linearly() -> None:
    assert cost.estimate_tts_cost(500) == pytest.approx(0.075)
    assert cost.estimate_tts_cost(2000) == pytest.approx(0.30)


def test_estimate_tts_cost_override_and_zero() -> None:
    assert cost.estimate_tts_cost(1000, usd_per_1k_chars=0.30) == pytest.approx(0.30)
    assert cost.estimate_tts_cost(0) == 0.0


def test_estimate_tts_cost_clamps_negative_chars() -> None:
    assert cost.estimate_tts_cost(-500) == 0.0


# --------------------------------------------------------------------------- #
# estimate_avatar_cost
# --------------------------------------------------------------------------- #
def test_estimate_avatar_cost_heygen_60s_in_plan_range() -> None:
    # HeyGen 60s → $0.75 midpoint (plan: ~$0.50–1.00/min).
    result = cost.estimate_avatar_cost(60.0, "heygen")
    assert result == pytest.approx(0.75)
    assert 0.50 <= result <= 1.00


def test_estimate_avatar_cost_latentsync_is_much_cheaper() -> None:
    # Tier-B self-hosted lip-sync ~$0.02–0.05/min.
    result = cost.estimate_avatar_cost(60.0, "latentsync")
    assert result == pytest.approx(0.03)
    assert result < cost.estimate_avatar_cost(60.0, "heygen")


def test_estimate_avatar_cost_unknown_provider_uses_default() -> None:
    assert cost.estimate_avatar_cost(60.0, "mystery") == cost.estimate_avatar_cost(
        60.0, "heygen"
    )


def test_estimate_avatar_cost_clamps_and_handles_nan() -> None:
    assert cost.estimate_avatar_cost(-10.0, "heygen") == 0.0
    assert cost.estimate_avatar_cost(math.nan, "heygen") == 0.0


# --------------------------------------------------------------------------- #
# record_cost (integration against in-memory SQLite)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def sqlite_db(monkeypatch: pytest.MonkeyPatch):
    """Build a fresh in-memory SQLite schema and point the telemetry layer at it.

    Uses a single shared in-memory connection (``StaticPool``) so the schema
    created here is visible to the session opened inside ``record_event``.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.db import base as db_base
    from app.models.db.base import Base
    from app.models.db.models import Job, User

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )

    # Redirect both the module-global SessionLocal (read by record_event) and the
    # get_session context manager to this in-memory engine.
    monkeypatch.setattr(db_base, "engine", engine, raising=False)
    monkeypatch.setattr(db_base, "SessionLocal", TestSession, raising=False)

    # Seed a user + job so the JobEvent FK is satisfiable.
    session = TestSession()
    user = User(id="u1", email="unit@example.com")
    job = Job(id="j1", user_id="u1")
    session.add_all([user, job])
    session.commit()
    session.close()

    yield TestSession
    engine.dispose()


def test_record_cost_writes_jobevent_with_cost_fields(sqlite_db) -> None:
    from app.models.db.models import JobEvent

    event = cost.record_cost(
        "j1", "tts", 0.153, duration_ms=1234, meta={"chars": 1020}
    )

    assert event is not None
    assert event.job_id == "j1"
    assert event.stage == "tts"
    assert event.status == cost.COST_EVENT_STATUS
    assert event.cost_usd == pytest.approx(0.153)
    assert event.duration_ms == 1234
    assert event.payload == {"chars": 1020}

    # Confirm it is actually persisted and queryable.
    session = sqlite_db()
    rows = session.query(JobEvent).filter_by(job_id="j1").all()
    session.close()
    assert len(rows) == 1
    assert rows[0].cost_usd == pytest.approx(0.153)
    assert rows[0].duration_ms == 1234


def test_record_cost_coerces_negative_cost_to_zero(sqlite_db) -> None:
    event = cost.record_cost("j1", "avatar", -5.0, duration_ms=-3)
    assert event is not None
    # Negative cost/duration are clamped to 0 at the persistence boundary.
    assert event.cost_usd == 0.0
    assert event.duration_ms == 0


def test_record_event_defaults_cost_fields_to_zero(sqlite_db) -> None:
    from app.telemetry.events import record_event

    event = record_event("j1", "script", "complete")
    assert event is not None
    assert event.cost_usd == 0.0
    assert event.duration_ms == 0
