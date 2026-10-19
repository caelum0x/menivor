"""A/B experiment persistence — create, ingest retention, evaluate winner (sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.publishing.experiment_repo import ExperimentError, ExperimentRepository
from app.models.db import experiments, models  # noqa: F401 - register tables
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


def test_create_requires_two_variants(session):
    repo = ExperimentRepository(session)
    with pytest.raises(ExperimentError):
        repo.create(user_id="u1", experiment_key="exp-1", hook_refs=["only-one"])


def test_ingest_and_evaluate_conclusive(session):
    repo = ExperimentRepository(session)
    exp = repo.create(user_id="u1", experiment_key="exp-1", hook_refs=["hookA", "hookB"])
    variants = repo.variants(exp.id)
    a = next(v for v in variants if v.hook_ref == "hookA")
    b = next(v for v in variants if v.hook_ref == "hookB")

    repo.ingest_metrics(experiment_key="exp-1", variant_id=a.id, views=1000,
                        completion_rate=0.8, avg_watch_frac=0.7, rewatch_rate=0.2)
    repo.ingest_metrics(experiment_key="exp-1", variant_id=b.id, views=1000,
                        completion_rate=0.4, avg_watch_frac=0.3, rewatch_rate=0.05)

    result = repo.evaluate("exp-1")
    assert result.status == "conclusive"
    assert result.winner_variant_id == a.id and result.winner_hook_ref == "hookA"


def test_evaluate_inconclusive_when_underpowered(session):
    repo = ExperimentRepository(session)
    exp = repo.create(user_id="u1", experiment_key="exp-2", hook_refs=["hookA", "hookB"])
    for v in repo.variants(exp.id):
        repo.ingest_metrics(experiment_key="exp-2", variant_id=v.id, views=10,
                            completion_rate=0.5, avg_watch_frac=0.5)
    result = repo.evaluate("exp-2")
    assert result.status == "running" and result.winner_variant_id == ""


def test_ingest_unknown_variant_rejected(session):
    repo = ExperimentRepository(session)
    repo.create(user_id="u1", experiment_key="exp-3", hook_refs=["a", "b"])
    with pytest.raises(ExperimentError):
        repo.ingest_metrics(experiment_key="exp-3", variant_id="ghost", views=1,
                            completion_rate=0.5, avg_watch_frac=0.5)
