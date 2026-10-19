"""Unit tests for per-user creator-dashboard analytics (``app.services.insights``).

Runs entirely against an in-memory SQLite engine — no Postgres/Neon required.
Seeds two users with jobs, job_events (with ``cost_usd`` / ``duration_ms``) and
credit-ledger rows, then asserts:

* every aggregate is scoped to a single ``user_id`` (no cross-user leakage);
* sums / averages / counts are computed correctly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import const
from app.models.db.base import Base
from app.models.db.models import CreditLedger, Job, JobEvent, User
from app.services.insights import user_insights


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def session() -> Session:
    """A Session bound to a fresh in-memory SQLite DB with all tables created."""
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _add_job(
    session: Session, user_id: str, state: int
) -> Job:
    job = Job(user_id=user_id, kind="avatar_reel", state=state, params={}, stages={})
    session.add(job)
    session.flush()
    return job


def _add_event(
    session: Session,
    job_id: str,
    stage: str,
    *,
    cost_usd: float = 0.0,
    duration_ms: int = 0,
) -> JobEvent:
    event = JobEvent(
        job_id=job_id,
        stage=stage,
        status=const.REELFORGE_STAGE_COMPLETE,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
    )
    session.add(event)
    session.flush()
    return event


@pytest.fixture()
def seeded(session: Session) -> dict[str, str]:
    """Seed two users with distinct jobs/events/ledger rows.

    User A:
      * job A1 COMPLETE  -> compose event cost 0.50 / 4000ms, tts event cost 0.10
      * job A2 FAILED    -> compose event cost 0.20 / 2000ms
      * ledger: grant 100, debit 30  (balance 70, spent 30)

    User B (must never leak into A's figures):
      * job B1 COMPLETE  -> compose event cost 9.99 / 99000ms
      * ledger: grant 50, debit 45   (balance 5, spent 45)
    """
    a = User(email="a@example.com", display_name="A", credits=0)
    b = User(email="b@example.com", display_name="B", credits=0)
    session.add_all([a, b])
    session.flush()

    # --- User A jobs/events ---
    a1 = _add_job(session, a.id, const.TASK_STATE_COMPLETE)
    _add_event(session, a1.id, "compose", cost_usd=0.50, duration_ms=4000)
    _add_event(session, a1.id, "tts", cost_usd=0.10, duration_ms=500)
    a2 = _add_job(session, a.id, const.TASK_STATE_FAILED)
    _add_event(session, a2.id, "compose", cost_usd=0.20, duration_ms=2000)

    # --- User B jobs/events ---
    b1 = _add_job(session, b.id, const.TASK_STATE_COMPLETE)
    _add_event(session, b1.id, "compose", cost_usd=9.99, duration_ms=99000)

    # --- Ledgers (append-only) ---
    session.add_all(
        [
            CreditLedger(user_id=a.id, delta=100, reason="signup", balance_after=100),
            CreditLedger(
                user_id=a.id, job_id=a1.id, delta=-30, reason="job_debit",
                balance_after=70,
            ),
            CreditLedger(user_id=b.id, delta=50, reason="signup", balance_after=50),
            CreditLedger(
                user_id=b.id, job_id=b1.id, delta=-45, reason="job_debit",
                balance_after=5,
            ),
        ]
    )
    session.flush()
    return {"a": a.id, "b": b.id}


# --------------------------------------------------------------------------- #
# Per-user correctness
# --------------------------------------------------------------------------- #
def test_insights_user_a(session: Session, seeded: dict[str, str]):
    result = user_insights(session, seeded["a"])

    assert result["user_id"] == seeded["a"]
    assert result["jobs_total"] == 2
    assert result["jobs_by_state"] == {"complete": 1, "failed": 1}
    assert result["videos_generated"] == 1
    assert result["credits_balance"] == 70
    assert result["credits_spent"] == 30
    # SUM over all of A's events: 0.50 + 0.10 + 0.20
    assert result["total_cost_usd"] == pytest.approx(0.80)
    # AVG of A's compose durations only: (4000 + 2000) / 2
    assert result["avg_render_ms"] == pytest.approx(3000.0)


def test_insights_user_b(session: Session, seeded: dict[str, str]):
    result = user_insights(session, seeded["b"])

    assert result["jobs_total"] == 1
    assert result["jobs_by_state"] == {"complete": 1}
    assert result["videos_generated"] == 1
    assert result["credits_balance"] == 5
    assert result["credits_spent"] == 45
    assert result["total_cost_usd"] == pytest.approx(9.99)
    assert result["avg_render_ms"] == pytest.approx(99000.0)


# --------------------------------------------------------------------------- #
# Scoping — no cross-user leakage
# --------------------------------------------------------------------------- #
def test_no_cross_user_leakage(session: Session, seeded: dict[str, str]):
    """A's figures must exclude every one of B's jobs/events/ledger rows."""
    a = user_insights(session, seeded["a"])
    b = user_insights(session, seeded["b"])

    # A never sees B's expensive compose event or vice-versa.
    assert a["total_cost_usd"] == pytest.approx(0.80)
    assert a["avg_render_ms"] == pytest.approx(3000.0)
    assert b["total_cost_usd"] == pytest.approx(9.99)

    # Combined jobs = 3, but neither user reports the other's counts.
    assert a["jobs_total"] + b["jobs_total"] == 3
    assert a["credits_balance"] != b["credits_balance"]
    assert a["credits_spent"] == 30 and b["credits_spent"] == 45


# --------------------------------------------------------------------------- #
# Empty / edge cases
# --------------------------------------------------------------------------- #
def test_unknown_user_returns_zeros(session: Session, seeded: dict[str, str]):
    result = user_insights(session, "nobody")

    assert result["jobs_total"] == 0
    assert result["jobs_by_state"] == {}
    assert result["videos_generated"] == 0
    assert result["credits_balance"] == 0
    assert result["credits_spent"] == 0
    assert result["total_cost_usd"] == 0.0
    assert result["avg_render_ms"] == 0.0


def test_blank_user_id_raises(session: Session):
    with pytest.raises(ValueError, match="user_id is required"):
        user_insights(session, "   ")
