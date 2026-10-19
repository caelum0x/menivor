"""Canon service — folds Wave-4 character identity + end-to-end asset verify (sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.canon import binding, service
from app.domains.canon.repository import CanonRepository
from app.domains.characters.consistency import CharacterProfile
from app.domains.characters.repository import CharacterRepository
from app.models.db import canon, characters, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import Asset, User


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


def test_build_values_folds_bound_character_identity(session):
    char = CharacterRepository(session).create(
        user_id="u1",
        profile=CharacterProfile(character_id="", name="Nova",
                                 descriptors=("silver hair",), style="3D"),
    )
    values = service.build_values(session, character_id=char.id, style="3D",
                                  palette=("#ff0000",))
    # The Wave-4 identity_key is folded in verbatim as a primitive.
    assert values.character_identity_key == char.identity_key
    # No bound character -> empty identity component.
    assert service.build_values(session, style="3D").character_identity_key == ""


def test_bound_character_participates_in_the_lock(session):
    char = CharacterRepository(session).create(
        user_id="u1",
        profile=CharacterProfile(character_id="", name="Nova", descriptors=("silver hair",)),
    )
    with_char = service.build_values(session, character_id=char.id, style="3D").canon_hash()
    without = service.build_values(session, style="3D").canon_hash()
    assert with_char != without  # the character changes the content address


def test_end_to_end_create_stamp_verify(session):
    values = service.build_values(session, style="3D", palette=("#ff0000",),
                                  product_name="Nova")
    c = CanonRepository(session).create_canon(user_id="u1", name="Brand", values=values)

    meta = binding.stamp_asset_meta({}, canon_id=c.id, canon_hash=c.current_canon_hash,
                                    canon_version=c.current_version)
    session.add(Asset(id="a1", user_id="u1", kind="final", r2_key="f/ok.mp4", meta=meta))
    session.flush()

    assert service.verify_asset(session, "a1", c.id).verified is True
    # Unknown asset id is reported, not raised.
    assert service.verify_asset(session, "missing", c.id).verified is False


def test_verify_falls_back_to_current_version_for_unstamped_asset(session):
    values = service.build_values(session, style="3D")
    c = CanonRepository(session).create_canon(user_id="u1", name="Brand", values=values)
    session.add(Asset(id="raw", user_id="u1", kind="final", r2_key="f/raw.mp4", meta={}))
    session.flush()
    res = service.verify_asset(session, "raw", c.id)
    assert res.verified is False and res.reason == "asset not stamped"
