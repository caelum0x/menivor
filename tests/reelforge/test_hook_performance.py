"""Hook Performance Loop — service + repository unit tests.

Runs entirely against an in-memory SQLite engine (no Postgres/Neon required),
mirroring ``test_insights.py`` / ``test_marketplace.py``. Anchors the hard
requirements of the feature:

* **Idempotent-ish upsert** — one performance row per job (re-logging updates the
  row, never a duplicate).
* **Strictly per-user job ownership** — a creator can only log metrics for THEIR
  OWN job; logging another user's job raises ``PermissionError`` and writes
  nothing.
* **Deterministic, divide-by-zero-guarded win score** — a 0-view hook yields a
  finite score (never ``NaN``/``Inf``); the math is a pure function of the
  aggregated metrics.
* **Ranking + clamp** — hooks/templates are ranked by win score (stable tie-break)
  and the ``limit`` is clamped.
"""

from __future__ import annotations

import math

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import Job, JobPerformance, User
from app.models.db.repositories import JobPerformanceRepository
from app.services import hook_performance as svc


# =========================================================================== #
# Fixtures / helpers
# =========================================================================== #
@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    with Factory() as s:
        yield s


def _user(session: Session, email: str) -> str:
    u = User(email=email, credits=0)
    session.add(u)
    session.flush()
    return u.id


def _job(
    session: Session,
    user_id: str,
    *,
    hook: str | None = None,
    template: str | None = None,
) -> Job:
    params: dict = {}
    if hook is not None:
        params["video_subject"] = hook
    if template is not None:
        params["template"] = template
    job = Job(user_id=user_id, kind="avatar_reel", state=1, params=params, stages={})
    session.add(job)
    session.flush()
    return job


# =========================================================================== #
# Idempotent upsert — one row per job
# =========================================================================== #
def test_upsert_updates_row_not_duplicate(session: Session):
    user = _user(session, "creator@example.com")
    job = _job(session, user, hook="Stop scrolling")

    first = svc.log_performance(
        session, user, job.id, {"platform": "tiktok", "views": 100, "likes": 10}
    )
    session.flush()
    # Re-logging the SAME job updates the SAME row (no duplicate).
    second = svc.log_performance(
        session, user, job.id, {"platform": "tiktok", "views": 250, "likes": 40}
    )
    session.flush()

    assert first.id == second.id
    assert session.query(JobPerformance).count() == 1
    row = session.query(JobPerformance).one()
    assert row.views == 250
    assert row.likes == 40


# =========================================================================== #
# Strictly per-user job ownership
# =========================================================================== #
def test_cannot_log_another_users_job(session: Session):
    owner = _user(session, "owner@example.com")
    stranger = _user(session, "stranger@example.com")
    job = _job(session, owner, hook="Owner hook")

    with pytest.raises(PermissionError):
        svc.log_performance(session, stranger, job.id, {"views": 999})
    session.flush()

    # Nothing was written for the stranger (or anyone).
    assert session.query(JobPerformance).count() == 0


def test_log_missing_job_raises_value_error(session: Session):
    user = _user(session, "creator@example.com")
    with pytest.raises(ValueError):
        svc.log_performance(session, user, "does-not-exist", {"views": 1})


def test_reads_are_owner_scoped(session: Session):
    owner = _user(session, "owner@example.com")
    stranger = _user(session, "stranger@example.com")
    job = _job(session, owner, hook="Owner hook")
    svc.log_performance(session, owner, job.id, {"views": 10})
    session.flush()

    repo = JobPerformanceRepository(session)
    # The owner can read their row; a stranger guessing the job id cannot.
    assert repo.get_for_job(job.id, owner) is not None
    assert repo.get_for_job(job.id, stranger) is None
    assert repo.list_for_user(stranger) == []


# =========================================================================== #
# Numeric validation / clamping
# =========================================================================== #
def test_metrics_are_clamped(session: Session):
    user = _user(session, "creator@example.com")
    job = _job(session, user, hook="Clamp me")

    row = svc.log_performance(
        session,
        user,
        job.id,
        {
            "platform": "  TikTok  ",
            "views": -5,          # negative -> floored to 0
            "likes": "not-a-num",  # garbage -> 0
            "saves": 7,
            "retention_pct": 250.0,  # > 100 -> clamped to 100
        },
    )
    session.flush()

    assert row.views == 0
    assert row.likes == 0
    assert row.saves == 7
    assert row.retention_pct == 100.0
    assert row.platform == "tiktok"  # normalized (trim + lowercase)


def test_blank_platform_normalizes_to_unknown(session: Session):
    user = _user(session, "creator@example.com")
    job = _job(session, user, hook="No platform")
    row = svc.log_performance(session, user, job.id, {"platform": "   ", "views": 1})
    session.flush()
    assert row.platform == "unknown"


# =========================================================================== #
# Win-score math — determinism + divide-by-zero guard
# =========================================================================== #
def test_win_score_is_deterministic_and_documented(session: Session):
    user = _user(session, "creator@example.com")
    job = _job(session, user, hook="Deterministic")
    # views=100, engagements = 10+5+3+2 = 20 -> engagement_rate = 0.20
    # retention = 50% -> retention_frac = 0.50
    # win_score = 100 * (0.6*0.20 + 0.4*0.50) = 100 * (0.12 + 0.20) = 32.0
    svc.log_performance(
        session,
        user,
        job.id,
        {
            "views": 100,
            "likes": 10,
            "comments": 5,
            "shares": 3,
            "saves": 2,
            "retention_pct": 50.0,
        },
    )
    session.flush()

    ranked = svc.winning_hooks(session, user)
    assert len(ranked) == 1
    assert ranked[0]["hook"] == "Deterministic"
    assert ranked[0]["win_score"] == pytest.approx(32.0)
    # Same inputs -> same output (pure function).
    assert svc.winning_hooks(session, user) == ranked


def test_zero_view_hook_is_finite_not_nan(session: Session):
    user = _user(session, "creator@example.com")
    job = _job(session, user, hook="Zero views")
    # 0 views, some engagement + retention: engagement term must guard the
    # divide-by-zero (max(views,1)) rather than produce NaN/Inf.
    svc.log_performance(
        session,
        user,
        job.id,
        {"views": 0, "likes": 5, "retention_pct": 80.0},
    )
    session.flush()

    ranked = svc.winning_hooks(session, user)
    score = ranked[0]["win_score"]
    assert math.isfinite(score)
    # engagement_rate = min(5/max(0,1), 1) = 1.0 (capped); retention_frac = 0.8
    # win_score = 100 * (0.6*1.0 + 0.4*0.8) = 100 * (0.6 + 0.32) = 92.0
    assert score == pytest.approx(92.0)


def test_zero_everything_scores_zero(session: Session):
    user = _user(session, "creator@example.com")
    job = _job(session, user, hook="Empty")
    svc.log_performance(session, user, job.id, {"views": 0})
    session.flush()
    ranked = svc.winning_hooks(session, user)
    assert ranked[0]["win_score"] == pytest.approx(0.0)


# =========================================================================== #
# Ranking + aggregation across reels
# =========================================================================== #
def test_winning_hooks_ranked_desc(session: Session):
    user = _user(session, "creator@example.com")

    # Winner hook: high engagement + retention.
    j_win = _job(session, user, hook="Winner")
    svc.log_performance(
        session, user, j_win.id,
        {"views": 100, "likes": 60, "comments": 20, "retention_pct": 90.0},
    )
    # Loser hook: low engagement + retention.
    j_lose = _job(session, user, hook="Loser")
    svc.log_performance(
        session, user, j_lose.id,
        {"views": 100, "likes": 1, "retention_pct": 10.0},
    )
    session.flush()

    ranked = svc.winning_hooks(session, user)
    hooks = [r["hook"] for r in ranked]
    assert hooks == ["Winner", "Loser"]
    assert ranked[0]["win_score"] > ranked[1]["win_score"]


def test_hook_aggregates_multiple_reels(session: Session):
    user = _user(session, "creator@example.com")
    # Two jobs sharing ONE hook -> one aggregated group of 2 reels.
    for views, likes in ((100, 10), (300, 40)):
        job = _job(session, user, hook="Shared hook")
        svc.log_performance(
            session, user, job.id,
            {"views": views, "likes": likes, "retention_pct": 40.0},
        )
    session.flush()

    ranked = svc.winning_hooks(session, user)
    assert len(ranked) == 1
    row = ranked[0]
    assert row["reels"] == 2
    assert row["views"] == 400
    assert row["engagements"] == 50
    # engagement_rate = 50/400 = 0.125; retention_frac = 0.40
    # win_score = 100 * (0.6*0.125 + 0.4*0.40) = 100 * (0.075 + 0.16) = 23.5
    assert row["win_score"] == pytest.approx(23.5)


def test_job_without_hook_contributes_nothing(session: Session):
    user = _user(session, "creator@example.com")
    job = _job(session, user)  # no video_subject, no script
    svc.log_performance(session, user, job.id, {"views": 100, "likes": 50})
    session.flush()
    assert svc.winning_hooks(session, user) == []


# =========================================================================== #
# Templates
# =========================================================================== #
def test_winning_templates_group_by_template(session: Session):
    user = _user(session, "creator@example.com")
    a = _job(session, user, hook="h1", template="talking_head")
    b = _job(session, user, hook="h2", template="talking_head")
    c = _job(session, user, hook="h3", template="screen_rec")
    svc.log_performance(session, user, a.id, {"views": 100, "likes": 50})
    svc.log_performance(session, user, b.id, {"views": 100, "likes": 50})
    svc.log_performance(session, user, c.id, {"views": 100, "likes": 1})
    session.flush()

    ranked = svc.winning_templates(session, user)
    labels = [r["template"] for r in ranked]
    assert labels == ["talking_head", "screen_rec"]
    assert ranked[0]["reels"] == 2


# =========================================================================== #
# Limit clamp
# =========================================================================== #
def test_winning_hooks_clamps_limit(session: Session):
    user = _user(session, "creator@example.com")
    for i in range(5):
        job = _job(session, user, hook=f"hook-{i}")
        svc.log_performance(session, user, job.id, {"views": 100, "likes": i})
    session.flush()

    # An absurd limit never raises and never returns more than exist.
    assert len(svc.winning_hooks(session, user, limit=10_000)) == 5
    # A tiny limit is honored (and clamped to >= 1 on garbage).
    assert len(svc.winning_hooks(session, user, limit=2)) == 2
    assert len(svc.winning_hooks(session, user, limit=0)) == 1
    assert len(svc.winning_hooks(session, user, limit=-9)) == 1


def test_list_for_user_clamps_limit(session: Session):
    user = _user(session, "creator@example.com")
    for i in range(3):
        job = _job(session, user, hook=f"hook-{i}")
        svc.log_performance(session, user, job.id, {"views": i})
    session.flush()

    repo = JobPerformanceRepository(session)
    assert len(repo.list_for_user(user, limit=10_000)) == 3
    assert len(repo.list_for_user(user, limit=1)) == 1


def test_ranking_requires_user_id(session: Session):
    with pytest.raises(ValueError):
        svc.winning_hooks(session, "")
