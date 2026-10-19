"""Unmeasured completion/rewatch rates are NULL ("not measured"), never a fake 0%."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.publishing.experiment_repo import ExperimentRepository
from app.domains.publishing.experiments import VariantMetrics, score_variant, select_winner
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


def test_new_variant_rates_start_unmeasured(session):
    repo = ExperimentRepository(session)
    exp = repo.create(user_id="u1", experiment_key="exp-n", hook_refs=["a", "b"])
    for v in repo.variants(exp.id):
        session.refresh(v)
        assert v.completion_rate is None
        assert v.rewatch_rate is None


def test_ingest_without_rates_stores_null(session):
    repo = ExperimentRepository(session)
    exp = repo.create(user_id="u1", experiment_key="exp-m", hook_refs=["a", "b"])
    v = repo.variants(exp.id)[0]
    repo.ingest_metrics(experiment_key="exp-m", variant_id=v.id, views=500,
                        completion_rate=None, avg_watch_frac=0.4)
    session.refresh(v)
    assert v.completion_rate is None and v.rewatch_rate is None
    assert v.avg_watch_frac == pytest.approx(0.4)


def test_unmeasured_metric_is_not_scored_as_zero():
    measured = VariantMetrics("a", "hA", views=1000, completion_rate=0.5, avg_watch_frac=0.5,
                              rewatch_rate=0.5, engagement_rate=0.5)
    partial = VariantMetrics("b", "hB", views=1000, completion_rate=None, avg_watch_frac=0.5,
                             rewatch_rate=None, engagement_rate=0.5)
    # Same values on what IS measured -> same score, not a penalty for NULL.
    assert score_variant(partial) == pytest.approx(score_variant(measured))


def test_winner_compares_only_commonly_measured_metrics():
    # 'b' has a great completion rate that 'a' never reported; with 'a' treated
    # as 0% completion 'b' would win. Compared on shared metrics, 'a' wins.
    a = VariantMetrics("a", "hA", views=1000, completion_rate=None, avg_watch_frac=0.8,
                       engagement_rate=0.1)
    b = VariantMetrics("b", "hB", views=1000, completion_rate=0.9, avg_watch_frac=0.3,
                       engagement_rate=0.1)
    res = select_winner([a, b])
    assert res.conclusive and res.winner_id == "a"


def test_fully_measured_scoring_unchanged():
    m = VariantMetrics("a", "hA", views=1000, completion_rate=0.8, avg_watch_frac=0.7,
                       rewatch_rate=0.2, engagement_rate=0.05)
    expected = 0.45 * 0.8 + 0.30 * 0.7 + 0.15 * 0.2 + 0.10 * 0.05
    assert score_variant(m) == pytest.approx(round(expected, 4))
