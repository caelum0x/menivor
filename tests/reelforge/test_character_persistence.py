"""Character persistence — save + reuse + dedupe identity-locked characters (sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.characters.consistency import CharacterProfile, build_shot_prompt
from app.domains.characters.repository import CharacterRepository, to_profile
from app.models.db import characters, models  # noqa: F401 - register tables
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


def _profile():
    return CharacterProfile(
        character_id="", name="Nova", descriptors=("silver hair", "red jacket"),
        reference_images=("r2://sheet.png",), style="3D pixar", negative=("blurry",),
    )


def test_save_and_reuse_across_projects(session):
    repo = CharacterRepository(session)
    row = repo.create(user_id="u1", profile=_profile())
    assert row.identity_key == _profile().identity_key()

    # Rebuild the pure profile from the row and produce a locked shot prompt.
    profile = to_profile(row)
    sp = build_shot_prompt(profile, "walks in the rain", shot_index=1)
    assert sp.prompt.startswith("Nova, silver hair, red jacket")
    assert sp.reference_images == ("r2://sheet.png",)


def test_dedupe_by_identity(session):
    repo = CharacterRepository(session)
    repo.create(user_id="u1", profile=_profile())
    # A profile with the SAME locked identity is detected as a duplicate.
    dup = repo.find_duplicate("u1", _profile())
    assert dup is not None and dup.name == "Nova"
    # A different identity is not a duplicate.
    other = CharacterProfile(character_id="", name="Zed", descriptors=("blue",))
    assert repo.find_duplicate("u1", other) is None


def test_owner_scoping(session):
    repo = CharacterRepository(session)
    row = repo.create(user_id="u1", profile=_profile())
    assert repo.get_owned(row.id, "u1") is not None
    assert repo.get_owned(row.id, "someone-else") is None
