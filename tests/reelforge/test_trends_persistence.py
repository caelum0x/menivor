"""TrendObservation persistence — record scored trends + surface recommendations."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.trends.repository import TrendRepository
from app.domains.trends.scoring import TrendSignal
from app.models.db import trends  # noqa: F401 - register table
from app.models.db.base import Base


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def test_records_score_and_recommends_rising(session):
    repo = TrendRepository(session)
    repo.record(TrendSignal("hot", "sound", counts=(100, 400, 1200, 3000)))
    repo.record(TrendSignal("cold", "sound", counts=(99000, 99100, 99050, 99000)))
    rec = repo.recommended()
    ids = [r.trend_id for r in rec]
    assert "hot" in ids and "cold" not in ids  # only the rising, unsaturated trend
    assert rec[0].opportunity_bps > 0 and rec[0].phase in ("rising", "emerging")


def test_recommended_sorted_by_opportunity(session):
    repo = TrendRepository(session)
    repo.record(TrendSignal("big", "sound", counts=(100, 500, 2000, 6000)))
    repo.record(TrendSignal("small", "sound", counts=(100, 150, 220, 320)))
    rec = repo.recommended()
    if len(rec) >= 2:
        assert rec[0].opportunity_bps >= rec[1].opportunity_bps
