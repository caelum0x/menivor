"""Creator Analytics API tests (BI dashboard).

Covers ``app.controllers.v1.analytics`` — the single auth-gated, strictly
owner-scoped endpoint:

* ``GET /me/analytics?days=`` — the caller's funnel / cost-over-time / credit
  burn + live balance / render-time percentiles / usage breakdowns
  (:func:`app.services.analytics.creator_analytics`), merged with their most-used
  templates/hooks (:func:`app.services.analytics.top_content`).

Asserts:

* the caller only ever sees their OWN analytics — never another user's jobs,
  cost, credits, render times or breakdowns;
* ``days`` is clamped to the sane ``1..365`` window (out-of-range -> 422; the
  window echoed back never exceeds 365);
* an unauthenticated request is a ``401``.

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient``, mirroring ``tests/reelforge/test_api_keys_api.py``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.analytics as analytics_mod
from app.models import const
from app.models.db.base import Base
from app.models.db.models import CreditLedger, Job, JobEvent, User
from app.models.exception import HttpException
from app.utils import utils

# Caller ("user A") authenticates with this key; "user B" is a foreign user
# whose data must NEVER leak into the caller's analytics.
_API_KEY = "caller-static-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}


# =========================================================================== #
# Time helpers
# =========================================================================== #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_ago(n: int) -> datetime:
    return _now() - timedelta(days=n)


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def db_factory():
    """In-memory SQLite engine + session factory with the schema created."""
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
    return Factory


def _add_job(session, user_id, state, *, params=None, script="", created_at=None):
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


def _add_event(session, job_id, stage, *, status=const.REELFORGE_STAGE_COMPLETE,
               cost_usd=0.0, duration_ms=0, created_at=None):
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


def _seed(Factory) -> dict[str, str]:
    """Seed two users. Returns ``{"a": caller_id, "b": foreign_id}``.

    User A (the caller): two in-window jobs (A1 COMPLETE + published, A2 FAILED),
    events with distinct cost/duration, a template + hook, and a personal ledger
    (grant 100, debit 30, debit 20 => balance 50, spent 50).

    User B (foreign): one expensive job whose cost/render/credits must never leak
    into A's figures.
    """
    with Factory() as s:
        a = User(email="a@example.com", api_key_hash=_KEY_HASH, credits=0)
        b = User(
            email="b@example.com",
            api_key_hash=hashlib.sha256(b"other").hexdigest(),
            credits=0,
        )
        s.add_all([a, b])
        s.flush()

        # --- User A ---
        a1 = _add_job(
            s, a.id, const.TASK_STATE_COMPLETE,
            params={
                "layout": "pip", "language": "en", "variants": 1,
                "template": "hook_pov", "video_subject": "5 AI tools",
            },
            created_at=_days_ago(3),
        )
        _add_event(s, a1.id, "compose", cost_usd=0.50, duration_ms=4000,
                   created_at=_days_ago(3))
        _add_event(s, a1.id, "upload", cost_usd=0.10, duration_ms=1000,
                   created_at=_days_ago(3))

        a2 = _add_job(
            s, a.id, const.TASK_STATE_FAILED,
            params={"layout": "split", "language": "tr", "variants": 2,
                    "video_subject": "5 AI tools"},
            created_at=_days_ago(2),
        )
        _add_event(s, a2.id, "compose", cost_usd=0.20, duration_ms=2000,
                   created_at=_days_ago(2))

        # --- User B (foreign; must never leak into A's analytics) ---
        b1 = _add_job(
            s, b.id, const.TASK_STATE_COMPLETE,
            params={"layout": "cinematic", "language": "de",
                    "template": "foreign_tmpl", "video_subject": "B secret hook"},
            created_at=_days_ago(1),
        )
        _add_event(s, b1.id, "compose", cost_usd=9.99, duration_ms=99000,
                   created_at=_days_ago(1))
        _add_event(s, b1.id, "upload", cost_usd=1.00, duration_ms=5000,
                   created_at=_days_ago(1))

        # --- Ledgers (append-only; personal pool => workspace_id NULL) ---
        s.add_all([
            CreditLedger(user_id=a.id, delta=100, reason="signup",
                         balance_after=100, created_at=_days_ago(6)),
            CreditLedger(user_id=a.id, job_id=a1.id, delta=-30, reason="job_debit",
                         balance_after=70, created_at=_days_ago(5)),
            CreditLedger(user_id=a.id, job_id=a2.id, delta=-20, reason="job_debit",
                         balance_after=50, created_at=_days_ago(2)),
            CreditLedger(user_id=b.id, delta=40, reason="signup",
                         balance_after=40, created_at=_days_ago(5)),
            CreditLedger(user_id=b.id, job_id=b1.id, delta=-45, reason="job_debit",
                         balance_after=-5, created_at=_days_ago(1)),
        ])
        ids = {"a": a.id, "b": b.id}
        s.commit()
    return ids


@pytest.fixture()
def analytics_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the analytics router + in-memory SQLite.

    Returns ``(client, Factory, ids)`` where ``ids`` maps ``"a"``/``"b"`` to the
    seeded caller / foreign user ids.
    """
    Factory = db_factory
    ids = _seed(Factory)

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(analytics_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(analytics_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory, ids


# =========================================================================== #
# Auth
# =========================================================================== #
def test_requires_auth(analytics_client):
    client, _, _ = analytics_client
    resp = client.get("/api/v1/me/analytics")
    assert resp.status_code == 401, resp.text


def test_invalid_api_key_is_401(analytics_client):
    client, _, _ = analytics_client
    resp = client.get(
        "/api/v1/me/analytics", headers={"x-api-key": "not-a-real-key"}
    )
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# Caller-scoped analytics (no cross-user leakage)
# =========================================================================== #
def test_caller_sees_only_their_own_analytics(analytics_client):
    client, _, _ = analytics_client
    resp = client.get("/api/v1/me/analytics?days=30", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    # Funnel is A's only: 2 created (A1+A2), 1 completed, 1 failed, 1 published.
    assert data["funnel"] == {
        "created": 2, "completed": 1, "failed": 1, "published": 1,
    }
    # Cost is A's in-window event cost (0.50+0.10+0.20) — never B's 10.99.
    assert data["totals"]["total_cost_usd"] == pytest.approx(0.80)
    # Credits are A's personal pool: live balance 50, in-window spend 50.
    assert data["credits"]["balance"] == 50
    assert data["credits"]["spent"] == 50
    # Render percentiles come from A's compose/upload durations [4000,1000,2000].
    assert data["render_time"]["samples"] == 3
    assert data["render_time"]["p90_ms"] == pytest.approx(4000.0)


def test_no_foreign_user_data_leaks(analytics_client):
    """None of user B's jobs, cost, credits, layouts or hooks appear for A."""
    client, _, _ = analytics_client
    resp = client.get("/api/v1/me/analytics?days=365", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.text
    data = resp.json()["data"]

    # B's expensive figures never surface in A's totals.
    assert data["totals"]["total_cost_usd"] == pytest.approx(0.80)
    assert data["credits"]["balance"] == 50  # not B's -5

    # B's distinct breakdown values / template / hook are absent everywhere.
    assert "cinematic" not in data["by_layout"]
    assert "de" not in data["by_language"]
    assert "foreign_tmpl" not in body
    assert "B secret hook" not in body

    # A's own template/hook ARE present (isolation the other direction).
    template_names = {t["name"] for t in data["top_content"]["templates"]}
    hook_lines = {h["hook"] for h in data["top_content"]["hooks"]}
    assert "hook_pov" in template_names
    assert "5 AI tools" in hook_lines


def test_foreign_user_sees_only_their_own(analytics_client):
    """User B, authenticating separately, sees only B's data (mirror check)."""
    client, Factory, ids = analytics_client
    # Give B a resolvable api key.
    b_key = "foreign-caller-key"
    with Factory() as s:
        b = s.get(User, ids["b"])
        b.api_key_hash = hashlib.sha256(b_key.encode("utf-8")).hexdigest()
        s.commit()

    resp = client.get(
        "/api/v1/me/analytics?days=30", headers={"x-api-key": b_key}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["user_id"] == ids["b"]
    assert data["funnel"] == {
        "created": 1, "completed": 1, "failed": 0, "published": 1,
    }
    assert data["totals"]["total_cost_usd"] == pytest.approx(10.99)
    assert data["credits"]["balance"] == -5
    # A's values never bleed into B.
    assert "split" not in data["by_layout"]
    assert "5 AI tools" not in resp.text


# =========================================================================== #
# days clamping (1..365)
# =========================================================================== #
def test_default_days_window(analytics_client):
    client, _, _ = analytics_client
    resp = client.get("/api/v1/me/analytics", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["days"] == 30


def test_days_out_of_range_rejected(analytics_client):
    """Query validation clamps the range: <1 or >365 is a 422."""
    client, _, _ = analytics_client
    too_small = client.get("/api/v1/me/analytics?days=0", headers=_HEADERS)
    too_large = client.get("/api/v1/me/analytics?days=100000", headers=_HEADERS)
    assert too_small.status_code == 422, too_small.text
    assert too_large.status_code == 422, too_large.text


def test_days_clamped_to_max(analytics_client):
    """A valid in-range window is echoed back and never exceeds 365."""
    client, _, _ = analytics_client
    resp = client.get("/api/v1/me/analytics?days=365", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["days"] == 365


def test_wider_window_reveals_more_but_still_scoped(analytics_client):
    """A wider window can include older own-jobs but still never foreign data."""
    client, Factory, ids = analytics_client
    # Add an OLD (60-day) job for the caller, outside a 30-day window.
    with Factory() as s:
        old = _add_job(
            s, ids["a"], const.TASK_STATE_COMPLETE,
            params={"layout": "pip", "language": "en"},
            created_at=_days_ago(60),
        )
        s.flush()
        _ = old
        s.commit()

    narrow = client.get("/api/v1/me/analytics?days=30", headers=_HEADERS).json()
    wide = client.get("/api/v1/me/analytics?days=365", headers=_HEADERS).json()
    assert narrow["data"]["funnel"]["created"] == 2
    assert wide["data"]["funnel"]["created"] == 3
    # Still no foreign cost even with the widest window.
    assert wide["data"]["totals"]["total_cost_usd"] == pytest.approx(0.80)
