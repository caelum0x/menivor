"""Unit tests for per-user BI analytics (``app.services.analytics``).

Runs entirely against an in-memory SQLite engine — no Postgres/Neon required.
Seeds TWO users with jobs, job_events (``cost_usd`` / ``duration_ms``) and
credit-ledger rows, then asserts:

* every aggregate is strictly scoped to one ``user_id`` (user A's analytics
  never include any of user B's rows);
* the funnel, cost-by-day, credit burn, render-time percentiles and usage
  breakdowns are computed correctly;
* ``top_content`` ranks templates/hooks per-user and tolerates missing fields.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import const
from app.models.db.base import Base
from app.models.db.models import CreditLedger, Job, JobEvent, User
from app.services.analytics import creator_analytics, top_content


# --------------------------------------------------------------------------- #
# Fixtures / seed helpers
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_ago(n: int) -> datetime:
    return _now() - timedelta(days=n)


def _add_job(
    session: Session,
    user_id: str,
    state: int,
    *,
    params: dict | None = None,
    script: str = "",
    created_at: datetime | None = None,
) -> Job:
    job = Job(
        user_id=user_id,
        kind="avatar_reel",
        state=state,
        params=params or {},
        stages={},
        script=script,
        created_at=created_at or _days_ago(1),
    )
    session.add(job)
    session.flush()
    return job


def _add_event(
    session: Session,
    job_id: str,
    stage: str,
    *,
    status: str = const.REELFORGE_STAGE_COMPLETE,
    cost_usd: float = 0.0,
    duration_ms: int = 0,
    created_at: datetime | None = None,
) -> JobEvent:
    event = JobEvent(
        job_id=job_id,
        stage=stage,
        status=status,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        created_at=created_at or _days_ago(1),
    )
    session.add(event)
    session.flush()
    return event


@pytest.fixture()
def seeded(session: Session) -> dict[str, str]:
    """Seed two users with distinct jobs/events/ledger rows.

    User A (within the 30-day window unless noted):
      * A1 COMPLETE  {layout:pip,   language:en, variants:1, template:hook_pov,
                      video_subject:"5 AI tools"}
          - compose complete  cost 0.50 / 4000ms
          - upload  complete  cost 0.10 / 1000ms  (=> published)
          - tts     complete  cost 0.05 /  500ms  (NOT a render stage)
      * A2 FAILED    {layout:split, language:tr, variants:2, video_subject:"5 AI tools"}
          - compose complete  cost 0.20 / 2000ms
          - compose running   cost 0.00 / 9999ms  (running => excluded)
      * A3 COMPLETE created 60 days ago (OUTSIDE the 30-day window; ignored)
      * ledger (personal): grant 100, debit 30 (5d ago), debit 20 (2d ago)
                           => balance 50, spent 50

    User B (must never leak into A's figures):
      * B1 COMPLETE {layout:pip, language:en} - compose complete 9.99 / 99000ms,
        upload complete 1.00 / 5000ms
      * ledger: grant 40, debit 45 => balance -5, spent 45
    """
    a = User(email="a@example.com", display_name="A", credits=0)
    b = User(email="b@example.com", display_name="B", credits=0)
    session.add_all([a, b])
    session.flush()

    # --- User A ---
    a1 = _add_job(
        session, a.id, const.TASK_STATE_COMPLETE,
        params={
            "layout": "pip", "language": "en", "variants": 1,
            "template": "hook_pov", "video_subject": "5 AI tools",
        },
        created_at=_days_ago(3),
    )
    _add_event(session, a1.id, "compose", cost_usd=0.50, duration_ms=4000,
               created_at=_days_ago(3))
    _add_event(session, a1.id, "upload", cost_usd=0.10, duration_ms=1000,
               created_at=_days_ago(3))
    _add_event(session, a1.id, "tts", cost_usd=0.05, duration_ms=500,
               created_at=_days_ago(3))

    a2 = _add_job(
        session, a.id, const.TASK_STATE_FAILED,
        params={
            "layout": "split", "language": "tr", "variants": 2,
            "video_subject": "5 AI tools",
        },
        created_at=_days_ago(2),
    )
    _add_event(session, a2.id, "compose", cost_usd=0.20, duration_ms=2000,
               created_at=_days_ago(2))
    _add_event(session, a2.id, "compose", status=const.REELFORGE_STAGE_RUNNING,
               cost_usd=0.0, duration_ms=9999, created_at=_days_ago(2))

    # Old job well outside the 30-day window — must be ignored by creator_analytics.
    _add_job(
        session, a.id, const.TASK_STATE_COMPLETE,
        params={"layout": "hook_intro", "language": "en"},
        created_at=_days_ago(60),
    )

    # --- User B ---
    b1 = _add_job(
        session, b.id, const.TASK_STATE_COMPLETE,
        params={"layout": "pip", "language": "en", "template": "hook_pov"},
        created_at=_days_ago(1),
    )
    _add_event(session, b1.id, "compose", cost_usd=9.99, duration_ms=99000,
               created_at=_days_ago(1))
    _add_event(session, b1.id, "upload", cost_usd=1.00, duration_ms=5000,
               created_at=_days_ago(1))

    # --- Ledgers (append-only; personal pool => workspace_id NULL) ---
    session.add_all([
        CreditLedger(user_id=a.id, delta=100, reason="signup", balance_after=100,
                     created_at=_days_ago(6)),
        CreditLedger(user_id=a.id, job_id=a1.id, delta=-30, reason="job_debit",
                     balance_after=70, created_at=_days_ago(5)),
        CreditLedger(user_id=a.id, job_id=a2.id, delta=-20, reason="job_debit",
                     balance_after=50, created_at=_days_ago(2)),
        CreditLedger(user_id=b.id, delta=40, reason="signup", balance_after=40,
                     created_at=_days_ago(5)),
        CreditLedger(user_id=b.id, job_id=b1.id, delta=-45, reason="job_debit",
                     balance_after=-5, created_at=_days_ago(1)),
    ])
    session.flush()
    return {"a": a.id, "b": b.id}


# --------------------------------------------------------------------------- #
# Funnel + totals
# --------------------------------------------------------------------------- #
def test_funnel_user_a(session: Session, seeded: dict[str, str]):
    result = creator_analytics(session, seeded["a"], days=30)

    # A3 (60d ago) is outside the window => created counts only A1 + A2.
    assert result["funnel"] == {
        "created": 2, "completed": 1, "failed": 1, "published": 1,
    }
    assert result["totals"]["jobs_total"] == 2
    assert result["totals"]["videos_generated"] == 1
    # SUM of A's in-window event costs: 0.50+0.10+0.05 + 0.20 (running=0.0)
    assert result["totals"]["total_cost_usd"] == pytest.approx(0.85)


def test_old_job_excluded_by_window(session: Session, seeded: dict[str, str]):
    """The 60-day-old job appears with a wide window but not a 30-day one."""
    narrow = creator_analytics(session, seeded["a"], days=30)
    wide = creator_analytics(session, seeded["a"], days=365)
    assert narrow["funnel"]["created"] == 2
    assert wide["funnel"]["created"] == 3


# --------------------------------------------------------------------------- #
# Cost over time + render-time percentiles
# --------------------------------------------------------------------------- #
def test_cost_by_day_and_render_time(session: Session, seeded: dict[str, str]):
    result = creator_analytics(session, seeded["a"], days=30)

    # Two distinct event days for A (3d ago: 0.65, 2d ago: 0.20).
    cost = {row["date"]: row["cost_usd"] for row in result["cost_by_day"]}
    assert sum(cost.values()) == pytest.approx(0.85)
    assert len(cost) == 2

    # Render stages = compose/upload with COMPLETE status only:
    # durations [4000 (compose), 1000 (upload), 2000 (compose)] — tts + running excluded.
    rt = result["render_time"]
    assert rt["samples"] == 3
    assert rt["avg_ms"] == pytest.approx((4000 + 1000 + 2000) / 3)
    # sorted [1000, 2000, 4000]: nearest-rank p50 -> 2000, p90 -> 4000.
    assert rt["p50_ms"] == pytest.approx(2000.0)
    assert rt["p90_ms"] == pytest.approx(4000.0)


# --------------------------------------------------------------------------- #
# Credits (burn + live balance)
# --------------------------------------------------------------------------- #
def test_credits_user_a(session: Session, seeded: dict[str, str]):
    credits = creator_analytics(session, seeded["a"], days=30)["credits"]

    assert credits["balance"] == 50           # latest personal balance_after
    assert credits["spent"] == 50             # 30 + 20 debits in-window
    burn = {row["date"]: row["spent"] for row in credits["burn_by_day"]}
    assert sum(burn.values()) == 50
    assert len(burn) == 2                     # two debit days


# --------------------------------------------------------------------------- #
# Usage breakdowns
# --------------------------------------------------------------------------- #
def test_breakdowns_user_a(session: Session, seeded: dict[str, str]):
    result = creator_analytics(session, seeded["a"], days=30)

    assert result["by_layout"] == {"pip": 1, "split": 1}
    assert result["by_language"] == {"en": 1, "tr": 1}
    assert result["by_variants"] == {"1": 1, "2": 1}


# --------------------------------------------------------------------------- #
# Strict per-user isolation
# --------------------------------------------------------------------------- #
def test_no_cross_user_leakage(session: Session, seeded: dict[str, str]):
    a = creator_analytics(session, seeded["a"], days=30)
    b = creator_analytics(session, seeded["b"], days=30)

    # A never sees B's expensive 9.99 compose or 99000ms render, and vice versa.
    assert a["totals"]["total_cost_usd"] == pytest.approx(0.85)
    assert b["totals"]["total_cost_usd"] == pytest.approx(10.99)
    assert a["render_time"]["p90_ms"] == pytest.approx(4000.0)
    assert b["render_time"]["samples"] == 2      # compose + upload only

    # Credit balances/spends are per-user and distinct.
    assert a["credits"]["balance"] == 50 and b["credits"]["balance"] == -5
    assert a["credits"]["spent"] == 50 and b["credits"]["spent"] == 45

    # Funnels do not bleed: B has exactly one created/completed/published job.
    assert b["funnel"] == {
        "created": 1, "completed": 1, "failed": 0, "published": 1,
    }
    # B's breakdown never contains A's 'split'/'tr' values.
    assert "split" not in b["by_layout"]
    assert "tr" not in b["by_language"]


# --------------------------------------------------------------------------- #
# top_content
# --------------------------------------------------------------------------- #
def test_top_content_user_a(session: Session, seeded: dict[str, str]):
    result = top_content(session, seeded["a"], limit=10)

    # template 'hook_pov' appears once (A1); A2/A3 carry no template hint.
    assert {"name": "hook_pov", "count": 1} in result["templates"]
    # 'video_subject' hook '5 AI tools' shared by A1 + A2 => count 2.
    assert result["hooks"][0] == {"hook": "5 AI tools", "count": 2}


def test_top_content_isolated_and_missing_fields_tolerated(
    session: Session, seeded: dict[str, str]
):
    a = top_content(session, seeded["a"])
    b = top_content(session, seeded["b"])

    # B's single job has a template but no video_subject/script => no hooks.
    assert b["templates"] == [{"name": "hook_pov", "count": 1}]
    assert b["hooks"] == []
    # A's '5 AI tools' hook never appears for B.
    assert all(h["hook"] != "5 AI tools" for h in b["hooks"])
    # A's own hooks are present (isolation the other direction).
    assert any(h["hook"] == "5 AI tools" for h in a["hooks"])


def test_top_content_script_fallback_hook(session: Session):
    """When ``video_subject`` is absent the first script line is the hook."""
    u = User(email="c@example.com", display_name="C", credits=0)
    session.add(u)
    session.flush()
    _add_job(
        session, u.id, const.TASK_STATE_COMPLETE,
        params={"layout": "pip"},
        script="Ever wondered how?\nSecond line.",
    )
    session.flush()

    result = top_content(session, u.id)
    assert result["hooks"] == [{"hook": "Ever wondered how?", "count": 1}]
    assert result["templates"] == []


# --------------------------------------------------------------------------- #
# Empty / edge cases
# --------------------------------------------------------------------------- #
def test_unknown_user_returns_empty(session: Session, seeded: dict[str, str]):
    result = creator_analytics(session, "nobody", days=30)

    assert result["funnel"] == {
        "created": 0, "completed": 0, "failed": 0, "published": 0,
    }
    assert result["cost_by_day"] == []
    assert result["credits"] == {"balance": 0, "spent": 0, "burn_by_day": []}
    assert result["render_time"] == {
        "p50_ms": 0.0, "p90_ms": 0.0, "avg_ms": 0.0, "samples": 0,
    }
    assert result["by_layout"] == {}
    assert result["totals"]["total_cost_usd"] == 0.0
    assert top_content(session, "nobody") == {"templates": [], "hooks": []}


def test_invalid_days_falls_back_to_default(session: Session, seeded: dict[str, str]):
    result = creator_analytics(session, seeded["a"], days=0)
    assert result["days"] == 30


def test_blank_user_id_raises(session: Session):
    with pytest.raises(ValueError, match="user_id is required"):
        creator_analytics(session, "   ")
    with pytest.raises(ValueError, match="user_id is required"):
        top_content(session, "")
