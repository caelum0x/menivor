"""Gateway persistence — provisioning keys + spend-gated, marked-up charging (sqlite)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.gateway import service as gw
from app.models.db import gateway, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(User(id="reseller", email="r@x.com"))
    s.flush()
    yield s
    s.close()


def _now():
    return datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def test_create_key_returns_secret_once_and_hashes(session):
    row, secret = gw.create_key(session, owner_id="reseller", daily_cap_micros=1_000_000,
                                label="acme", markup_bps=2000)
    assert secret.startswith("rf_pk_")
    assert row.key_hash == gw.hash_secret(secret)
    # Resolvable by the secret.
    assert gw.resolve_key(session, secret).id == row.id
    assert gw.resolve_key(session, "wrong") is None


def test_markup_applied_and_recorded(session):
    key, _ = gw.create_key(session, owner_id="reseller", daily_cap_micros=1_000_000,
                           markup_bps=2000, min_fee_micros=1000)  # +20% + 1000
    res = gw.authorize_and_record(session, key, 100_000, now=_now(), model_key="kling")
    assert res.allowed and res.customer_price_micros == 121_000
    # Recorded in usage; today's spend reflects it.
    assert gw.spent_today(session, key.id, now=_now()) == 121_000


def test_daily_cap_blocks_and_records_nothing(session):
    key, _ = gw.create_key(session, owner_id="reseller", daily_cap_micros=150_000, markup_bps=0)
    first = gw.authorize_and_record(session, key, 100_000, now=_now())
    assert first.allowed  # 100k <= 150k
    second = gw.authorize_and_record(session, key, 100_000, now=_now())  # would total 200k
    assert not second.allowed and "daily cap" in second.reason
    # The blocked charge left no usage row (still just the first 100k).
    assert gw.spent_today(session, key.id, now=_now()) == 100_000


def test_unlimited_key_allows(session):
    key, _ = gw.create_key(session, owner_id="reseller", daily_cap_micros=0)
    res = gw.authorize_and_record(session, key, 5_000_000, now=_now())
    assert res.allowed and res.remaining_micros == -1


def test_window_resets_next_day(session):
    key, _ = gw.create_key(session, owner_id="reseller", daily_cap_micros=150_000)
    gw.authorize_and_record(session, key, 100_000, now=_now())
    # A charge on the NEXT UTC day sees a fresh window (0 spent).
    next_day = datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc)
    assert gw.spent_today(session, key.id, now=next_day) == 0
    assert gw.authorize_and_record(session, key, 100_000, now=next_day).allowed
