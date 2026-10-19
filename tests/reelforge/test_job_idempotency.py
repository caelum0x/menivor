"""Durability, concurrency, and lifecycle coverage for job-create idempotency."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.controllers.v1.jobs as jobs_mod
from app.models.db.base import Base
from app.models.db.models import JobRequest, User
from app.services import job_idempotency


def test_concurrent_idempotency_reservations_have_one_winner(tmp_path):
    """Two independent DB sessions racing a key produce one durable winner.

    This intentionally uses a file-backed SQLite database rather than the
    suite's shared in-memory connection: each thread receives a real separate
    connection, exercising the unique-constraint race and the controller's
    nested-transaction recovery path.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'idempotency-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Factory.begin() as session:
        user = User(email="race@example.com")
        session.add(user)
        session.flush()
        user_id = user.id

    barrier = Barrier(2)

    def reserve() -> tuple[bool, dict]:
        barrier.wait(timeout=5)
        with Factory() as session:
            row, replay = jobs_mod._reserve_job_idempotency_key(
                session,
                user_id,
                "same-key",
                "a" * 64,
                "race-test",
            )
            session.commit()
            return row is not None and replay is None, replay or {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: reserve(), range(2)))

    assert sum(is_new for is_new, _ in outcomes) == 1
    assert sum(replay == {} for _, replay in outcomes) == 2
    with Factory() as session:
        rows = session.query(JobRequest).all()
    assert len(rows) == 1
    assert rows[0].idempotency_key == "same-key"


def test_sweep_expired_job_requests_is_bounded_and_keeps_retry_window(monkeypatch):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    now = datetime.now(UTC)
    with Factory.begin() as session:
        user = User(email="cleanup@example.com")
        session.add(user)
        session.flush()
        session.add_all(
            [
                JobRequest(
                    user_id=user.id,
                    idempotency_key=f"expired-{index}",
                    request_hash="a" * 64,
                    response_data={},
                    created_at=now - timedelta(days=2),
                )
                for index in range(2)
            ]
            + [
                JobRequest(
                    user_id=user.id,
                    idempotency_key="recent",
                    request_hash="b" * 64,
                    response_data={},
                    created_at=now - timedelta(hours=1),
                )
            ]
        )

    @contextmanager
    def fake_get_session():
        with Factory.begin() as session:
            yield session

    monkeypatch.setattr(job_idempotency, "get_session", fake_get_session)

    assert job_idempotency.sweep_expired_job_requests(now=now, limit=1) == {
        "deleted": 1
    }
    assert job_idempotency.sweep_expired_job_requests(now=now, limit=10) == {
        "deleted": 1
    }
    with Factory() as session:
        assert [row.idempotency_key for row in session.query(JobRequest).all()] == [
            "recent"
        ]
