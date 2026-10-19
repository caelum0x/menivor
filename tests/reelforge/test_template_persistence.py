"""TemplateInstance persistence + genre analytics (sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.templates.repository import TemplateInstanceRepository
from app.models.db import models, templates  # noqa: F401 - register tables
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


def test_record_and_list_for_user(session):
    repo = TemplateInstanceRepository(session)
    repo.record(user_id="u1", template_slug="minecraft-reddit-split", template_version="1.0.0",
                inputs={"story": "x"}, duration_s=45, reel_job_id="job-1")
    rows = repo.list_for_user("u1")
    assert len(rows) == 1 and rows[0].template_slug == "minecraft-reddit-split"
    assert rows[0].duration_s == 45 and rows[0].reel_job_id == "job-1"


def test_popular_templates_ranks_by_count(session):
    repo = TemplateInstanceRepository(session)
    for _ in range(3):
        repo.record(user_id="u1", template_slug="minecraft-reddit-split", template_version="1.0.0",
                    inputs={}, duration_s=45)
    repo.record(user_id="u1", template_slug="asmr-satisfying-loop", template_version="1.0.0",
                inputs={}, duration_s=5)
    popular = repo.popular_templates()
    assert popular[0] == {"template_slug": "minecraft-reddit-split", "count": 3}
    assert popular[1] == {"template_slug": "asmr-satisfying-loop", "count": 1}
