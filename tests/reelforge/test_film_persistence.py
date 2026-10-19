"""FilmProject persistence — plan → project + shots → assemble on completion."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.characters.consistency import CharacterProfile
from app.domains.film.orchestrator import plan_film
from app.domains.film.repository import FilmRepository
from app.domains.storyboard.shotlist import SceneBeat
from app.models.db import film, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(User(id="u1", email="u@x.com"))
    s.flush()
    yield s
    s.close()


def _plan():
    beats = [SceneBeat("sc1", "hero enters", weight=2.0), SceneBeat("sc2", "twist", weight=1.0)]
    char = CharacterProfile("c1", "Nova", descriptors=("red jacket",), style="3D")
    return plan_film(beats, char, total_shots=6, target_runtime_s=18.0)


def test_create_from_plan_writes_project_and_shots(session):
    repo = FilmRepository(session)
    project = repo.create_from_plan(_plan(), user_id="u1", title="Ep1", character_id="c1")
    assert project.shot_count == 6 and project.status == "planned"

    shots = repo.shots(project.id)
    assert len(shots) == 6
    assert [s.order for s in shots] == list(range(6))
    # Each shot carries the identity-locked prompt + a seed.
    assert all("Nova" in s.prompt for s in shots)
    assert all(s.seed != 0 for s in shots)


def test_project_is_shots_ready_when_all_shots_done(session):
    repo = FilmRepository(session)
    project = repo.create_from_plan(_plan(), user_id="u1")
    shots = repo.shots(project.id)
    for s in shots[:-1]:
        repo.mark_shot(s.id, status="done", render_job_id="job")
    # Still not ready until the last shot is done.
    assert repo.get(project.id).status == "planned"
    repo.mark_shot(shots[-1].id, status="done")
    # All shots rendered -> ``shots_ready``; the stitched final video is produced
    # separately by the export task.
    assert repo.get(project.id).status == "shots_ready"
