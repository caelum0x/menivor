"""RenderJob persistence — envelope ↔ ORM round-trip over sqlite."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db import models  # noqa: F401 - registers users table (FK target)
from app.models.db import render  # noqa: F401 - registers render_jobs
from app.models.db.render_repo import RenderJobRepository, row_to_envelope
from app.services.render import envelope as env


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, future=True)
    s = Factory()
    # A user row for the FK.
    from app.models.db.models import User

    s.add(User(id="u1", email="u@x.com"))
    s.commit()
    yield s
    s.close()


def test_create_and_roundtrip_envelope(session):
    repo = RenderJobRepository(session)
    job = env.RenderJob(id="job-1", backend="runpod", workflow_version="wan@1",
                        state=env.IN_QUEUE, provider_ref="rp-1")
    repo.create(job, user_id="u1", held_cost_micros=120_000)
    session.commit()

    back = row_to_envelope(repo.get("job-1"))
    assert back.id == "job-1" and back.backend == "runpod" and back.state == env.IN_QUEUE
    assert back.provider_ref == "rp-1"


def test_save_advanced_envelope_persists_terminal(session):
    repo = RenderJobRepository(session)
    job = env.RenderJob(id="job-2", backend="runpod", state=env.IN_PROGRESS, provider_ref="rp-2")
    repo.create(job, user_id="u1", held_cost_micros=90_000)
    session.commit()

    done = env.transition(job, env.COMPLETED, output_refs=("https://cdn/o.mp4",), cost_micros=80_000)
    repo.save_envelope(done)
    session.commit()

    row = repo.get("job-2")
    assert row.state == env.COMPLETED and row.progress == 100
    assert row.output_refs == "https://cdn/o.mp4" and row.actual_cost_micros == 80_000
    # Round-trips back to a tuple.
    assert row_to_envelope(row).output_refs == ("https://cdn/o.mp4",)


def test_list_active_excludes_terminal(session):
    repo = RenderJobRepository(session)
    repo.create(env.RenderJob(id="a", backend="runpod", state=env.IN_QUEUE), user_id="u1")
    repo.create(env.RenderJob(id="b", backend="runpod", state=env.IN_PROGRESS), user_id="u1")
    repo.create(env.transition(env.RenderJob(id="c", backend="runpod"), env.COMPLETED), user_id="u1")
    session.commit()
    active_ids = {r.id for r in repo.list_active()}
    assert active_ids == {"a", "b"}  # completed 'c' excluded
