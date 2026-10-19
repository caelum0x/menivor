"""MG1: delete means delete (ACCOUNT-LIFECYCLE section 3).

In-memory SQLite plus fakes for R2, Dodo/Creem, Clerk, Celery and mail.

* Erasing a user with a live Dodo subscription cancels it at Dodo.
* Every job, asset and voice-sample object is deleted, including stage files
  under ``jobs/<id>/`` whose keys the retention sweep had already blanked;
  another user's objects are untouched.
* The Clerk user is deleted, open renders are stopped, the balance is recorded
  as ``forfeited_on_delete`` and one confirmation email goes to the old address.
* The run is idempotent, and a failed step is retried by the worker task.
* The retention sweep deletes objects before blanking keys and keeps a key
  whose object could not be deleted.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.db.base as db_base
from app.models.db.base import Base
from app.models.db.creator_subscription import CreatorSubscription
from app.models.db.models import Asset, AuditLog, CreditLedger, Job, User, UserVoice, Workspace, WorkspaceMember
from app.models.db.repositories import CreditRepository, JobRepository, WorkspaceRepository
from app.services.compliance import erasure, erasure_followups, retention
from app.workers import tasks_erasure


class FakeWorld:
    def __init__(self) -> None:
        self.objects: set[str] = set()
        self.cancelled: list[tuple[str, str]] = []
        self.clerk_deleted: list[str] = []
        self.revoked: list[str] = []
        self.mail: list[tuple[str, str]] = []
        self.fail_delete = False

    def delete(self, key: str) -> bool:
        if self.fail_delete:
            raise RuntimeError("r2 down")
        self.objects.discard(key)
        return True

    def listing(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def deps(self) -> erasure_followups.Deps:
        return erasure_followups.Deps(
            r2_delete=self.delete,
            r2_list=self.listing,
            cancel_plan=lambda p, r: self.cancelled.append((p, r)),
            cancel_team=lambda p, r: self.cancelled.append((f"team:{p}", r)),
            clerk_configured=lambda: True,
            clerk_lookup=lambda email: ["user_clerk_1"] if email == "gone@example.com" else [],
            clerk_delete=self.clerk_deleted.append,
            revoke=self.revoked.append,
            send_mail=lambda to, subject, text: self.mail.append((to, subject)) or True,
        )


@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(erasure_followups, "_redis", lambda: None)
    return Factory


def _seed(Factory, world: FakeWorld) -> tuple[str, str, dict[str, str]]:
    with Factory() as s:
        user = User(email="gone@example.com", display_name="Gone", api_key_hash="h1")
        other = User(email="stays@example.com", display_name="Stays", api_key_hash="h2")
        s.add_all([user, other])
        s.flush()
        uid, oid = user.id, other.id
        jobs = JobRepository(s)
        done = jobs.create(user_id=uid, kind="avatar_reel", params={})
        done.result_key, done.poster_key = f"jobs/{done.id}/final.mp4", f"jobs/{done.id}/poster.jpg"
        done.state = 1
        swept = jobs.create(user_id=uid, kind="avatar_reel", params={})  # keys blanked by retention
        swept.state = 1
        running = jobs.create(user_id=uid, kind="avatar_reel", params={})
        running.celery_task_id = "celery-123"
        theirs = jobs.create(user_id=oid, kind="avatar_reel", params={})
        theirs.result_key = f"jobs/{theirs.id}/final.mp4"
        s.add(Asset(job_id=done.id, user_id=uid, kind="upload", r2_key="uploads/abc.mp4"))
        s.add(UserVoice(user_id=uid, sample_key="voices/sample-1.wav", provider_voice_id="v1", consent=True))
        s.add(CreatorSubscription(user_id=uid, plan_key="creator", provider="dodo",
                                  provider_ref="sub_live", status="active"))
        CreditRepository(s).grant(uid, 7, "purchase:dodo:pay_1")
        s.commit()
        ids = {"done": done.id, "swept": swept.id, "running": running.id, "theirs": theirs.id}
    world.objects |= {
        f"jobs/{ids['done']}/final.mp4", f"jobs/{ids['done']}/poster.jpg", f"jobs/{ids['done']}/tts.wav",
        f"jobs/{ids['swept']}/final.mp4", f"jobs/{ids['swept']}/captions.ass",
        "uploads/abc.mp4", "voices/sample-1.wav", f"jobs/{ids['theirs']}/final.mp4",
    }
    return uid, oid, ids


def test_erase_cancels_billing_deletes_media_and_identity(factory):
    world = FakeWorld()
    uid, _oid, ids = _seed(factory, world)
    with factory() as s:
        erasure.erase_user(s, uid, deps=world.deps())
        s.commit()
    assert world.cancelled == [("dodo", "sub_live")]
    assert world.objects == {f"jobs/{ids['theirs']}/final.mp4"}  # nothing of theirs is left
    assert world.clerk_deleted == ["user_clerk_1"]
    assert world.revoked == ["celery-123"]
    assert world.mail == [("gone@example.com", "Your Menivor account is deleted")]
    with factory() as s:
        assert s.get(Job, ids["running"]).state == -1
        assert s.execute(select(CreatorSubscription.status)).scalar() == "canceled"
        reasons = [(r, d) for r, d in s.execute(
            select(CreditLedger.reason, CreditLedger.delta).where(CreditLedger.user_id == uid)).all()]
        assert reasons == [("purchase:dodo:pay_1", 7), ("forfeited_on_delete", -7)]
        assert erasure_followups.pending(s) == []


def test_rerun_is_idempotent(factory):
    world = FakeWorld()
    uid, _oid, _ids = _seed(factory, world)
    with factory() as s:
        erasure.erase_user(s, uid, deps=world.deps())
        s.commit()
    with factory() as s:
        erasure.erase_user(s, uid, deps=world.deps())  # a second delete request
        s.commit()
    assert tasks_erasure.retry_erasure_followups() == {"requests": 0, "failed_steps": 0}
    assert world.cancelled == [("dodo", "sub_live")]
    assert world.clerk_deleted == ["user_clerk_1"]
    with factory() as s:
        forfeits = s.execute(select(CreditLedger).where(CreditLedger.reason == "forfeited_on_delete")).all()
        assert len(forfeits) == 1


def test_failed_media_step_is_retried_by_the_worker(factory, monkeypatch):
    world = FakeWorld()
    uid, _oid, ids = _seed(factory, world)
    world.fail_delete = True
    with factory() as s:
        erasure.erase_user(s, uid, deps=world.deps())
        s.commit()
    assert f"jobs/{ids['done']}/final.mp4" in world.objects
    with factory() as s:
        assert len(erasure_followups.pending(s)) == 1
    world.fail_delete = False
    original = erasure_followups.retry_pending
    monkeypatch.setattr(erasure_followups, "retry_pending", lambda: original(deps=world.deps()))
    assert tasks_erasure.retry_erasure_followups() == {"requests": 1, "failed_steps": 0}
    assert world.objects == {f"jobs/{ids['theirs']}/final.mp4"}
    assert world.cancelled == [("dodo", "sub_live")]  # finished steps are not repeated
    with factory() as s:
        steps = s.execute(select(AuditLog.meta).where(AuditLog.action == erasure_followups.ACTION_STEP)).scalars()
        assert sorted(m["step"] for m in steps) == sorted(erasure_followups.STEPS)


def test_sole_owned_team_plan_is_cancelled_shared_team_is_not(factory):
    world = FakeWorld()
    uid, oid, _ids = _seed(factory, world)
    from app.models.db.models import Subscription

    with factory() as s:
        solo, shared = Workspace(name="Solo", owner_id=uid), Workspace(name="Shared", owner_id=uid)
        s.add_all([solo, shared])
        s.flush()
        s.add_all([WorkspaceMember(workspace_id=solo.id, user_id=uid, role="owner"),
                   WorkspaceMember(workspace_id=shared.id, user_id=uid, role="owner"),
                   WorkspaceMember(workspace_id=shared.id, user_id=oid, role="member"),
                   Subscription(workspace_id=solo.id, plan_key="starter", provider="dodo",
                                provider_ref="sub_solo", status="active"),
                   Subscription(workspace_id=shared.id, plan_key="starter", provider="dodo",
                                provider_ref="sub_shared", status="active")])
        s.commit()
    with factory() as s:
        erasure.erase_user(s, uid, deps=world.deps())
        s.commit()
    assert ("team:dodo", "sub_solo") in world.cancelled
    assert ("team:dodo", "sub_shared") not in world.cancelled


def test_anonymize_only_has_no_side_effects(factory):
    world = FakeWorld()
    uid, _oid, _ids = _seed(factory, world)
    before = set(world.objects)
    with factory() as s:
        erasure.erase_user(s, uid, followups=False, deps=world.deps())
        s.commit()
    assert world.objects == before and not world.cancelled


def test_deletion_preview_shows_balance_and_outcome(factory):
    world = FakeWorld()
    uid, _oid, _ids = _seed(factory, world)
    with factory() as s:
        preview = erasure_followups.deletion_preview(s, uid)
    assert preview["balance"] == 7 and preview["paid_credit_refundable"] == 7
    assert preview["outcome"]["grant"] == "forfeited"


def test_retention_sweep_deletes_objects_and_keeps_undeleted_keys(factory, monkeypatch):
    world = FakeWorld()
    monkeypatch.setattr(retention, "_list_prefix", world.listing)
    monkeypatch.setattr(retention, "_delete_objects",
                        lambda keys: erasure_followups.delete_objects(keys, deps=world.deps()))
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with factory() as s:
        owner = User(email="o@example.com", api_key_hash="h")
        s.add(owner)
        s.flush()
        ws = WorkspaceRepository(s).create_workspace("W", owner.id)
        job = JobRepository(s).create(user_id=owner.id, kind="avatar_reel", params={})
        job.result_key = f"jobs/{job.id}/final.mp4"
        job.created_at = now - timedelta(days=60)
        asset = Asset(job_id=job.id, user_id=owner.id, kind="upload", r2_key="uploads/old.mp4",
                      created_at=now - timedelta(days=60))
        s.add(asset)
        retention.set_policy(s, owner.id, ws.id, jobs_retention_days=30, assets_retention_days=30)
        s.commit()
        job_id, asset_id = job.id, asset.id
    world.objects |= {f"jobs/{job_id}/final.mp4", f"jobs/{job_id}/tts.wav", "uploads/old.mp4"}
    world.fail_delete = True
    with factory() as s:
        retention.sweep_retention(s, now=now)
        s.commit()
        assert s.get(Asset, asset_id).r2_key == "uploads/old.mp4"  # kept for the next sweep
        assert s.get(Job, job_id).result_key == f"jobs/{job_id}/final.mp4"
    world.fail_delete = False
    with factory() as s:
        retention.sweep_retention(s, now=now)
        s.commit()
        assert s.get(Asset, asset_id).r2_key == ""
        assert s.get(Job, job_id).result_key == ""
    assert world.objects == set()


def test_erasure_retry_is_scheduled_through_the_optional_beat_hook():
    from app.workers import tasks_erasure

    entry = tasks_erasure.BEAT_SCHEDULE["erasure-followups"]
    assert entry["task"] == "app.workers.tasks_erasure.retry_erasure_followups_task"
    assert 0 < float(entry["schedule"]) <= 3600
