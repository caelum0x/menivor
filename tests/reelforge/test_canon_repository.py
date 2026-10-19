"""Canon repository — append-only versioning, never-stale hash, dedupe (sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.canon.canon_hash import CanonValues, canon_hash
from app.domains.canon.repository import CanonRepository
from app.models.db import canon, characters, models  # noqa: F401 - register tables
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


def _values(**over) -> CanonValues:
    base = dict(style="3D", palette=("#ff0000",), product_name="Nova",
                brand_avoid=("cheap",))
    base.update(over)
    return CanonValues(**base)


def test_create_canon_writes_header_and_v1(session):
    repo = CanonRepository(session)
    canon_row = repo.create_canon(user_id="u1", name="Brand", values=_values())
    assert canon_row.current_version == 1
    # Stored header hash equals a fresh recompute from the stored values.
    v1 = repo.get_version(canon_row.id, 1)
    assert v1 is not None
    assert canon_row.current_canon_hash == canon_hash(CanonValues(**v1.values))
    assert v1.canon_hash == canon_row.current_canon_hash


def test_lock_new_version_appends_and_retains_old(session):
    repo = CanonRepository(session)
    c = repo.create_canon(user_id="u1", name="Brand", values=_values())
    old_hash = c.current_canon_hash
    v2 = repo.lock_new_version(c.id, _values(style="watercolor"))
    assert v2.version == 2
    assert c.current_version == 2 and c.current_canon_hash == v2.canon_hash
    assert v2.canon_hash != old_hash
    # The old immutable snapshot is retained unchanged.
    v1 = repo.get_version(c.id, 1)
    assert v1.canon_hash == old_hash
    assert canon_hash(CanonValues(**v1.values)) == old_hash
    assert len(repo.list_versions(c.id)) == 2


def test_relock_identical_values_is_dedupe_noop(session):
    repo = CanonRepository(session)
    c = repo.create_canon(user_id="u1", name="Brand", values=_values())
    res = repo.lock_new_version(c.id, _values())  # identical values
    assert res.version == 1  # returns the existing current version
    assert c.current_version == 1
    assert len(repo.list_versions(c.id)) == 1  # no new row


def test_never_stale_hash_and_index_lookups(session):
    repo = CanonRepository(session)
    c = repo.create_canon(user_id="u1", name="Brand", values=_values())
    repo.lock_new_version(c.id, _values(style="watercolor"))
    for v in repo.list_versions(c.id):
        assert v.canon_hash == canon_hash(CanonValues(**v.values))
        assert repo.get_version_by_hash(c.id, v.canon_hash).id == v.id
    assert repo.find_by_hash(c.current_canon_hash).id == c.id


def test_owner_scoping_and_listing(session):
    session.add(User(id="u2", email="u2@x.com"))
    session.flush()
    repo = CanonRepository(session)
    c = repo.create_canon(user_id="u1", name="Brand", values=_values())
    assert repo.get_owned(c.id, "u1") is not None
    assert repo.get_owned(c.id, "u2") is None
    assert [x.id for x in repo.list_for_user("u1")] == [c.id]
    assert repo.list_for_user("u2") == []
