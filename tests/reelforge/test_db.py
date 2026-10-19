"""Unit tests for ReelForge persistence (models + repositories).

Runs entirely against an in-memory SQLite engine — no Postgres/Neon required.
Covers ``JobRepository`` lifecycle transitions (create/get/update_stage/
set_progress/mark_failed first-failure guard/mark_complete) and the append-only
``CreditRepository`` (grant/debit/balance with correct ``balance_after``).

Per INTEGRATION_CONTRACT.md §4.2 / §4.3.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import const
from app.models.db import base as db_base
from app.models.db.base import Base
from app.models.db.models import (
    CreditLedger,
    JobEvent,
    Notification,
    SavedIdea,
    ScheduledPublish,
    User,
    UserApiKey,
    UserBrand,
    UserPreset,
    UserVoice,
    WorkspaceMember,
)
from app.models.db.media_jobs import MediaJob
from app.models.db.repositories import (
    CreditRepository,
    JobRepository,
    NotificationRepository,
    SavedIdeaRepository,
    ScheduledPublishRepository,
    UserApiKeyRepository,
    UserBrandRepository,
    UserPresetRepository,
    UserRepository,
    UserVoiceRepository,
    WorkspaceRepository,
)


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


@pytest.fixture()
def user(session: Session) -> User:
    """A persisted user to satisfy job/ledger foreign keys."""
    u = User(email="tester@example.com", display_name="Tester", credits=0)
    session.add(u)
    session.flush()
    return u


@pytest.fixture()
def jobs(session: Session) -> JobRepository:
    return JobRepository(session)


@pytest.fixture()
def credits(session: Session) -> CreditRepository:
    return CreditRepository(session)


@pytest.fixture()
def users_repo(session: Session) -> UserRepository:
    return UserRepository(session)


@pytest.fixture()
def presets(session: Session) -> UserPresetRepository:
    return UserPresetRepository(session)


@pytest.fixture()
def voices(session: Session) -> UserVoiceRepository:
    return UserVoiceRepository(session)


@pytest.fixture()
def ideas(session: Session) -> SavedIdeaRepository:
    return SavedIdeaRepository(session)


@pytest.fixture()
def notifications(session: Session) -> NotificationRepository:
    return NotificationRepository(session)


@pytest.fixture()
def schedules(session: Session) -> ScheduledPublishRepository:
    return ScheduledPublishRepository(session)


@pytest.fixture()
def brands(session: Session) -> UserBrandRepository:
    return UserBrandRepository(session)


@pytest.fixture()
def api_keys(session: Session) -> UserApiKeyRepository:
    return UserApiKeyRepository(session)


# --------------------------------------------------------------------------- #
# JobRepository — create / get
# --------------------------------------------------------------------------- #
def test_create_returns_processing_job_with_id(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={"a": 1})

    assert job.id and len(job.id) == 32
    assert job.user_id == user.id
    assert job.kind == "avatar_reel"
    assert job.state == const.TASK_STATE_PROCESSING
    assert job.progress == 0
    assert job.stages == {}
    assert job.params == {"a": 1}


def test_create_defaults_kind_when_blank(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="", params=None)
    assert job.kind == "avatar_reel"
    assert job.params == {}


def test_create_copies_params_dict(jobs: JobRepository, user: User):
    src = {"video_subject": "cats"}
    job = jobs.create(user_id=user.id, kind="avatar_reel", params=src)
    # The stored params must be a copy, not the caller's object (immutability).
    assert job.params == src
    assert job.params is not src


def test_get_returns_job_and_none_for_missing(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    assert jobs.get(job.id) is job
    assert jobs.get("does-not-exist") is None


def test_list_for_user_scoped(jobs: JobRepository, session: Session):
    u1 = User(email="a@x.com")
    u2 = User(email="b@x.com")
    session.add_all([u1, u2])
    session.flush()
    jobs.create(user_id=u1.id, kind="avatar_reel", params={})
    jobs.create(user_id=u1.id, kind="avatar_reel", params={})
    jobs.create(user_id=u2.id, kind="avatar_reel", params={})

    assert len(jobs.list_for_user(u1.id)) == 2
    assert len(jobs.list_for_user(u2.id)) == 1
    assert jobs.list_for_user("nobody") == []


# --------------------------------------------------------------------------- #
# JobRepository — Phase-10 batch grouping (batch_id / list_by_batch)
# --------------------------------------------------------------------------- #
def test_batch_id_defaults_null_for_single_job(jobs: JobRepository, user: User):
    """A single-variant job leaves ``batch_id`` NULL (belongs to no batch)."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    assert job.batch_id is None


def test_create_persists_batch_id(
    jobs: JobRepository, session: Session, user: User
):
    """An explicit ``batch_id`` is persisted and reloads from the DB."""
    job = jobs.create(
        user_id=user.id, kind="avatar_reel", params={}, batch_id="batch-abc"
    )
    assert job.batch_id == "batch-abc"
    session.expire_all()  # force a reload from the DB, not the identity map
    assert jobs.get(job.id).batch_id == "batch-abc"


def test_create_blank_batch_id_stored_as_null(jobs: JobRepository, user: User):
    """A blank ``batch_id`` is normalized to NULL (never an empty string)."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={}, batch_id="")
    assert job.batch_id is None


def test_list_by_batch_returns_all_variants_oldest_first(
    jobs: JobRepository, session: Session, user: User
):
    """All jobs sharing a batch_id are returned together, oldest (first) first."""
    from datetime import datetime, timedelta, timezone

    batch = "batch-xyz"
    a = jobs.create(user_id=user.id, kind="avatar_reel", params={}, batch_id=batch)
    b = jobs.create(user_id=user.id, kind="avatar_reel", params={}, batch_id=batch)
    c = jobs.create(user_id=user.id, kind="avatar_reel", params={}, batch_id=batch)

    # SQLite CURRENT_TIMESTAMP has 1s resolution; set explicit ordered stamps so
    # the oldest-first assertion is deterministic within the same test tick.
    base = datetime(2026, 8, 11, tzinfo=timezone.utc)
    a.created_at = base
    b.created_at = base + timedelta(seconds=1)
    c.created_at = base + timedelta(seconds=2)
    session.flush()

    listed = jobs.list_by_batch(batch, user.id)
    assert [j.id for j in listed] == [a.id, b.id, c.id]


def test_list_by_batch_is_owner_scoped(
    jobs: JobRepository, session: Session
):
    """A user can never read another user's batch by guessing its id."""
    owner = User(email="owner@example.com")
    other = User(email="other@example.com")
    session.add_all([owner, other])
    session.flush()

    batch = "shared-batch-id"
    jobs.create(user_id=owner.id, kind="avatar_reel", params={}, batch_id=batch)
    jobs.create(user_id=owner.id, kind="avatar_reel", params={}, batch_id=batch)
    # A different user reusing the same batch id string sees only their own row.
    jobs.create(user_id=other.id, kind="avatar_reel", params={}, batch_id=batch)

    assert len(jobs.list_by_batch(batch, owner.id)) == 2
    assert len(jobs.list_by_batch(batch, other.id)) == 1


def test_list_by_batch_excludes_single_jobs(jobs: JobRepository, user: User):
    """Single (NULL batch_id) jobs are never swept up by a batch lookup."""
    jobs.create(user_id=user.id, kind="avatar_reel", params={})  # NULL batch
    jobs.create(user_id=user.id, kind="avatar_reel", params={}, batch_id="b1")

    assert len(jobs.list_by_batch("b1", user.id)) == 1
    # An unknown / blank batch id never matches (blank must not match NULL rows).
    assert jobs.list_by_batch("does-not-exist", user.id) == []
    assert jobs.list_by_batch("", user.id) == []
    assert jobs.list_by_batch("   ", user.id) == []


def test_batch_id_column_is_nullable_and_indexed():
    """The model declares batch_id as a nullable, indexed String(32) column.

    Mirrors migration 36c997a74166 (nullable ADD COLUMN + ``ix_jobs_batch_id``)
    so a single-variant job can stay NULL and ``list_by_batch`` is an O(index)
    lookup. Nullable (no server_default) keeps the ADD COLUMN safe on a
    populated jobs table without Alembic autogenerate drift.
    """
    from app.models.db.models import Job

    column = Job.__table__.columns["batch_id"]
    assert column.nullable is True, "batch_id must be nullable"
    assert column.index is True, "batch_id must be indexed"
    assert column.server_default is None, (
        "nullable batch_id needs no server_default (defaults to NULL)"
    )


# --------------------------------------------------------------------------- #
# JobRepository — update_stage / set_progress
# --------------------------------------------------------------------------- #
def test_update_stage_sets_and_merges(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})

    jobs.update_stage(job.id, "script", "complete")
    jobs.update_stage(job.id, "tts", "running")

    updated = jobs.get(job.id)
    assert updated.stages == {"script": "complete", "tts": "running"}


def test_update_stage_overwrites_same_stage(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    jobs.update_stage(job.id, "tts", "running")
    jobs.update_stage(job.id, "tts", "complete")
    assert jobs.get(job.id).stages == {"tts": "complete"}


def test_update_stage_replaces_map_immutably(jobs: JobRepository, user: User):
    """The stages map must be a new dict, not the original mutated in place."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    original = job.stages
    jobs.update_stage(job.id, "script", "complete")
    assert job.stages is not original


def test_update_stage_missing_job_returns_none(jobs: JobRepository):
    assert jobs.update_stage("nope", "script", "complete") is None


def test_set_progress_clamps(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})

    jobs.set_progress(job.id, 42)
    assert jobs.get(job.id).progress == 42

    jobs.set_progress(job.id, 999)
    assert jobs.get(job.id).progress == 100

    jobs.set_progress(job.id, -5)
    assert jobs.get(job.id).progress == 0


def test_set_progress_missing_job_is_noop(jobs: JobRepository):
    # Must not raise even when the job does not exist.
    jobs.set_progress("missing", 50)


# --------------------------------------------------------------------------- #
# JobRepository — mark_failed (FIRST-FAILURE GUARD)
# --------------------------------------------------------------------------- #
def test_mark_failed_records_root_cause(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    jobs.set_progress(job.id, 30)

    failed = jobs.mark_failed(job.id, "tts", "boom")

    assert failed.state == const.TASK_STATE_FAILED
    assert failed.failed_stage == "tts"
    assert failed.error == "boom"
    assert failed.stages == {"tts": "failed"}
    # Progress reached before failure is preserved.
    assert failed.progress == 30


def test_mark_failed_first_failure_guard(jobs: JobRepository, user: User):
    """Second mark_failed must NOT overwrite the first error/stage."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})

    jobs.mark_failed(job.id, "tts", "first error")
    result = jobs.mark_failed(job.id, "compose", "second error")

    assert result.failed_stage == "tts"
    assert result.error == "first error"
    assert result.stages == {"tts": "failed"}


def test_mark_failed_defaults_blank_error(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    failed = jobs.mark_failed(job.id, "script", "   ")
    # Blank error still trips the failed state with a default message,
    # so a subsequent real error can still be recorded (guard checks .strip()).
    assert failed.state == const.TASK_STATE_FAILED
    assert failed.error == "unknown job error"


def test_mark_failed_blank_error_does_not_lock_guard(jobs: JobRepository, user: User):
    """A blank/default error should still be a real recorded root cause."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    jobs.mark_failed(job.id, "script", "")
    # Default message is non-empty, so the guard now holds.
    result = jobs.mark_failed(job.id, "tts", "real error")
    assert result.failed_stage == "script"
    assert result.error == "unknown job error"


def test_mark_failed_missing_job_returns_none(jobs: JobRepository):
    assert jobs.mark_failed("nope", "tts", "boom") is None


# --------------------------------------------------------------------------- #
# JobRepository — mark_complete
# --------------------------------------------------------------------------- #
def test_mark_complete(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    done = jobs.mark_complete(job.id, "outputs/final.mp4")

    assert done.state == const.TASK_STATE_COMPLETE
    assert done.progress == 100
    assert done.result_key == "outputs/final.mp4"


def test_mark_complete_blank_result_key(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    done = jobs.mark_complete(job.id, "")
    assert done.state == const.TASK_STATE_COMPLETE
    assert done.result_key == ""


def test_mark_complete_missing_job_returns_none(jobs: JobRepository):
    assert jobs.mark_complete("nope", "k") is None


def test_set_celery_task_id(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    updated = jobs.set_celery_task_id(job.id, "celery-123")
    assert updated.celery_task_id == "celery-123"
    assert jobs.set_celery_task_id("nope", "x") is None


# --------------------------------------------------------------------------- #
# JobRepository — Phase-6 studio columns (poster_key / preview_key / webhook_url)
# --------------------------------------------------------------------------- #
def test_new_studio_columns_default_empty(jobs: JobRepository, user: User):
    """poster_key / preview_key / webhook_url default to '' for new jobs."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    assert job.poster_key == ""
    assert job.preview_key == ""
    assert job.webhook_url == ""


def test_studio_columns_round_trip(
    jobs: JobRepository, session: Session, user: User
):
    """The new columns persist and reload correctly from the DB."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    job.poster_key = "posters/abc.jpg"
    job.preview_key = "previews/abc.mp4"
    job.webhook_url = "https://example.com/hook"
    session.flush()
    session.expire_all()  # force a reload from the DB, not the identity map

    reloaded = jobs.get(job.id)
    assert reloaded.poster_key == "posters/abc.jpg"
    assert reloaded.preview_key == "previews/abc.mp4"
    assert reloaded.webhook_url == "https://example.com/hook"


def test_set_artifacts_persists_both_keys(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    updated = jobs.set_artifacts(
        job.id, poster_key="posters/x.jpg", preview_key="previews/x.mp4"
    )
    assert updated is not None
    assert updated.poster_key == "posters/x.jpg"
    assert updated.preview_key == "previews/x.mp4"
    assert jobs.get(job.id).poster_key == "posters/x.jpg"
    assert jobs.get(job.id).preview_key == "previews/x.mp4"


def test_set_artifacts_updates_keys_independently(
    jobs: JobRepository, user: User
):
    """Passing None leaves the other key untouched (independent updates)."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    jobs.set_artifacts(job.id, poster_key="posters/x.jpg")
    assert jobs.get(job.id).poster_key == "posters/x.jpg"
    assert jobs.get(job.id).preview_key == ""

    jobs.set_artifacts(job.id, preview_key="previews/x.mp4")
    # Poster key must be preserved when only the preview key is updated.
    assert jobs.get(job.id).poster_key == "posters/x.jpg"
    assert jobs.get(job.id).preview_key == "previews/x.mp4"


def test_set_artifacts_missing_job_returns_none(jobs: JobRepository):
    assert jobs.set_artifacts("nope", poster_key="p", preview_key="v") is None


def test_set_webhook_url(jobs: JobRepository, user: User):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    updated = jobs.set_webhook_url(job.id, "https://example.com/hook")
    assert updated is not None
    assert updated.webhook_url == "https://example.com/hook"
    assert jobs.get(job.id).webhook_url == "https://example.com/hook"
    # Blank falls back to "" (never None) and missing job returns None.
    assert jobs.set_webhook_url(job.id, "").webhook_url == ""
    assert jobs.set_webhook_url("nope", "x") is None


def test_script_defaults_empty_for_new_job(jobs: JobRepository, user: User):
    """A new job's ``script`` defaults to '' (never NULL)."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    assert job.script == ""


def test_set_script_round_trip(
    jobs: JobRepository, session: Session, user: User
):
    """set_script persists the narration and reloads from the DB."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    narration = "Hook line.\nBody line.\nCall to action."
    updated = jobs.set_script(job.id, narration)
    assert updated is not None
    assert updated.script == narration

    session.expire_all()  # force a reload from the DB, not the identity map
    reloaded = jobs.get(job.id)
    assert reloaded is not None
    assert reloaded.script == narration


def test_set_script_blank_coerced_to_empty(jobs: JobRepository, user: User):
    """A blank/None script is coerced to '' (never written as NULL)."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    jobs.set_script(job.id, "some script")
    assert jobs.get(job.id).script == "some script"
    assert jobs.set_script(job.id, "").script == ""
    assert jobs.set_script(job.id, None).script == ""  # type: ignore[arg-type]


def test_set_script_missing_job_returns_none(jobs: JobRepository):
    assert jobs.set_script("nope", "x") is None


def test_script_column_is_nullable_text():
    """Model declares ``script`` as nullable Text with a '' server_default.

    Mirrors migration 555b661b1cde, which adds it nullable with
    ``server_default="''"`` so the ADD COLUMN is safe on a populated jobs table
    (existing rows backfill to '') and Alembic autogenerate reports no drift.
    """
    from app.models.db.models import Job

    column = Job.__table__.columns["script"]
    assert column.nullable is True
    assert column.server_default is not None


def test_studio_columns_present_in_table_metadata():
    """Model declares the columns as NOT NULL with a server_default (no drift).

    Mirrors migration 677d1259a269, which adds them as NOT NULL with
    ``server_default="''"`` so the ADD COLUMN is safe on a populated jobs table
    and Alembic autogenerate does not report spurious drift.
    """
    from app.models.db.models import Job

    for name in ("poster_key", "preview_key", "webhook_url"):
        column = Job.__table__.columns[name]
        assert column.nullable is False, f"{name} must be NOT NULL"
        assert column.server_default is not None, (
            f"{name} must declare server_default to match migration 677d1259a269"
        )


# --------------------------------------------------------------------------- #
# CreditRepository — grant / debit / balance
# --------------------------------------------------------------------------- #
def test_balance_zero_when_no_ledger(credits: CreditRepository, user: User):
    assert credits.balance(user.id) == 0


def test_grant_sets_balance_after(credits: CreditRepository, user: User):
    entry = credits.grant(user.id, 100, reason="signup")

    assert isinstance(entry, CreditLedger)
    assert entry.delta == 100
    assert entry.reason == "signup"
    assert entry.balance_after == 100
    assert credits.balance(user.id) == 100


def test_grant_accumulates(credits: CreditRepository, user: User):
    credits.grant(user.id, 100, reason="signup")
    second = credits.grant(user.id, 50, reason="purchase")
    assert second.balance_after == 150
    assert credits.balance(user.id) == 150


def test_grant_updates_user_credits_cache(credits: CreditRepository, user: User):
    credits.grant(user.id, 75, reason="signup")
    assert user.credits == 75


def test_debit_subtracts_and_records_negative_delta(
    credits: CreditRepository, user: User
):
    credits.grant(user.id, 100, reason="signup")
    entry = credits.debit(user.id, 30, job_id=None, reason="job_debit")

    assert entry.delta == -30
    assert entry.balance_after == 70
    assert entry.reason == "job_debit"
    assert credits.balance(user.id) == 70
    assert user.credits == 70


def test_debit_insufficient_balance_raises(credits: CreditRepository, user: User):
    credits.grant(user.id, 10, reason="signup")
    with pytest.raises(ValueError, match="insufficient credits"):
        credits.debit(user.id, 50, job_id=None, reason="job_debit")
    # Balance unchanged after the rejected debit.
    assert credits.balance(user.id) == 10


def test_debit_non_positive_raises(credits: CreditRepository, user: User):
    credits.grant(user.id, 10, reason="signup")
    with pytest.raises(ValueError, match="positive"):
        credits.debit(user.id, 0, job_id=None, reason="job_debit")
    with pytest.raises(ValueError, match="positive"):
        credits.debit(user.id, -5, job_id=None, reason="job_debit")


def test_grant_non_positive_raises(credits: CreditRepository, user: User):
    with pytest.raises(ValueError, match="positive"):
        credits.grant(user.id, 0, reason="signup")
    with pytest.raises(ValueError, match="positive"):
        credits.grant(user.id, -1, reason="signup")


def test_debit_records_job_id(
    credits: CreditRepository, jobs: JobRepository, user: User
):
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    credits.grant(user.id, 50, reason="signup")
    entry = credits.debit(user.id, 5, job_id=job.id, reason="job_debit")
    assert entry.job_id == job.id


def test_ledger_is_append_only(
    credits: CreditRepository, session: Session, user: User
):
    """Every grant/debit appends an immutable row; nothing is mutated."""
    credits.grant(user.id, 100, reason="signup")
    credits.debit(user.id, 40, job_id=None, reason="job_debit")
    credits.grant(user.id, 10, reason="refund")

    rows = (
        session.query(CreditLedger)
        .filter(CreditLedger.user_id == user.id)
        .order_by(CreditLedger.id.asc())
        .all()
    )
    assert [r.delta for r in rows] == [100, -40, 10]
    assert [r.balance_after for r in rows] == [100, 60, 70]
    assert [r.reason for r in rows] == ["signup", "job_debit", "refund"]
    # Final balance matches the newest row's balance_after.
    assert credits.balance(user.id) == 70


def test_balance_uses_newest_row(credits: CreditRepository, user: User):
    """balance() reads the latest ledger row's balance_after, not SUM recompute."""
    credits.grant(user.id, 200, reason="signup")
    credits.debit(user.id, 200, job_id=None, reason="job_debit")
    assert credits.balance(user.id) == 0


# --------------------------------------------------------------------------- #
# CreditRepository — debit lock behavior on SQLite (defect #11)
# --------------------------------------------------------------------------- #
def test_debit_lock_degrades_on_sqlite(credits: CreditRepository, user: User):
    """FOR UPDATE is unsupported on SQLite; debit must still lock+read cleanly.

    ``_locked_balance`` only tolerates SQLite's missing row-lock support and
    must not swallow other errors. Here the whole debit path runs on SQLite
    and produces a correct balance without raising.
    """
    credits.grant(user.id, 100, reason="signup")
    entry = credits.debit(user.id, 40, job_id=None, reason="job_debit")

    assert entry.balance_after == 60
    assert credits.balance(user.id) == 60
    # The locked read returns the current (pre-debit) balance without error.
    assert credits._locked_balance(user.id) == 60


def test_locked_balance_propagates_non_sqlite_lock_error(
    credits: CreditRepository, user: User, monkeypatch
):
    """A real (non-SQLite) locking failure must propagate, not be swallowed."""

    class _FakeDialect:
        name = "postgresql"

    class _FakeBind:
        dialect = _FakeDialect()

    from sqlalchemy.exc import NotSupportedError

    def _boom(*_args, **_kwargs):
        raise NotSupportedError("SELECT ... FOR UPDATE", None, None)

    monkeypatch.setattr(credits._session, "get_bind", lambda: _FakeBind())
    monkeypatch.setattr(credits._session, "execute", _boom)

    with pytest.raises(NotSupportedError):
        credits._locked_balance(user.id)


# --------------------------------------------------------------------------- #
# JobEvent — server_default drift guard (defect: cost/duration columns)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("column_name", ["cost_usd", "duration_ms"])
def test_job_event_cost_columns_declare_server_default(column_name: str):
    """The unit-economics columns must carry a model-level ``server_default``.

    Migration 8d33fcd0b532 adds ``cost_usd``/``duration_ms`` as NOT NULL with
    ``server_default='0'`` so the ADD COLUMN is safe on the populated
    append-only ``job_events`` table. The model must mirror that default,
    otherwise Alembic autogenerate (``compare_server_default=True``) reports
    permanent drift and emits a spurious DROP DEFAULT that strips the
    protective default from the live DB.
    """
    column = JobEvent.__table__.columns[column_name]

    assert column.nullable is False
    assert column.server_default is not None, (
        f"{column_name} must declare server_default to match migration "
        "8d33fcd0b532 and avoid Alembic autogenerate drift"
    )
    # Rendered SQL default must match what the migration placed in the DB ('0').
    assert str(column.server_default.arg.text) == "0"


# --------------------------------------------------------------------------- #
# base.py — lazy engine/sessionmaker init (defect #10)
# --------------------------------------------------------------------------- #
def test_get_engine_requires_database_url(monkeypatch):
    """A clear RuntimeError is raised when no database URL is configured."""
    monkeypatch.setattr(db_base, "engine", None)
    monkeypatch.setattr(db_base, "SessionLocal", None)
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.setattr(db_base, "_database_url", lambda: "")

    with pytest.raises(RuntimeError, match="No database URL configured"):
        db_base.get_engine()


def test_pool_options_bound_postgres_fanout_and_skip_sqlite():
    options = db_base._pool_options(
        "postgresql+psycopg://example",
        {"pool_size": 999, "max_overflow": 999, "pool_timeout_s": 0},
    )

    assert options["pool_pre_ping"] is True
    assert options["pool_use_lifo"] is True
    assert options["pool_size"] == 20
    assert options["max_overflow"] == 20
    assert options["pool_timeout"] == 1
    assert db_base._pool_options("sqlite://") == {}


def test_concurrent_lazy_init_publishes_atomically(monkeypatch):
    """Racing get_engine()/get_sessionmaker() never see engine set w/o SessionLocal.

    Exercises the double-checked-locking guard: many threads initialize the
    lazy singletons at once, and every observed sessionmaker is bound to the
    single shared engine (no re-entry, no None SessionLocal, no assertion).
    """
    monkeypatch.setattr(db_base, "engine", None)
    monkeypatch.setattr(db_base, "SessionLocal", None)
    monkeypatch.setattr(db_base, "_database_url", lambda: "sqlite://")

    # SQLite's pool does not accept pool_size/max_overflow (prod uses Postgres),
    # so strip them here while keeping get_engine's real lock/publish logic.
    real_create_engine = db_base.create_engine

    def _sqlite_create_engine(url, **kw):
        for pg_only in ("pool_size", "max_overflow", "pool_pre_ping"):
            kw.pop(pg_only, None)
        return real_create_engine(url, **kw)

    monkeypatch.setattr(db_base, "create_engine", _sqlite_create_engine)

    start = threading.Barrier(8)
    errors: list[BaseException] = []
    makers: list[object] = []

    def worker() -> None:
        try:
            start.wait()
            # Interleave both entry points to stress the race window.
            db_base.get_engine()
            makers.append(db_base.get_sessionmaker())
        except BaseException as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert db_base.engine is not None
    assert db_base.SessionLocal is not None
    # Exactly one engine was built and every sessionmaker is bound to it.
    assert all(m is db_base.SessionLocal for m in makers)
    assert all(m.kw["bind"] is db_base.engine for m in makers)

    # Clean up the module-level singletons we created for the test.
    db_base.engine.dispose()
    monkeypatch.setattr(db_base, "engine", None)
    monkeypatch.setattr(db_base, "SessionLocal", None)


# --------------------------------------------------------------------------- #
# User — Phase-7 growth columns (referral_code / referred_by)
# --------------------------------------------------------------------------- #
def test_new_user_referral_columns_default_null(session: Session):
    """referral_code / referred_by default to NULL so existing rows are safe."""
    u = User(email="growth@example.com")
    session.add(u)
    session.flush()
    assert u.referral_code is None
    assert u.referred_by is None


def test_referral_columns_round_trip(session: Session, user: User):
    """The growth columns persist and reload correctly from the DB."""
    user.referral_code = "ABC123"
    user.referred_by = "referrer-uid-32chars"
    session.flush()
    session.expire_all()  # force a reload from the DB, not the identity map

    reloaded = session.get(User, user.id)
    assert reloaded.referral_code == "ABC123"
    assert reloaded.referred_by == "referrer-uid-32chars"


def test_referral_code_unique_constraint(session: Session):
    """The referral_code column is UNIQUE — a duplicate code is rejected."""
    from sqlalchemy.exc import IntegrityError

    session.add(User(email="a@example.com", referral_code="DUPCODE"))
    session.flush()
    session.add(User(email="b@example.com", referral_code="DUPCODE"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_referral_code_allows_multiple_nulls(session: Session):
    """Multiple users may share a NULL referral_code (populated on demand)."""
    session.add(User(email="n1@example.com"))
    session.add(User(email="n2@example.com"))
    # Must not raise — UNIQUE permits many NULLs on both SQLite and Postgres.
    session.flush()


# --------------------------------------------------------------------------- #
# UserRepository — referral helpers
# --------------------------------------------------------------------------- #
def test_set_referral_code_persists(users_repo: UserRepository, user: User):
    updated = users_repo.set_referral_code(user.id, "MYCODE1")
    assert updated is not None
    assert updated.referral_code == "MYCODE1"
    assert users_repo.get(user.id).referral_code == "MYCODE1"


def test_set_referral_code_strips_whitespace(
    users_repo: UserRepository, user: User
):
    updated = users_repo.set_referral_code(user.id, "  PADDED  ")
    assert updated.referral_code == "PADDED"


def test_set_referral_code_missing_user_returns_none(
    users_repo: UserRepository,
):
    assert users_repo.set_referral_code("nobody", "CODE") is None


def test_set_referral_code_rejects_blank(users_repo: UserRepository, user: User):
    with pytest.raises(ValueError):
        users_repo.set_referral_code(user.id, "")
    with pytest.raises(ValueError):
        users_repo.set_referral_code(user.id, "   ")


def test_get_by_referral_code_found(users_repo: UserRepository, user: User):
    users_repo.set_referral_code(user.id, "FINDME")
    found = users_repo.get_by_referral_code("FINDME")
    assert found is not None and found.id == user.id


def test_get_by_referral_code_is_case_insensitive(
    users_repo: UserRepository, user: User
):
    users_repo.set_referral_code(user.id, "MixedCase")
    assert users_repo.get_by_referral_code("mixedcase").id == user.id
    assert users_repo.get_by_referral_code("  MIXEDCASE  ").id == user.id


def test_get_by_referral_code_unknown_and_blank(
    users_repo: UserRepository, user: User
):
    users_repo.set_referral_code(user.id, "REAL")
    assert users_repo.get_by_referral_code("does-not-exist") is None
    assert users_repo.get_by_referral_code("") is None
    assert users_repo.get_by_referral_code("   ") is None


# --------------------------------------------------------------------------- #
# UserPresetRepository — brand kits (create / list / get / delete + ownership)
# --------------------------------------------------------------------------- #
def _brand_kit() -> dict:
    return {
        "avatar_id": "av-1",
        "voice_name": "elevenlabs:xyz",
        "layout": "pip",
        "caption_style": "karaoke_yellow",
        "music_id": "upbeat",
        "language": "en",
    }


def test_preset_create_returns_row_with_id(
    presets: UserPresetRepository, user: User
):
    preset = presets.create(user.id, "My Kit", _brand_kit())
    assert preset.id and len(preset.id) == 32
    assert preset.user_id == user.id
    assert preset.name == "My Kit"
    assert preset.config == _brand_kit()


def test_preset_create_copies_config_dict(
    presets: UserPresetRepository, user: User
):
    src = _brand_kit()
    preset = presets.create(user.id, "Kit", src)
    # Stored config must be a copy, not the caller's object (immutability).
    assert preset.config == src
    assert preset.config is not src


def test_preset_create_defaults_empty_config(
    presets: UserPresetRepository, user: User
):
    preset = presets.create(user.id, "Empty", None)
    assert preset.config == {}


def test_preset_round_trip(
    presets: UserPresetRepository, session: Session, user: User
):
    preset = presets.create(user.id, "Kit", _brand_kit())
    session.expire_all()  # force reload from the DB
    reloaded = session.get(UserPreset, preset.id)
    assert reloaded.name == "Kit"
    assert reloaded.config == _brand_kit()


def test_preset_list_for_user_scoped_newest_first(
    presets: UserPresetRepository, session: Session
):
    from datetime import datetime, timedelta, timezone

    u1 = User(email="p1@example.com")
    u2 = User(email="p2@example.com")
    session.add_all([u1, u2])
    session.flush()

    a = presets.create(u1.id, "A", {})
    b = presets.create(u1.id, "B", {})
    presets.create(u2.id, "C", {})

    # SQLite CURRENT_TIMESTAMP has 1s resolution; set explicit ordered stamps so
    # the newest-first assertion is deterministic within the same test tick.
    base = datetime(2026, 8, 11, tzinfo=timezone.utc)
    a.created_at = base
    b.created_at = base + timedelta(seconds=1)
    session.flush()

    listed = presets.list_for_user(u1.id)
    assert [p.name for p in listed] == ["B", "A"]
    assert len(presets.list_for_user(u2.id)) == 1
    assert presets.list_for_user("nobody") == []


def test_preset_get_enforces_ownership(
    presets: UserPresetRepository, session: Session
):
    owner = User(email="owner@example.com")
    other = User(email="other@example.com")
    session.add_all([owner, other])
    session.flush()
    preset = presets.create(owner.id, "Kit", {})

    assert presets.get(preset.id, owner.id) is preset
    # A different user cannot read the preset by guessing its id.
    assert presets.get(preset.id, other.id) is None
    # A missing id returns None (not a crash).
    assert presets.get("does-not-exist", owner.id) is None


def test_preset_delete_enforces_ownership(
    presets: UserPresetRepository, session: Session
):
    owner = User(email="o@example.com")
    other = User(email="x@example.com")
    session.add_all([owner, other])
    session.flush()
    preset = presets.create(owner.id, "Kit", {})

    # A foreign user cannot delete it; the row survives.
    assert presets.delete(preset.id, other.id) is False
    assert presets.get(preset.id, owner.id) is not None

    # The owner deletes it successfully; a second delete is a no-op False.
    assert presets.delete(preset.id, owner.id) is True
    assert presets.get(preset.id, owner.id) is None
    assert presets.delete(preset.id, owner.id) is False


def test_preset_delete_missing_returns_false(
    presets: UserPresetRepository, user: User
):
    assert presets.delete("nope", user.id) is False


# --------------------------------------------------------------------------- #
# UserVoiceRepository — brand voice clones (create / list / get / get_owned /
# delete + ownership + consent). Phase-11 voice cloning.
# --------------------------------------------------------------------------- #
def test_voice_create_returns_row_with_id(
    voices: UserVoiceRepository, user: User
):
    voice = voices.create(
        user_id=user.id,
        name="My Brand Voice",
        provider_voice_id="el-abc123",
        sample_key="voices/sample-1.mp3",
        consent=True,
    )
    assert voice.id and len(voice.id) == 32
    assert voice.user_id == user.id
    assert voice.name == "My Brand Voice"
    assert voice.provider == "elevenlabs"
    assert voice.provider_voice_id == "el-abc123"
    assert voice.sample_key == "voices/sample-1.mp3"
    assert voice.consent is True
    assert voice.status == "ready"


def test_voice_create_defaults(voices: UserVoiceRepository, user: User):
    # Minimal create: consent defaults False, status ready, empty keys.
    voice = voices.create(user_id=user.id, name="Draft")
    assert voice.provider == "elevenlabs"
    assert voice.provider_voice_id == ""
    assert voice.sample_key == ""
    assert voice.consent is False
    assert voice.status == "ready"


def test_voice_create_processing_status(
    voices: UserVoiceRepository, user: User
):
    # A row created before the clone completes has no provider_voice_id yet.
    voice = voices.create(
        user_id=user.id, name="Cloning", status="processing"
    )
    assert voice.status == "processing"
    assert voice.provider_voice_id == ""
    assert voice.consent is False


def test_voice_consent_defaults_false_and_persists_true(
    voices: UserVoiceRepository, session: Session, user: User
):
    denied = voices.create(user_id=user.id, name="No Consent")
    granted = voices.create(user_id=user.id, name="Consented", consent=True)
    session.expire_all()  # force reload from the DB
    assert session.get(UserVoice, denied.id).consent is False
    assert session.get(UserVoice, granted.id).consent is True


def test_voice_round_trip(
    voices: UserVoiceRepository, session: Session, user: User
):
    voice = voices.create(
        user_id=user.id,
        name="Round Trip",
        provider_voice_id="el-xyz",
        sample_key="voices/rt.mp3",
        consent=True,
    )
    session.expire_all()  # force reload from the DB
    reloaded = session.get(UserVoice, voice.id)
    assert reloaded.name == "Round Trip"
    assert reloaded.provider_voice_id == "el-xyz"
    assert reloaded.sample_key == "voices/rt.mp3"
    assert reloaded.consent is True
    # Narrator selection format handled by voice.py::tts().
    assert f"elevenlabs:{reloaded.provider_voice_id}" == "elevenlabs:el-xyz"


def test_voice_list_for_user_scoped_newest_first(
    voices: UserVoiceRepository, session: Session
):
    from datetime import datetime, timedelta, timezone

    u1 = User(email="v1@example.com")
    u2 = User(email="v2@example.com")
    session.add_all([u1, u2])
    session.flush()

    a = voices.create(user_id=u1.id, name="A")
    b = voices.create(user_id=u1.id, name="B")
    voices.create(user_id=u2.id, name="C")

    # SQLite CURRENT_TIMESTAMP has 1s resolution; set explicit ordered stamps so
    # the newest-first assertion is deterministic within the same test tick.
    base = datetime(2026, 8, 11, tzinfo=timezone.utc)
    a.created_at = base
    b.created_at = base + timedelta(seconds=1)
    session.flush()

    listed = voices.list_for_user(u1.id)
    assert [v.name for v in listed] == ["B", "A"]
    assert len(voices.list_for_user(u2.id)) == 1
    assert voices.list_for_user("nobody") == []


def test_voice_get_is_unscoped(voices: UserVoiceRepository, user: User):
    voice = voices.create(user_id=user.id, name="Any")
    # get() resolves by id regardless of owner (worker narrator resolution).
    assert voices.get(voice.id) is voice
    assert voices.get("does-not-exist") is None


def test_voice_get_owned_enforces_ownership(
    voices: UserVoiceRepository, session: Session
):
    owner = User(email="owner-v@example.com")
    other = User(email="other-v@example.com")
    session.add_all([owner, other])
    session.flush()
    voice = voices.create(user_id=owner.id, name="Owned")

    assert voices.get_owned(voice.id, owner.id) is voice
    # A different user cannot read the voice by guessing its id.
    assert voices.get_owned(voice.id, other.id) is None
    # A missing id returns None (not a crash).
    assert voices.get_owned("does-not-exist", owner.id) is None


def test_voice_delete_enforces_ownership(
    voices: UserVoiceRepository, session: Session
):
    owner = User(email="od-v@example.com")
    other = User(email="xd-v@example.com")
    session.add_all([owner, other])
    session.flush()
    voice = voices.create(user_id=owner.id, name="Del")

    # A foreign user cannot delete it; the row survives.
    assert voices.delete(voice.id, other.id) is False
    assert voices.get_owned(voice.id, owner.id) is not None

    # The owner deletes it successfully; a second delete is a no-op False.
    assert voices.delete(voice.id, owner.id) is True
    assert voices.get_owned(voice.id, owner.id) is None
    assert voices.delete(voice.id, owner.id) is False


def test_voice_delete_missing_returns_false(
    voices: UserVoiceRepository, user: User
):
    assert voices.delete("nope", user.id) is False


def test_voice_columns_present_in_table_metadata():
    """UserVoice declares the indexed columns the migration/queries rely on."""
    cols = UserVoice.__table__.columns
    assert cols["user_id"].index is True
    assert cols["provider_voice_id"].index is True
    assert cols["provider"].default.arg == "elevenlabs"
    assert cols["status"].default.arg == "ready"
    assert cols["consent"].default.arg is False


# --------------------------------------------------------------------------- #
# SavedIdeaRepository — SPARK ideas (create / list / get_owned / delete + owner)
# --------------------------------------------------------------------------- #
def _spark_idea() -> dict:
    return {
        "title": "POV: your app does the boring part",
        "hook": "Stop wasting Sundays on spreadsheets",
        "angle": "relatable frustration -> relief",
        "format": "talking head with screen b-roll",
        "script_outline": ["hook", "problem", "reveal", "cta"],
        "suggested_layout": "pip",
        "suggested_caption_style": "karaoke_yellow",
        "language": "en",
        "est_duration_s": 22,
    }


def test_idea_create_returns_row_with_id(
    ideas: SavedIdeaRepository, user: User
):
    idea = ideas.create(user.id, _spark_idea())
    assert idea.id and len(idea.id) == 32
    assert idea.user_id == user.id
    # title / hook are denormalized out of the payload for cheap list rendering.
    assert idea.title == _spark_idea()["title"]
    assert idea.hook == _spark_idea()["hook"]
    assert idea.payload == _spark_idea()


def test_idea_create_copies_payload_dict(
    ideas: SavedIdeaRepository, user: User
):
    src = _spark_idea()
    idea = ideas.create(user.id, src)
    # Stored payload must be a copy, not the caller's object (immutability).
    assert idea.payload == src
    assert idea.payload is not src


def test_idea_create_defaults_blank_title_and_hook(
    ideas: SavedIdeaRepository, user: User
):
    # An idea missing title/hook stores empty strings (never None) and keeps the
    # rest of the payload whole.
    idea = ideas.create(user.id, {"angle": "curiosity", "language": "tr"})
    assert idea.title == ""
    assert idea.hook == ""
    assert idea.payload == {"angle": "curiosity", "language": "tr"}


def test_idea_create_coerces_non_string_title_and_hook(
    ideas: SavedIdeaRepository, user: User
):
    # Untrusted LLM payloads may carry non-string title/hook — they are coerced
    # to str so the String columns never receive a bad type.
    idea = ideas.create(user.id, {"title": 123, "hook": None})
    assert idea.title == "123"
    assert idea.hook == ""


def test_idea_create_truncates_oversized_title_and_hook(
    ideas: SavedIdeaRepository, session: Session, user: User
):
    # title/hook map to String(300) (VARCHAR(300) on Postgres). A caller can
    # send an unbounded, untrusted idea dict, so oversized values are truncated
    # to the column limit before the INSERT — otherwise Postgres raises
    # StringDataRightTruncation and the controller's bare except yields a 502.
    from app.models.db.repositories import SAVED_IDEA_TEXT_MAX_LEN

    long_title = "T" * 500
    long_hook = "H" * 400
    idea = ideas.create(
        user.id, {"title": long_title, "hook": long_hook, "angle": "curiosity"}
    )

    assert len(idea.title) == SAVED_IDEA_TEXT_MAX_LEN == 300
    assert idea.title == long_title[:SAVED_IDEA_TEXT_MAX_LEN]
    assert len(idea.hook) == SAVED_IDEA_TEXT_MAX_LEN
    assert idea.hook == long_hook[:SAVED_IDEA_TEXT_MAX_LEN]
    # The full, untouched idea survives in the unlimited JSON payload.
    assert idea.payload["title"] == long_title
    assert idea.payload["hook"] == long_hook

    # Truncated values round-trip through the DB without a truncation error.
    session.expire_all()
    reloaded = session.get(SavedIdea, idea.id)
    assert len(reloaded.title) == 300
    assert reloaded.payload["title"] == long_title


def test_idea_create_keeps_boundary_length_title(
    ideas: SavedIdeaRepository, user: User
):
    # A title exactly at the column limit is stored intact (no off-by-one cut).
    exact = "X" * 300
    idea = ideas.create(user.id, {"title": exact})
    assert idea.title == exact
    assert len(idea.title) == 300


def test_idea_create_empty_payload(ideas: SavedIdeaRepository, user: User):
    idea = ideas.create(user.id, None)
    assert idea.payload == {}
    assert idea.title == ""
    assert idea.hook == ""


def test_idea_round_trip(
    ideas: SavedIdeaRepository, session: Session, user: User
):
    idea = ideas.create(user.id, _spark_idea())
    session.expire_all()  # force reload from the DB
    reloaded = session.get(SavedIdea, idea.id)
    assert reloaded.title == _spark_idea()["title"]
    assert reloaded.payload == _spark_idea()


def test_idea_list_for_user_scoped_newest_first(
    ideas: SavedIdeaRepository, session: Session
):
    from datetime import datetime, timedelta, timezone

    u1 = User(email="i1@example.com")
    u2 = User(email="i2@example.com")
    session.add_all([u1, u2])
    session.flush()

    a = ideas.create(u1.id, {"title": "A"})
    b = ideas.create(u1.id, {"title": "B"})
    ideas.create(u2.id, {"title": "C"})

    # SQLite CURRENT_TIMESTAMP has 1s resolution; set explicit ordered stamps so
    # the newest-first assertion is deterministic within the same test tick.
    base = datetime(2026, 8, 11, tzinfo=timezone.utc)
    a.created_at = base
    b.created_at = base + timedelta(seconds=1)
    session.flush()

    listed = ideas.list_for_user(u1.id)
    assert [i.title for i in listed] == ["B", "A"]
    assert len(ideas.list_for_user(u2.id)) == 1
    assert ideas.list_for_user("nobody") == []


def test_idea_list_respects_limit(
    ideas: SavedIdeaRepository, user: User
):
    for n in range(5):
        ideas.create(user.id, {"title": f"idea-{n}"})
    assert len(ideas.list_for_user(user.id, limit=3)) == 3
    # A non-positive limit is clamped to at least 1 (never an empty/invalid page).
    assert len(ideas.list_for_user(user.id, limit=0)) == 1
    assert len(ideas.list_for_user(user.id)) == 5


def test_idea_get_owned_enforces_ownership(
    ideas: SavedIdeaRepository, session: Session
):
    owner = User(email="owner-i@example.com")
    other = User(email="other-i@example.com")
    session.add_all([owner, other])
    session.flush()
    idea = ideas.create(owner.id, _spark_idea())

    assert ideas.get_owned(idea.id, owner.id) is idea
    # A different user cannot read the idea by guessing its id.
    assert ideas.get_owned(idea.id, other.id) is None
    # A missing id returns None (not a crash).
    assert ideas.get_owned("does-not-exist", owner.id) is None


def test_idea_delete_enforces_ownership(
    ideas: SavedIdeaRepository, session: Session
):
    owner = User(email="od-i@example.com")
    other = User(email="xd-i@example.com")
    session.add_all([owner, other])
    session.flush()
    idea = ideas.create(owner.id, _spark_idea())

    # A foreign user cannot delete it; the row survives.
    assert ideas.delete(idea.id, other.id) is False
    assert ideas.get_owned(idea.id, owner.id) is not None

    # The owner deletes it successfully; a second delete is a no-op False.
    assert ideas.delete(idea.id, owner.id) is True
    assert ideas.get_owned(idea.id, owner.id) is None
    assert ideas.delete(idea.id, owner.id) is False


def test_idea_delete_missing_returns_false(
    ideas: SavedIdeaRepository, user: User
):
    assert ideas.delete("nope", user.id) is False


def test_idea_columns_present_in_table_metadata():
    """SavedIdea declares the indexed column the migration/queries rely on."""
    cols = SavedIdea.__table__.columns
    assert cols["user_id"].index is True
    assert cols["user_id"].nullable is False
    # payload is JSON so the idea schema can grow without a migration.
    assert isinstance(cols["payload"].type, JSON)


# --------------------------------------------------------------------------- #
# NotificationRepository — in-app notifications (bell + notification center)
# --------------------------------------------------------------------------- #
def test_notification_create_returns_unread_row_with_id(
    notifications: NotificationRepository, user: User
):
    n = notifications.create(
        user.id,
        kind="job_complete",
        title="Your reel is ready",
        body="Tap to view",
        data={"job_id": "abc", "result_key": "r2/final.mp4"},
    )

    assert n.id and len(n.id) == 32
    assert n.user_id == user.id
    assert n.kind == "job_complete"
    assert n.title == "Your reel is ready"
    assert n.body == "Tap to view"
    assert n.data == {"job_id": "abc", "result_key": "r2/final.mp4"}
    # A freshly emitted notification is always unread.
    assert n.read is False
    assert n.created_at is not None


def test_notification_create_defaults_body_and_data(
    notifications: NotificationRepository, user: User
):
    n = notifications.create(user.id, kind="low_credits", title="Low balance")
    assert n.body == ""
    assert n.data == {}
    assert n.read is False


def test_notification_create_copies_data_dict(
    notifications: NotificationRepository, user: User
):
    src = {"amount": 50}
    n = notifications.create(user.id, "referral_earned", "You earned credits", data=src)
    # The stored data must be a copy, not the caller's object (immutability).
    assert n.data == src
    assert n.data is not src


def test_notification_create_truncates_oversized_title(
    notifications: NotificationRepository, user: User
):
    # Notification content comes from untrusted, unbounded sources (job errors).
    long_title = "x" * 5000
    n = notifications.create(user.id, "job_failed", long_title, data={"error": "boom"})
    assert len(n.title) == 300


def test_notification_list_newest_first(
    notifications: NotificationRepository, session: Session, user: User
):
    from datetime import datetime, timezone

    first = notifications.create(user.id, "job_complete", "first")
    second = notifications.create(user.id, "job_complete", "second")
    # SQLite CURRENT_TIMESTAMP has 1s resolution; set explicit ordered stamps so
    # the newest-first assertion is deterministic within the same test tick.
    first.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second.created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    session.flush()

    listed = notifications.list_for_user(user.id)
    assert [n.id for n in listed] == [second.id, first.id]


def test_notification_list_unread_only_filters_read(
    notifications: NotificationRepository, user: User
):
    read_one = notifications.create(user.id, "job_complete", "read")
    notifications.create(user.id, "job_complete", "unread")
    notifications.mark_read(read_one.id, user.id)

    all_rows = notifications.list_for_user(user.id)
    unread_rows = notifications.list_for_user(user.id, unread_only=True)
    assert len(all_rows) == 2
    assert len(unread_rows) == 1
    assert unread_rows[0].title == "unread"


def test_notification_list_respects_limit(
    notifications: NotificationRepository, user: User
):
    for n in range(5):
        notifications.create(user.id, "job_complete", f"n-{n}")
    assert len(notifications.list_for_user(user.id, limit=3)) == 3
    # A non-positive limit is clamped to at least 1 (never an invalid page).
    assert len(notifications.list_for_user(user.id, limit=0)) == 1
    assert len(notifications.list_for_user(user.id)) == 5


def test_notification_list_is_owner_scoped(
    notifications: NotificationRepository, session: Session
):
    owner = User(email="owner-n@example.com")
    other = User(email="other-n@example.com")
    session.add_all([owner, other])
    session.flush()
    notifications.create(owner.id, "job_complete", "owner-only")

    assert len(notifications.list_for_user(owner.id)) == 1
    # A different user never sees the owner's notifications.
    assert notifications.list_for_user(other.id) == []


def test_notification_unread_count(
    notifications: NotificationRepository, user: User
):
    assert notifications.unread_count(user.id) == 0
    a = notifications.create(user.id, "job_complete", "a")
    notifications.create(user.id, "job_failed", "b")
    assert notifications.unread_count(user.id) == 2

    notifications.mark_read(a.id, user.id)
    assert notifications.unread_count(user.id) == 1


def test_notification_unread_count_is_owner_scoped(
    notifications: NotificationRepository, session: Session
):
    owner = User(email="owner-uc@example.com")
    other = User(email="other-uc@example.com")
    session.add_all([owner, other])
    session.flush()
    notifications.create(owner.id, "job_complete", "a")
    notifications.create(owner.id, "job_complete", "b")

    assert notifications.unread_count(owner.id) == 2
    # Another user's badge is unaffected by the owner's notifications.
    assert notifications.unread_count(other.id) == 0


def test_notification_mark_read_enforces_ownership(
    notifications: NotificationRepository, session: Session
):
    owner = User(email="owner-mr@example.com")
    other = User(email="other-mr@example.com")
    session.add_all([owner, other])
    session.flush()
    n = notifications.create(owner.id, "job_complete", "secret")

    # A foreign user cannot flip it; it stays unread.
    assert notifications.mark_read(n.id, other.id) is False
    assert notifications.unread_count(owner.id) == 1

    # The owner flips it successfully; a second call is an idempotent True.
    assert notifications.mark_read(n.id, owner.id) is True
    assert notifications.unread_count(owner.id) == 0
    assert notifications.mark_read(n.id, owner.id) is True

    # A missing id returns False (not a crash).
    assert notifications.mark_read("does-not-exist", owner.id) is False


def test_notification_mark_all_read(
    notifications: NotificationRepository, session: Session
):
    owner = User(email="owner-mar@example.com")
    other = User(email="other-mar@example.com")
    session.add_all([owner, other])
    session.flush()
    notifications.create(owner.id, "job_complete", "a")
    notifications.create(owner.id, "job_failed", "b")
    already = notifications.create(owner.id, "low_credits", "c")
    notifications.mark_read(already.id, owner.id)
    # A different user's unread row must NOT be swept up by the bulk update.
    notifications.create(other.id, "job_complete", "foreign")

    # Only the two still-unread owner rows are flipped.
    assert notifications.mark_all_read(owner.id) == 2
    assert notifications.unread_count(owner.id) == 0
    # The other user is untouched.
    assert notifications.unread_count(other.id) == 1
    # A second call is a no-op (nothing left unread).
    assert notifications.mark_all_read(owner.id) == 0


def test_notification_columns_present_in_table_metadata():
    """Notification declares the indexed columns the migration/queries rely on."""
    cols = Notification.__table__.columns
    assert cols["user_id"].index is True
    assert cols["user_id"].nullable is False
    assert cols["created_at"].index is True
    # data is JSON so the per-event payload can grow without a migration.
    assert isinstance(cols["data"].type, JSON)
    # Composite (user_id, read) index backs the hot unread queries.
    index_names = {ix.name for ix in Notification.__table__.indexes}
    assert "ix_notifications_user_id_read" in index_names


# --------------------------------------------------------------------------- #
# ScheduledPublishRepository — Scheduled Publishing (create / get_owned / list /
# cancel / claim_due / mark_published / mark_failed)
# --------------------------------------------------------------------------- #
def _sched_dt(offset_seconds: int = 0):
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_seconds)


def test_schedule_create_returns_pending_row_with_id(
    schedules: ScheduledPublishRepository, user: User
):
    row = schedules.create(
        user_id=user.id,
        job_id="job-1",
        platforms=["tiktok", "instagram"],
        scheduled_at=_sched_dt(3600),
    )
    assert row.id and len(row.id) == 32
    assert row.user_id == user.id
    assert row.job_id == "job-1"
    assert row.platforms == ["tiktok", "instagram"]
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.result == {}
    assert row.error == ""
    assert row.youtube_privacy_status == "private"


def test_schedule_create_copies_platforms_list(
    schedules: ScheduledPublishRepository, user: User
):
    src = ["tiktok"]
    row = schedules.create(
        user_id=user.id, job_id="j", platforms=src, scheduled_at=_sched_dt()
    )
    # Stored platforms must be a copy, not the caller's object (immutability).
    assert row.platforms == src
    assert row.platforms is not src


def test_schedule_create_custom_privacy(
    schedules: ScheduledPublishRepository, user: User
):
    row = schedules.create(
        user_id=user.id, job_id="j", platforms=["youtube_shorts"],
        scheduled_at=_sched_dt(), youtube_privacy_status="unlisted",
    )
    assert row.youtube_privacy_status == "unlisted"


def test_schedule_get_owned_enforces_ownership(
    schedules: ScheduledPublishRepository, session: Session
):
    owner = User(email="owner-sc@example.com")
    other = User(email="other-sc@example.com")
    session.add_all([owner, other])
    session.flush()
    row = schedules.create(
        user_id=owner.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(),
    )

    assert schedules.get_owned(row.id, owner.id) is row
    # A different user cannot read the schedule by guessing its id.
    assert schedules.get_owned(row.id, other.id) is None
    # A missing id returns None (not a crash).
    assert schedules.get_owned("does-not-exist", owner.id) is None


def test_schedule_list_for_user_scoped_and_filtered(
    schedules: ScheduledPublishRepository, session: Session
):
    u1 = User(email="s1@example.com")
    u2 = User(email="s2@example.com")
    session.add_all([u1, u2])
    session.flush()

    a = schedules.create(
        user_id=u1.id, job_id="j1", platforms=["tiktok"],
        scheduled_at=_sched_dt(20),
    )
    b = schedules.create(
        user_id=u1.id, job_id="j2", platforms=["instagram"],
        scheduled_at=_sched_dt(10),
    )
    schedules.create(
        user_id=u2.id, job_id="j3", platforms=["tiktok"],
        scheduled_at=_sched_dt(30),
    )

    listed = schedules.list_for_user(u1.id)
    # Ordered soonest-due first (b at +10 before a at +20).
    assert [r.id for r in listed] == [b.id, a.id]
    assert len(schedules.list_for_user(u2.id)) == 1
    assert schedules.list_for_user("nobody") == []
    # Status filter.
    assert len(schedules.list_for_user(u1.id, status="pending")) == 2
    assert schedules.list_for_user(u1.id, status="published") == []


def test_schedule_cancel_only_pending_and_owner_scoped(
    schedules: ScheduledPublishRepository, session: Session
):
    owner = User(email="owner-cx@example.com")
    other = User(email="other-cx@example.com")
    session.add_all([owner, other])
    session.flush()
    row = schedules.create(
        user_id=owner.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(),
    )

    # A foreign user cannot cancel it.
    assert schedules.cancel(row.id, other.id) is False
    assert schedules.get_owned(row.id, owner.id).status == "pending"

    # The owner cancels it; a second cancel is a no-op False (not pending).
    assert schedules.cancel(row.id, owner.id) is True
    assert schedules.get_owned(row.id, owner.id).status == "canceled"
    assert schedules.cancel(row.id, owner.id) is False
    # A missing id returns False (not a crash).
    assert schedules.cancel("does-not-exist", owner.id) is False


def test_schedule_cancel_not_pending_returns_false(
    schedules: ScheduledPublishRepository, user: User
):
    """A publishing/published schedule can never be canceled out from under
    the runner."""
    row = schedules.create(
        user_id=user.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(-10),
    )
    schedules.mark_published(row.id, {"success": True})
    assert schedules.cancel(row.id, user.id) is False
    assert schedules.get_owned(row.id, user.id).status == "published"


def test_schedule_cancel_detects_concurrent_claim_despite_stale_read(
    schedules: ScheduledPublishRepository, session: Session, user: User
):
    """Regression: cancel must not overwrite a row the due-runner already
    claimed, even when the ORM identity map still caches ``status='pending'``.

    Reproduces the cross-session race behind the defect: the cancel controller
    has read the row into its session identity map as ``pending`` while the
    due-runner (another committed transaction) has already flipped it to
    ``publishing``. A stale identity-map read would pass the old guard and let
    the ORM UPDATE clobber the claim to ``canceled`` (a false cancellation).
    The guarded UPDATE must instead match zero DB rows and return ``False``,
    leaving the runner's claim intact.
    """
    from sqlalchemy import update as _update

    row = schedules.create(
        user_id=user.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(-10),
    )
    # Prime the identity map with the stale 'pending' status the controller saw.
    cached = schedules.get_owned(row.id, user.id)
    assert cached.status == "pending"

    # The due-runner claims the row out-of-band. synchronize_session=False keeps
    # the identity-map object stale at 'pending', reproducing the race exactly.
    session.execute(
        _update(ScheduledPublish)
        .where(ScheduledPublish.id == row.id)
        .values(status="publishing"),
        execution_options={"synchronize_session": False},
    )
    assert cached.status == "pending"  # still stale in the session cache

    # cancel must detect the claim (rowcount 0) and refuse to overwrite it.
    assert schedules.cancel(row.id, user.id) is False

    # The DB row is still 'publishing' — not clobbered to 'canceled'.
    session.expire_all()
    assert schedules.get_owned(row.id, user.id).status == "publishing"


def test_schedule_claim_due_only_returns_due_pending_and_flips(
    schedules: ScheduledPublishRepository, user: User
):
    due = schedules.create(
        user_id=user.id, job_id="j-due", platforms=["tiktok"],
        scheduled_at=_sched_dt(-60),
    )
    future = schedules.create(
        user_id=user.id, job_id="j-future", platforms=["tiktok"],
        scheduled_at=_sched_dt(3600),
    )

    claimed = schedules.claim_due(_sched_dt(0))
    assert [r.id for r in claimed] == [due.id]
    # The claimed row is flipped to publishing; the future row stays pending.
    assert schedules.get_owned(due.id, user.id).status == "publishing"
    assert schedules.get_owned(future.id, user.id).status == "pending"


def test_schedule_claim_due_is_idempotent(
    schedules: ScheduledPublishRepository, user: User
):
    """A second claim returns nothing — a claimed row is not re-claimed."""
    schedules.create(
        user_id=user.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(-30),
    )

    first = schedules.claim_due(_sched_dt(0))
    second = schedules.claim_due(_sched_dt(0))
    assert len(first) == 1
    assert second == []


def test_schedule_claim_due_ignores_at_boundary(
    schedules: ScheduledPublishRepository, user: User
):
    """scheduled_at exactly at ``now`` is due (``<=``); a moment later is not."""
    at_now = schedules.create(
        user_id=user.id, job_id="j-now", platforms=["tiktok"],
        scheduled_at=_sched_dt(0),
    )
    just_after = schedules.create(
        user_id=user.id, job_id="j-after", platforms=["tiktok"],
        scheduled_at=_sched_dt(1),
    )
    claimed = schedules.claim_due(_sched_dt(0))
    assert [r.id for r in claimed] == [at_now.id]
    assert schedules.get_owned(just_after.id, user.id).status == "pending"


def test_schedule_claim_due_respects_limit(
    schedules: ScheduledPublishRepository, user: User
):
    for n in range(5):
        schedules.create(
            user_id=user.id, job_id=f"j-{n}", platforms=["tiktok"],
            scheduled_at=_sched_dt(-100 + n),
        )
    claimed = schedules.claim_due(_sched_dt(0), limit=3)
    assert len(claimed) == 3
    # The remaining two are still pending and claimable next tick.
    assert len(schedules.claim_due(_sched_dt(0), limit=20)) == 2


def test_schedule_mark_published_sets_result_and_clears_error(
    schedules: ScheduledPublishRepository, user: User
):
    row = schedules.create(
        user_id=user.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(-1),
    )
    updated = schedules.mark_published(row.id, {"request_id": "abc"})
    assert updated.status == "published"
    assert updated.result == {"request_id": "abc"}
    assert updated.error == ""
    # Missing id returns None.
    assert schedules.mark_published("nope", {}) is None


def test_schedule_mark_published_copies_result_dict(
    schedules: ScheduledPublishRepository, user: User
):
    row = schedules.create(
        user_id=user.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(-1),
    )
    src = {"request_id": "abc"}
    updated = schedules.mark_published(row.id, src)
    assert updated.result == src
    assert updated.result is not src


def test_schedule_mark_failed_increments_attempts(
    schedules: ScheduledPublishRepository, user: User
):
    row = schedules.create(
        user_id=user.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(-1),
    )
    updated = schedules.mark_failed(row.id, "boom")
    assert updated.status == "failed"
    assert updated.attempts == 1
    assert updated.error == "boom"

    # A second failure increments attempts again.
    again = schedules.mark_failed(row.id, "boom2")
    assert again.attempts == 2
    assert again.error == "boom2"


def test_schedule_mark_failed_defaults_blank_error(
    schedules: ScheduledPublishRepository, user: User
):
    row = schedules.create(
        user_id=user.id, job_id="j", platforms=["tiktok"],
        scheduled_at=_sched_dt(-1),
    )
    updated = schedules.mark_failed(row.id, "   ")
    assert updated.error == "unknown publish error"
    assert schedules.mark_failed("nope", "x") is None


def test_schedule_round_trip(
    schedules: ScheduledPublishRepository, session: Session, user: User
):
    row = schedules.create(
        user_id=user.id, job_id="j", platforms=["tiktok", "youtube_shorts"],
        scheduled_at=_sched_dt(120), youtube_privacy_status="unlisted",
    )
    session.expire_all()  # force reload from the DB
    reloaded = session.get(ScheduledPublish, row.id)
    assert reloaded.platforms == ["tiktok", "youtube_shorts"]
    assert reloaded.status == "pending"
    assert reloaded.youtube_privacy_status == "unlisted"


def test_schedule_columns_present_in_table_metadata():
    """ScheduledPublish declares the indexed columns the migration/queries rely on."""
    cols = ScheduledPublish.__table__.columns
    assert cols["user_id"].index is True
    assert cols["user_id"].nullable is False
    assert cols["job_id"].index is True
    assert cols["job_id"].nullable is False
    assert cols["scheduled_at"].index is True
    assert cols["status"].index is True
    # platforms / result are JSON so the payload can grow without a migration.
    assert isinstance(cols["platforms"].type, JSON)
    assert isinstance(cols["result"].type, JSON)
    # server_defaults mirror migration a03a6d3bc673 (fresh CREATE, no drift).
    assert cols["status"].server_default is not None
    assert cols["attempts"].server_default is not None
    assert cols["youtube_privacy_status"].server_default is not None


# --------------------------------------------------------------------------- #
# JobRepository — Cover / Thumbnail Generator (cover_key / set_cover)
# --------------------------------------------------------------------------- #
def test_cover_key_defaults_empty_for_new_job(jobs: JobRepository, user: User):
    """A new job's ``cover_key`` defaults to '' (never NULL)."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    assert job.cover_key == ""


def test_set_cover_round_trip(
    jobs: JobRepository, session: Session, user: User
):
    """set_cover persists the cover R2 key and reloads it from the DB."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    cover_key = "covers/abc-hook.jpg"
    updated = jobs.set_cover(job.id, cover_key)
    assert updated is not None
    assert updated.cover_key == cover_key

    session.expire_all()  # force a reload from the DB, not the identity map
    reloaded = jobs.get(job.id)
    assert reloaded is not None
    assert reloaded.cover_key == cover_key


def test_set_cover_regenerates_overwrites_key(jobs: JobRepository, user: User):
    """Regenerating with a new headline/style overwrites the stored key."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    jobs.set_cover(job.id, "covers/first.jpg")
    assert jobs.get(job.id).cover_key == "covers/first.jpg"
    jobs.set_cover(job.id, "covers/second.jpg")
    assert jobs.get(job.id).cover_key == "covers/second.jpg"


def test_set_cover_blank_coerced_to_empty(jobs: JobRepository, user: User):
    """A blank/None cover key is coerced to '' (never written as NULL)."""
    job = jobs.create(user_id=user.id, kind="avatar_reel", params={})
    jobs.set_cover(job.id, "covers/x.jpg")
    assert jobs.get(job.id).cover_key == "covers/x.jpg"
    assert jobs.set_cover(job.id, "").cover_key == ""
    assert jobs.set_cover(job.id, None).cover_key == ""  # type: ignore[arg-type]


def test_set_cover_missing_job_returns_none(jobs: JobRepository):
    assert jobs.set_cover("nope", "covers/x.jpg") is None


def test_cover_key_column_is_nullable_string():
    """Model declares ``cover_key`` as nullable String(512) with '' server_default.

    Mirrors migration 03a93b99b144, which adds it nullable with
    ``server_default="''"`` so the ADD COLUMN is safe on a populated jobs table
    (existing rows backfill to '') and Alembic autogenerate reports no drift.
    """
    from app.models.db.models import Job

    column = Job.__table__.columns["cover_key"]
    assert column.nullable is True
    assert column.server_default is not None


# --------------------------------------------------------------------------- #
# WorkspaceRepository — Team Workspaces (additive membership layer)
# --------------------------------------------------------------------------- #
def _make_user(session: Session, email: str) -> User:
    """Persist and return a user with the given (unique) email."""
    u = User(email=email, display_name=email.split("@")[0], credits=0)
    session.add(u)
    session.flush()
    return u


@pytest.fixture()
def workspaces(session: Session) -> WorkspaceRepository:
    return WorkspaceRepository(session)


@pytest.fixture()
def owner(session: Session) -> User:
    return _make_user(session, "owner@example.com")


@pytest.fixture()
def teammate(session: Session) -> User:
    return _make_user(session, "teammate@example.com")


def test_create_workspace_inserts_owner_membership(
    workspaces: WorkspaceRepository, owner: User
):
    """create_workspace persists the workspace + an owner-role member row."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)

    assert ws.id and len(ws.id) == 32
    assert ws.name == "Acme"
    assert ws.owner_id == owner.id

    membership = workspaces.get_membership(ws.id, owner.id)
    assert membership is not None
    assert membership.role == "owner"
    # The owner is the sole initial member.
    members = workspaces.list_members(ws.id)
    assert [(m.user_id, m.role) for m in members] == [(owner.id, "owner")]


def test_create_workspace_coerces_blank_name(
    workspaces: WorkspaceRepository, owner: User
):
    """A None/blank name is coerced to '' (never written as NULL)."""
    ws = workspaces.create_workspace(name=None, owner_id=owner.id)  # type: ignore[arg-type]
    assert ws.name == ""


def test_get_returns_workspace_and_none_for_missing(
    workspaces: WorkspaceRepository, owner: User
):
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    assert workspaces.get(ws.id) is not None
    assert workspaces.get("does-not-exist") is None


def test_add_member_persists_role(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """add_member inserts a membership row with the requested role."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    member = workspaces.add_member(ws.id, teammate.id, role="admin")

    assert member.id and len(member.id) == 32
    assert member.workspace_id == ws.id
    assert member.user_id == teammate.id
    assert member.role == "admin"
    assert workspaces.get_membership(ws.id, teammate.id).role == "admin"


def test_add_member_normalizes_role_casing(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """Role is normalized (trimmed + lowercased) before persistence."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    member = workspaces.add_member(ws.id, teammate.id, role="  ADMIN ")
    assert member.role == "admin"


def test_add_member_rejects_invalid_role(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """An unknown role value raises ValueError (never persisted)."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    with pytest.raises(ValueError):
        workspaces.add_member(ws.id, teammate.id, role="superadmin")
    with pytest.raises(ValueError):
        workspaces.add_member(ws.id, teammate.id, role="")


def test_add_member_duplicate_raises_value_error(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """A duplicate invite raises ValueError (pre-check on the UNIQUE constraint)."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    workspaces.add_member(ws.id, teammate.id, role="member")
    with pytest.raises(ValueError):
        workspaces.add_member(ws.id, teammate.id, role="member")
    # The owner is already a member, so re-adding must also raise.
    with pytest.raises(ValueError):
        workspaces.add_member(ws.id, owner.id, role="admin")


def test_unique_membership_constraint_enforced_at_db_level(
    workspaces: WorkspaceRepository, session: Session, owner: User, teammate: User
):
    """A raw duplicate (workspace_id, user_id) INSERT hits the UNIQUE constraint.

    Bypasses the repository pre-check to prove the DB-level guarantee: a second
    membership row for the same (workspace, user) pair must fail with an
    IntegrityError, so a user is a member at most once even under a race.
    """
    from sqlalchemy.exc import IntegrityError

    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    session.add(
        WorkspaceMember(workspace_id=ws.id, user_id=teammate.id, role="member")
    )
    session.flush()
    session.add(
        WorkspaceMember(workspace_id=ws.id, user_id=teammate.id, role="admin")
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_same_user_can_join_two_workspaces(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """The unique constraint is per-workspace: a user may join many workspaces."""
    ws1 = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    ws2 = workspaces.create_workspace(name="Beta", owner_id=owner.id)
    m1 = workspaces.add_member(ws1.id, teammate.id, role="member")
    m2 = workspaces.add_member(ws2.id, teammate.id, role="admin")
    assert m1.workspace_id == ws1.id
    assert m2.workspace_id == ws2.id


def test_list_members_oldest_first_owner_leads(
    workspaces: WorkspaceRepository, session: Session, owner: User, teammate: User
):
    """list_members returns every member of a workspace, owner (oldest) first."""
    third = _make_user(session, "third@example.com")
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    workspaces.add_member(ws.id, teammate.id, role="admin")
    workspaces.add_member(ws.id, third.id, role="member")

    members = workspaces.list_members(ws.id)
    assert [m.user_id for m in members] == [owner.id, teammate.id, third.id]


def test_get_membership_none_for_non_member(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """A non-member (and a missing workspace) yields None from get_membership."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    assert workspaces.get_membership(ws.id, teammate.id) is None
    assert workspaces.get_membership("nope", owner.id) is None


def test_set_role_updates_existing_member(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """set_role changes an existing member's role and returns the row."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    workspaces.add_member(ws.id, teammate.id, role="member")
    updated = workspaces.set_role(ws.id, teammate.id, role="admin")
    assert updated is not None
    assert updated.role == "admin"
    assert workspaces.get_membership(ws.id, teammate.id).role == "admin"


def test_set_role_missing_member_returns_none(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """set_role never creates a phantom membership for a non-member."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    assert workspaces.set_role(ws.id, teammate.id, role="admin") is None
    assert workspaces.get_membership(ws.id, teammate.id) is None


def test_set_role_rejects_invalid_role(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    workspaces.add_member(ws.id, teammate.id, role="member")
    with pytest.raises(ValueError):
        workspaces.set_role(ws.id, teammate.id, role="nope")


def test_remove_member_deletes_and_reports(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """remove_member deletes a membership and returns True; False when absent."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    workspaces.add_member(ws.id, teammate.id, role="member")

    assert workspaces.remove_member(ws.id, teammate.id) is True
    assert workspaces.get_membership(ws.id, teammate.id) is None
    # A second removal is a no-op.
    assert workspaces.remove_member(ws.id, teammate.id) is False


def test_remove_member_missing_returns_false(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    assert workspaces.remove_member(ws.id, teammate.id) is False


def test_list_for_user_scoped_to_memberships(
    workspaces: WorkspaceRepository, session: Session, owner: User, teammate: User
):
    """list_for_user returns only workspaces the user is actually a member of."""
    other = _make_user(session, "other@example.com")

    ws_owned = workspaces.create_workspace(name="Owned", owner_id=owner.id)
    ws_joined = workspaces.create_workspace(name="Joined", owner_id=other.id)
    ws_foreign = workspaces.create_workspace(name="Foreign", owner_id=other.id)
    workspaces.add_member(ws_joined.id, owner.id, role="member")

    owner_ws_ids = {w.id for w in workspaces.list_for_user(owner.id)}
    assert owner_ws_ids == {ws_owned.id, ws_joined.id}
    assert ws_foreign.id not in owner_ws_ids

    # A brand-new user with no memberships sees nothing.
    assert workspaces.list_for_user(teammate.id) == []


def test_list_for_user_after_leaving(
    workspaces: WorkspaceRepository, owner: User, teammate: User
):
    """A user who leaves a workspace no longer sees it in list_for_user."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    workspaces.add_member(ws.id, teammate.id, role="member")
    assert [w.id for w in workspaces.list_for_user(teammate.id)] == [ws.id]

    workspaces.remove_member(ws.id, teammate.id)  # teammate leaves
    assert workspaces.list_for_user(teammate.id) == []
    # The workspace itself still exists for its owner.
    assert [w.id for w in workspaces.list_for_user(owner.id)] == [ws.id]


def test_workspace_member_has_unique_constraint_declared():
    """The model declares the (workspace_id, user_id) UNIQUE constraint."""
    from sqlalchemy import UniqueConstraint

    constraints = [
        c
        for c in WorkspaceMember.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    cols = [tuple(col.name for col in c.columns) for c in constraints]
    assert ("workspace_id", "user_id") in cols


# --------------------------------------------------------------------------- #
# CreditRepository — workspace shared credit pool
# --------------------------------------------------------------------------- #
def test_workspace_balance_zero_for_empty_pool(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    assert credits.workspace_balance(ws.id) == 0


def test_workspace_grant_reflected_in_balance(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    """workspace_grant appends a positive pool row; balance == SUM(delta)."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    entry = credits.workspace_grant(ws.id, 500, reason="workspace_grant")

    assert isinstance(entry, CreditLedger)
    assert entry.workspace_id == ws.id
    assert entry.delta == 500
    assert entry.balance_after == 500
    assert credits.workspace_balance(ws.id) == 500


def test_workspace_grant_accumulates(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    credits.workspace_grant(ws.id, 100, reason="workspace_grant")
    second = credits.workspace_grant(ws.id, 50, reason="workspace_grant")
    assert second.balance_after == 150
    assert credits.workspace_balance(ws.id) == 150


def test_workspace_grant_records_actor_for_audit(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    """The funding member is recorded on the row purely for audit."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    entry = credits.workspace_grant(
        ws.id, 100, reason="workspace_grant", actor_user_id=owner.id
    )
    assert entry.user_id == owner.id


def test_workspace_grant_non_positive_raises(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    with pytest.raises(ValueError, match="positive"):
        credits.workspace_grant(ws.id, 0, reason="workspace_grant")
    with pytest.raises(ValueError, match="positive"):
        credits.workspace_grant(ws.id, -5, reason="workspace_grant")


def test_workspace_debit_subtracts_and_records_negative_delta(
    credits: CreditRepository,
    workspaces: WorkspaceRepository,
    jobs: JobRepository,
    owner: User,
):
    """workspace_debit atomically reduces the pool + records a negative row."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    credits.workspace_grant(ws.id, 100, reason="workspace_grant")
    job = jobs.create(user_id=owner.id, kind="avatar_reel", params={})

    entry = credits.workspace_debit(
        ws.id, 30, job_id=job.id, reason="workspace_debit"
    )

    assert entry.delta == -30
    assert entry.workspace_id == ws.id
    assert entry.job_id == job.id
    assert entry.balance_after == 70
    assert credits.workspace_balance(ws.id) == 70


def test_workspace_debit_rejects_when_insufficient(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    """An over-debit is rejected and the pool never goes negative."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    credits.workspace_grant(ws.id, 10, reason="workspace_grant")

    with pytest.raises(ValueError, match="insufficient workspace credits"):
        credits.workspace_debit(
            ws.id, 50, job_id=None, reason="workspace_debit"
        )
    # Balance unchanged after the rejected debit — no negative pool.
    assert credits.workspace_balance(ws.id) == 10


def test_workspace_debit_non_positive_raises(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    credits.workspace_grant(ws.id, 10, reason="workspace_grant")
    with pytest.raises(ValueError, match="positive"):
        credits.workspace_debit(ws.id, 0, job_id=None, reason="workspace_debit")
    with pytest.raises(ValueError, match="positive"):
        credits.workspace_debit(ws.id, -5, job_id=None, reason="workspace_debit")


def test_workspace_debit_lock_degrades_on_sqlite(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    """FOR UPDATE is unsupported on SQLite; the pooled debit still runs cleanly.

    ``_locked_workspace_balance`` tolerates only SQLite's missing row-lock
    support and must not swallow other errors. The whole debit path runs on
    SQLite here and produces a correct pool balance without raising.
    """
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    credits.workspace_grant(ws.id, 100, reason="workspace_grant")
    entry = credits.workspace_debit(
        ws.id, 40, job_id=None, reason="workspace_debit"
    )
    assert entry.balance_after == 60
    assert credits.workspace_balance(ws.id) == 60


def test_workspace_pool_isolated_from_personal_balance(
    credits: CreditRepository, workspaces: WorkspaceRepository, owner: User
):
    """Workspace-pool rows never bleed into a member's personal balance.

    Even when the owner is recorded as the grant/debit actor, personal
    ``balance()`` (which filters ``workspace_id IS NULL``) stays 0, and the two
    pools move independently.
    """
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    credits.workspace_grant(
        ws.id, 500, reason="workspace_grant", actor_user_id=owner.id
    )
    credits.workspace_debit(
        ws.id, 200, job_id=None, reason="workspace_debit"
    )

    # Personal pool untouched by any workspace activity.
    assert credits.balance(owner.id) == 0
    assert credits.workspace_balance(ws.id) == 300

    # A personal grant does not leak into the workspace pool either.
    credits.grant(owner.id, 40, reason="signup")
    assert credits.balance(owner.id) == 40
    assert credits.workspace_balance(ws.id) == 300


def test_workspace_debit_append_only(
    credits: CreditRepository,
    workspaces: WorkspaceRepository,
    session: Session,
    owner: User,
):
    """Every pool grant/debit appends an immutable row; nothing is mutated."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    credits.workspace_grant(ws.id, 100, reason="workspace_grant")
    credits.workspace_debit(ws.id, 40, job_id=None, reason="workspace_debit")
    credits.workspace_grant(ws.id, 10, reason="workspace_grant")

    rows = (
        session.query(CreditLedger)
        .filter(CreditLedger.workspace_id == ws.id)
        .order_by(CreditLedger.id.asc())
        .all()
    )
    assert [r.delta for r in rows] == [100, -40, 10]
    assert [r.balance_after for r in rows] == [100, 60, 70]
    assert credits.workspace_balance(ws.id) == 70


# --------------------------------------------------------------------------- #
# UserPresetRepository — brand kits shared to a workspace
# --------------------------------------------------------------------------- #
def test_preset_create_defaults_no_workspace(
    presets: UserPresetRepository, user: User
):
    """A preset is private (workspace_id IS NULL) unless explicitly shared."""
    preset = presets.create(user.id, "Private Kit", _brand_kit())
    assert preset.workspace_id is None


def test_preset_create_with_workspace_id_shares_it(
    presets: UserPresetRepository, workspaces: WorkspaceRepository, owner: User
):
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    preset = presets.create(
        owner.id, "Team Kit", _brand_kit(), workspace_id=ws.id
    )
    assert preset.workspace_id == ws.id


def test_list_for_user_and_workspaces_includes_member_shared(
    presets: UserPresetRepository,
    workspaces: WorkspaceRepository,
    owner: User,
    teammate: User,
):
    """A member sees presets a teammate shared to a workspace they belong to."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    workspaces.add_member(ws.id, teammate.id, role="member")

    shared = presets.create(
        owner.id, "Team Kit", _brand_kit(), workspace_id=ws.id
    )
    own = presets.create(teammate.id, "My Private Kit", _brand_kit())

    result_ids = {
        p.id
        for p in presets.list_for_user_and_workspaces(teammate.id, [ws.id])
    }
    # The teammate sees both the shared team kit and their own private kit.
    assert result_ids == {shared.id, own.id}


def test_list_for_user_and_workspaces_excludes_non_members(
    presets: UserPresetRepository,
    workspaces: WorkspaceRepository,
    session: Session,
    owner: User,
):
    """A non-member never receives another workspace's shared presets.

    The caller resolves ``workspace_ids`` from the user's *actual* memberships;
    a non-member is a member of no workspace, so the caller passes ``[]`` and
    the shared preset stays hidden.
    """
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    shared = presets.create(
        owner.id, "Team Kit", _brand_kit(), workspace_id=ws.id
    )
    outsider = _make_user(session, "outsider@example.com")

    outsider_view = presets.list_for_user_and_workspaces(outsider.id, [])
    assert shared.id not in {p.id for p in outsider_view}
    assert outsider_view == []


def test_list_for_user_and_workspaces_dedupes_owned_and_shared(
    presets: UserPresetRepository, workspaces: WorkspaceRepository, owner: User
):
    """A preset the user owns AND shared appears exactly once."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    shared = presets.create(
        owner.id, "Team Kit", _brand_kit(), workspace_id=ws.id
    )

    result = presets.list_for_user_and_workspaces(owner.id, [ws.id])
    ids = [p.id for p in result]
    assert ids.count(shared.id) == 1


def test_list_for_user_and_workspaces_empty_ids_returns_own_only(
    presets: UserPresetRepository,
    workspaces: WorkspaceRepository,
    owner: User,
    teammate: User,
):
    """With no workspace ids the result is narrowed to the user's own presets."""
    ws = workspaces.create_workspace(name="Acme", owner_id=owner.id)
    presets.create(owner.id, "Team Kit", _brand_kit(), workspace_id=ws.id)
    mine = presets.create(teammate.id, "Mine", _brand_kit())

    result = presets.list_for_user_and_workspaces(teammate.id, [])
    assert [p.id for p in result] == [mine.id]


# --------------------------------------------------------------------------- #
# UserBrandRepository — Brand Watermark settings (get / upsert singleton)
# --------------------------------------------------------------------------- #
def test_brand_get_returns_none_when_unset(brands: UserBrandRepository, user: User):
    """A user with no brand row yet resolves to None (no watermark configured)."""
    assert brands.get(user.id) is None
    # A blank user id never matches an unrelated row.
    assert brands.get("") is None
    assert brands.get("   ") is None


def test_brand_upsert_inserts_with_defaults(
    brands: UserBrandRepository, user: User
):
    """First upsert inserts a row; unset columns take their model defaults."""
    brand = brands.upsert(user.id, logo_key="brands/logo.png")

    assert brand.id and len(brand.id) == 32
    assert brand.user_id == user.id
    assert brand.logo_key == "brands/logo.png"
    # Column defaults describe an enabled bottom_right watermark at 0.85 opacity.
    assert brand.position == "bottom_right"
    assert brand.opacity == 0.85
    assert brand.enabled is True


def test_brand_upsert_updates_existing_row_in_place(
    brands: UserBrandRepository, session: Session, user: User
):
    """A second upsert updates the SAME row (singleton), never inserts a new one."""
    first = brands.upsert(user.id, logo_key="brands/a.png", opacity=0.5)
    second = brands.upsert(user.id, position="top_left", enabled=False)

    assert second.id == first.id
    # Only the fields passed on the second call changed; logo_key/opacity persist.
    assert second.logo_key == "brands/a.png"
    assert second.opacity == 0.5
    assert second.position == "top_left"
    assert second.enabled is False

    # Exactly one row exists for the user (upsert, not append).
    rows = session.query(UserBrand).filter(UserBrand.user_id == user.id).all()
    assert len(rows) == 1


def test_brand_upsert_partial_leaves_other_fields(
    brands: UserBrandRepository, user: User
):
    """Passing None (or omitting) a field leaves the stored value untouched."""
    brands.upsert(user.id, logo_key="brands/x.png", position="top_right", opacity=0.9)
    updated = brands.upsert(user.id, opacity=None, position=None, logo_key=None)

    assert updated.logo_key == "brands/x.png"
    assert updated.position == "top_right"
    assert updated.opacity == 0.9


def test_brand_upsert_clamps_opacity(brands: UserBrandRepository, user: User):
    """Out-of-range opacity is clamped to [0.0, 1.0] (untrusted API input)."""
    assert brands.upsert(user.id, opacity=5.0).opacity == 1.0
    assert brands.upsert(user.id, opacity=-2.0).opacity == 0.0


def test_brand_upsert_normalizes_unknown_position(
    brands: UserBrandRepository, user: User
):
    """An unknown corner falls back to the default rather than persisting garbage."""
    assert brands.upsert(user.id, position="middle").position == "bottom_right"
    # A known corner (any casing/whitespace) is normalized and kept.
    assert brands.upsert(user.id, position="  TOP_LEFT ").position == "top_left"


def test_brand_upsert_coerces_enabled_to_bool(
    brands: UserBrandRepository, user: User
):
    """enabled is coerced to a real bool so a truthy/falsy payload is safe."""
    assert brands.upsert(user.id, enabled=0).enabled is False
    assert brands.upsert(user.id, enabled=1).enabled is True


def test_brand_upsert_rejects_blank_user_id(brands: UserBrandRepository):
    """A blank user id can never persist an ownerless brand row."""
    with pytest.raises(ValueError):
        brands.upsert("", logo_key="x")
    with pytest.raises(ValueError):
        brands.upsert("   ", logo_key="x")


def test_brand_round_trip(
    brands: UserBrandRepository, session: Session, user: User
):
    """Settings persist and reload correctly from the DB."""
    brands.upsert(
        user.id, logo_key="brands/rt.png", position="bottom_left",
        opacity=0.4, enabled=False,
    )
    session.expire_all()  # force a reload from the DB, not the identity map

    reloaded = session.get(UserBrand, brands.get(user.id).id)
    assert reloaded.logo_key == "brands/rt.png"
    assert reloaded.position == "bottom_left"
    assert reloaded.opacity == 0.4
    assert reloaded.enabled is False


def test_brand_user_id_is_unique(session: Session, user: User):
    """The user_id column is UNIQUE — a second brand row for a user is rejected."""
    from sqlalchemy.exc import IntegrityError

    session.add(UserBrand(user_id=user.id, logo_key="a"))
    session.flush()
    session.add(UserBrand(user_id=user.id, logo_key="b"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_brand_columns_present_in_table_metadata():
    """Model declares the UNIQUE, indexed user_id + defaulted columns.

    Mirrors migration 54e4dca8a24a (a brand-new ``user_brands`` table with a
    UNIQUE index on ``user_id`` and server_defaults describing an enabled
    bottom_right watermark at 0.85 opacity) so Alembic autogenerate reports no
    drift and the render pipeline resolves the singleton by owner id.
    """
    cols = UserBrand.__table__.columns
    assert cols["user_id"].index is True
    assert cols["user_id"].unique is True
    assert cols["user_id"].nullable is False
    assert cols["logo_key"].default.arg == ""
    assert cols["position"].default.arg == "bottom_right"
    assert cols["opacity"].default.arg == 0.85
    assert cols["enabled"].default.arg is True
    for name in ("logo_key", "position", "opacity", "enabled"):
        assert cols[name].server_default is not None, (
            f"{name} must declare server_default to match migration 54e4dca8a24a"
        )


# --------------------------------------------------------------------------- #
# UserApiKeyRepository — PUBLIC API KEYS (create / list / get_by_hash / revoke /
# touch_last_used + ownership + unique hash + revoked exclusion). SECURITY: only
# SHA-256 digests are ever stored, never the raw key.
# --------------------------------------------------------------------------- #
def _sha256(raw: str) -> str:
    """Return the SHA-256 hex digest of a raw key (as the auth path would)."""
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_api_key_create_returns_active_row_with_id(
    api_keys: UserApiKeyRepository, user: User
):
    key_hash = _sha256("rf_secret_raw_key_value")
    row = api_keys.create(user.id, "CI", key_hash, prefix="rf_ab12")

    assert row.id and len(row.id) == 32
    assert row.user_id == user.id
    assert row.name == "CI"
    assert row.key_hash == key_hash
    assert len(row.key_hash) == 64  # sha256 hex digest
    assert row.prefix == "rf_ab12"
    # A freshly minted key is active and has never been used.
    assert row.revoked is False
    assert row.last_used_at is None
    assert row.created_at is not None


def test_api_key_create_stores_only_hash_not_raw_secret(
    api_keys: UserApiKeyRepository, session: Session, user: User
):
    """SECURITY: the raw key must never appear in any persisted column."""
    raw = "rf_this_is_the_raw_secret_never_stored"
    row = api_keys.create(user.id, "K", _sha256(raw), prefix="rf_this")

    session.expire_all()  # force a reload from the DB, not the identity map
    reloaded = session.get(UserApiKey, row.id)
    # No column holds the raw secret — only its digest is present.
    assert reloaded.key_hash == _sha256(raw)
    assert raw not in (
        reloaded.key_hash,
        reloaded.prefix,
        reloaded.name,
    )


def test_api_key_create_rejects_blank_user_and_hash(
    api_keys: UserApiKeyRepository, user: User
):
    with pytest.raises(ValueError):
        api_keys.create("", "K", _sha256("x"), prefix="rf_x")
    with pytest.raises(ValueError):
        api_keys.create("   ", "K", _sha256("x"), prefix="rf_x")
    with pytest.raises(ValueError):
        api_keys.create(user.id, "K", "", prefix="rf_x")
    with pytest.raises(ValueError):
        api_keys.create(user.id, "K", "   ", prefix="rf_x")


def test_api_key_create_coerces_blank_name_and_prefix(
    api_keys: UserApiKeyRepository, user: User
):
    row = api_keys.create(user.id, "", _sha256("y"), prefix="")
    assert row.name == ""
    assert row.prefix == ""


def test_api_key_unique_hash_constraint(session: Session, user: User):
    """The key_hash column is UNIQUE — the same digest cannot be stored twice."""
    from sqlalchemy.exc import IntegrityError

    digest = _sha256("collision")
    session.add(UserApiKey(user_id=user.id, name="a", key_hash=digest, prefix="p"))
    session.flush()
    session.add(UserApiKey(user_id=user.id, name="b", key_hash=digest, prefix="p"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_api_key_list_for_user_includes_revoked_newest_first(
    api_keys: UserApiKeyRepository, session: Session
):
    """list_for_user returns ALL keys (active + revoked), newest first, scoped."""
    from datetime import datetime, timedelta, timezone

    u1 = User(email="k1@example.com")
    u2 = User(email="k2@example.com")
    session.add_all([u1, u2])
    session.flush()

    a = api_keys.create(u1.id, "A", _sha256("a"), prefix="rf_a")
    b = api_keys.create(u1.id, "B", _sha256("b"), prefix="rf_b")
    api_keys.create(u2.id, "C", _sha256("c"), prefix="rf_c")

    # SQLite CURRENT_TIMESTAMP has 1s resolution; set explicit ordered stamps so
    # the newest-first assertion is deterministic within the same test tick.
    base = datetime(2026, 8, 12, tzinfo=timezone.utc)
    a.created_at = base
    b.created_at = base + timedelta(seconds=1)
    session.flush()

    # Revoke one key — it must STILL appear in the list (revoked keys are shown
    # for audit/display with their flag, not filtered out).
    assert api_keys.revoke(a.id, u1.id) is True

    listed = api_keys.list_for_user(u1.id)
    assert [k.name for k in listed] == ["B", "A"]  # newest first, revoked kept
    assert [k.revoked for k in listed] == [False, True]
    assert len(api_keys.list_for_user(u2.id)) == 1
    assert api_keys.list_for_user("nobody") == []


def test_api_key_get_by_hash_resolves_owner(
    api_keys: UserApiKeyRepository, user: User
):
    raw = "rf_lookup_me"
    digest = _sha256(raw)
    row = api_keys.create(user.id, "K", digest, prefix="rf_look")

    found = api_keys.get_by_hash(digest)
    assert found is not None
    assert found.id == row.id
    assert found.user_id == user.id


def test_api_key_get_by_hash_excludes_revoked(
    api_keys: UserApiKeyRepository, user: User
):
    """A revoked key can never authenticate — get_by_hash must not resolve it."""
    digest = _sha256("rf_to_be_revoked")
    row = api_keys.create(user.id, "K", digest, prefix="rf_rev")

    assert api_keys.get_by_hash(digest) is not None
    assert api_keys.revoke(row.id, user.id) is True
    # Once revoked, the digest no longer resolves to a live row.
    assert api_keys.get_by_hash(digest) is None


def test_api_key_get_by_hash_unknown_and_blank(
    api_keys: UserApiKeyRepository, user: User
):
    api_keys.create(user.id, "K", _sha256("real"), prefix="rf_real")
    assert api_keys.get_by_hash(_sha256("does-not-exist")) is None
    assert api_keys.get_by_hash("") is None
    assert api_keys.get_by_hash("   ") is None


def test_api_key_revoke_enforces_ownership(
    api_keys: UserApiKeyRepository, session: Session
):
    """A user can never revoke another user's key by guessing its id."""
    owner = User(email="owner-k@example.com")
    other = User(email="other-k@example.com")
    session.add_all([owner, other])
    session.flush()
    digest = _sha256("rf_owned")
    row = api_keys.create(owner.id, "Owned", digest, prefix="rf_own")

    # A foreign user cannot revoke it; the key survives and still resolves.
    assert api_keys.revoke(row.id, other.id) is False
    assert api_keys.get_by_hash(digest) is not None

    # The owner revokes it successfully; a second revoke is a no-op False.
    assert api_keys.revoke(row.id, owner.id) is True
    assert api_keys.revoke(row.id, owner.id) is False
    assert api_keys.get_by_hash(digest) is None


def test_api_key_revoke_missing_returns_false(
    api_keys: UserApiKeyRepository, user: User
):
    assert api_keys.revoke("does-not-exist", user.id) is False


def test_api_key_touch_last_used_stamps_now(
    api_keys: UserApiKeyRepository, session: Session, user: User
):
    row = api_keys.create(user.id, "K", _sha256("rf_touch"), prefix="rf_t")
    assert row.last_used_at is None

    api_keys.touch_last_used(row.id)
    session.expire_all()  # force a reload from the DB, not the identity map
    reloaded = session.get(UserApiKey, row.id)
    assert reloaded.last_used_at is not None


def test_api_key_touch_last_used_missing_is_noop(
    api_keys: UserApiKeyRepository
):
    # Must not raise even when the key does not exist (best-effort telemetry).
    api_keys.touch_last_used("does-not-exist")


def test_api_key_columns_present_in_table_metadata():
    """UserApiKey declares the UNIQUE/indexed columns the migration relies on.

    Mirrors migration 4e73c6aaa0a5 (a brand-new ``user_api_keys`` table with a
    UNIQUE index on ``key_hash`` and plain indexes on ``user_id`` + ``revoked``)
    so a presented key resolves to one owner and the live-key filter is an
    O(index) lookup, with no Alembic autogenerate drift.
    """
    cols = UserApiKey.__table__.columns
    assert cols["user_id"].index is True
    assert cols["user_id"].nullable is False
    # key_hash is the sha256 hex digest (64 chars), UNIQUE + indexed.
    assert cols["key_hash"].unique is True
    assert cols["key_hash"].index is True
    assert cols["key_hash"].type.length == 64
    assert cols["key_hash"].nullable is False
    assert cols["prefix"].type.length == 16
    assert cols["revoked"].index is True
    assert cols["revoked"].nullable is False
    assert cols["revoked"].default.arg is False
    assert cols["last_used_at"].nullable is True
    for name in ("name", "prefix", "revoked"):
        assert cols[name].server_default is not None, (
            f"{name} must declare server_default to match migration 4e73c6aaa0a5"
        )


def test_media_job_identity_and_settlement_columns_are_restart_safe():
    """Identity binding and receipt state survive worker/process restarts.

    Every recovery field has a database default as well as an ORM default so
    Alembic-created databases and ``Base.metadata.create_all`` behave alike.
    """
    cols = MediaJob.__table__.columns
    expected = {
        "identity_passport_id",
        "identity_version",
        "identity_content_digest",
        "identity_provider",
        "identity_provenance_id",
        "identity_status",
        "mint_hold_id",
        "settlement_request_id",
        "settlement_payer_account",
        "settlement_receipt",
        "settlement_settled_at_ms",
    }
    assert expected <= set(cols.keys())
    for name in expected:
        assert cols[name].nullable is False
        assert cols[name].server_default is not None, (
            f"{name} must have a server default for rolling upgrades"
        )
