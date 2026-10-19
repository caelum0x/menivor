"""Tests for data-retention policy + sweep (Compliance, Epic 5).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered:

* :func:`retention.set_policy` / :func:`get_policy` are ``workspace.settings``
  RBAC-gated (a non-member is denied);
* :func:`retention.sweep_retention` soft-purges/anonymizes ONLY the target
  workspace's aged jobs + assets; fresh rows are kept;
* the sweep is cross-workspace safe — a workspace with no policy (or a different
  tenant's rows) is never touched;
* a ``NULL`` (keep-forever) window is never swept.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import Asset, Job, User
from app.models.db.repositories import (
    AssetRepository,
    JobRepository,
    WorkspaceRepository,
)
from app.services.compliance import retention

_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
_OLD = _NOW - timedelta(days=60)
_FRESH = _NOW - timedelta(days=1)


@pytest.fixture(autouse=True)
def _fake_r2(monkeypatch):
    """No network: every R2 delete succeeds and no stage files are listed."""
    monkeypatch.setattr(retention, "_delete_objects", lambda keys: set(keys))
    monkeypatch.setattr(retention, "_list_prefix", lambda prefix: [])


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@contextmanager
def _session(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_user(session, email: str) -> str:
    user = User(email=email, credits=0)
    session.add(user)
    session.flush()
    return user.id


def _aged_job(session, user_id: str, script: str, created_at: datetime) -> str:
    job = JobRepository(session).create(
        user_id=user_id, kind="avatar_reel", params={"prompt": script}
    )
    JobRepository(session).set_script(job.id, script)
    job.created_at = created_at
    session.flush()
    return job.id


def _aged_asset(session, user_id: str, r2_key: str, created_at: datetime) -> str:
    asset = AssetRepository(session).create(
        user_id=user_id, kind="final", r2_key=r2_key
    )
    asset.created_at = created_at
    session.flush()
    return asset.id


# --------------------------------------------------------------------------- #
# policy RBAC
# --------------------------------------------------------------------------- #
def test_set_policy_requires_workspace_settings(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        outsider = _make_user(s, "outsider@example.com")
        ws = WorkspaceRepository(s).create_workspace("W", owner)

        # A non-member cannot set the policy (tenant isolation + RBAC).
        with pytest.raises(PermissionError):
            retention.set_policy(s, outsider, ws.id, jobs_retention_days=10)

        # The owner can.
        policy = retention.set_policy(
            s, owner, ws.id, jobs_retention_days=7, assets_retention_days=14
        )
        assert policy.jobs_retention_days == 7
        assert policy.assets_retention_days == 14


def test_get_policy_returns_configured_window(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        ws = WorkspaceRepository(s).create_workspace("W", owner)
        retention.set_policy(s, owner, ws.id, jobs_retention_days=30)

        got = retention.get_policy(s, owner, ws.id)
        assert got is not None
        assert got.jobs_retention_days == 30
        assert got.assets_retention_days is None


# --------------------------------------------------------------------------- #
# sweep — only the target workspace's aged rows are purged
# --------------------------------------------------------------------------- #
def test_sweep_purges_only_aged_rows(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        ws = WorkspaceRepository(s).create_workspace("W", owner)
        retention.set_policy(
            s, owner, ws.id, jobs_retention_days=30, assets_retention_days=30
        )

        old_job = _aged_job(s, owner, "old script", _OLD)
        fresh_job = _aged_job(s, owner, "fresh script", _FRESH)
        old_asset = _aged_asset(s, owner, "old.mp4", _OLD)
        fresh_asset = _aged_asset(s, owner, "fresh.mp4", _FRESH)

        summary = retention.sweep_retention(s, now=_NOW)

        oj = s.get(Job, old_job)
        fj = s.get(Job, fresh_job)
        assert oj.script == "" and oj.params == {}
        assert fj.script == "fresh script"
        assert fj.params.get("prompt") == "fresh script"

        oa = s.get(Asset, old_asset)
        fa = s.get(Asset, fresh_asset)
        assert oa.r2_key == "" and oa.meta == {}
        assert fa.r2_key == "fresh.mp4"

        assert summary["jobs_purged"] == 1
        assert summary["assets_purged"] == 1
        assert summary["workspaces"] == 1


def test_sweep_is_cross_workspace_safe(session_factory):
    with _session(session_factory) as s:
        owner_a = _make_user(s, "a@example.com")
        owner_b = _make_user(s, "b@example.com")
        ws_a = WorkspaceRepository(s).create_workspace("A", owner_a)
        WorkspaceRepository(s).create_workspace("B", owner_b)

        # Only workspace A configures a retention window.
        retention.set_policy(s, owner_a, ws_a.id, jobs_retention_days=30)

        job_a = _aged_job(s, owner_a, "a-old", _OLD)
        job_b = _aged_job(s, owner_b, "b-old", _OLD)

        retention.sweep_retention(s, now=_NOW)

        # A's aged job purged; B's (no policy, other tenant) untouched.
        assert s.get(Job, job_a).script == ""
        assert s.get(Job, job_b).script == "b-old"


def test_sweep_skips_multi_workspace_members(session_factory):
    # A user who belongs to >1 workspace must never be purged by any workspace's
    # window (Job/Asset carry no workspace_id, so their rows can't be attributed
    # to a single tenant). Otherwise one tenant's 7-day window would destroy work
    # another tenant's window says to keep.
    with _session(session_factory) as s:
        owner_a = _make_user(s, "a@example.com")
        owner_b = _make_user(s, "b@example.com")
        freelancer = _make_user(s, "free@example.com")

        ws_a = WorkspaceRepository(s).create_workspace("A", owner_a)
        ws_b = WorkspaceRepository(s).create_workspace("B", owner_b)
        # Freelancer is a member of BOTH client workspaces.
        WorkspaceRepository(s).add_member(ws_a.id, freelancer, "member")
        WorkspaceRepository(s).add_member(ws_b.id, freelancer, "member")

        # A: aggressive 7-day window; B keeps for a year.
        retention.set_policy(s, owner_a, ws_a.id, jobs_retention_days=7)
        retention.set_policy(s, owner_b, ws_b.id, jobs_retention_days=365)

        free_job = _aged_job(s, freelancer, "freelancer work", _OLD)
        owner_a_job = _aged_job(s, owner_a, "owner-a work", _OLD)

        retention.sweep_retention(s, now=_NOW)

        # Freelancer's personal job is preserved (belongs to two workspaces).
        assert s.get(Job, free_job).script == "freelancer work"
        # The sole-member owner's aged job is still purged under A's window.
        assert s.get(Job, owner_a_job).script == ""


def test_sweep_keep_forever_window_is_never_swept(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "owner@example.com")
        ws = WorkspaceRepository(s).create_workspace("W", owner)
        # Both windows NULL => keep forever.
        retention.set_policy(
            s, owner, ws.id, jobs_retention_days=None, assets_retention_days=None
        )
        old_job = _aged_job(s, owner, "ancient", _OLD)

        summary = retention.sweep_retention(s, now=_NOW)

        assert s.get(Job, old_job).script == "ancient"
        assert summary["jobs_purged"] == 0
        assert summary["assets_purged"] == 0
