"""Marketplace Remix Trees — service + repository unit tests.

Runs entirely against an in-memory SQLite engine (no Postgres/Neon required),
mirroring ``test_marketplace.py``. Anchors the remix-tree behavior:

* **Publishing a clone records the parent + bumps ``remix_count`` exactly once**
  — publishing from a preset that carries ``source_marketplace_id`` sets the new
  listing's ``parent_template_id`` to that source and increments the parent's
  ``remix_count`` a single time.
* **A non-cloned publish has a NULL parent** and never bumps anyone.
* **An unresolvable / unpublished parent is ignored silently** — the listing
  publishes as an original.
* **``lineage`` returns correct ancestors (depth-capped) + direct children.**
* **``most_remixed`` ordering is deterministic.**
* **The migration backfill populates a pre-existing clone's parent link.**
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import MarketplaceTemplate, User
from app.models.db.repositories import (
    MARKETPLACE_SORT_REMIXED,
    MarketplaceRepository,
    UserPresetRepository,
)
from app.services import marketplace as svc


# =========================================================================== #
# Fixtures / helpers
# =========================================================================== #
@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    with Factory() as s:
        yield s


def _user(session: Session, email: str) -> str:
    u = User(email=email, credits=0)
    session.add(u)
    session.flush()
    return u.id


def _publish_original(
    session: Session, author_id: str, **kwargs
) -> MarketplaceTemplate:
    """Publish an ORIGINAL (non-cloned) listing directly via the service."""
    defaults = dict(title="Original template", prompt="Write about {subject}")
    defaults.update(kwargs)
    row = svc.publish_from_template(session, author_id, **defaults)
    session.flush()
    return row


def _clone_then_publish(
    session: Session, cloner_id: str, source: MarketplaceTemplate, **kwargs
) -> MarketplaceTemplate:
    """Clone ``source`` into the cloner's presets, then re-publish that preset.

    Mirrors the real remix flow: clone_to_user writes a preset carrying
    ``source_marketplace_id``; publishing from that preset records the parent.
    """
    preset = svc.clone_to_user(session, cloner_id, source.id)
    session.flush()
    remix = svc.publish_from_template(session, cloner_id, preset.id, **kwargs)
    session.flush()
    return remix


# =========================================================================== #
# Publishing a clone sets parent + bumps remix_count exactly once
# =========================================================================== #
def test_publish_clone_sets_parent_and_bumps_remix_count_once(session: Session):
    author = _user(session, "author@example.com")
    cloner = _user(session, "cloner@example.com")

    parent = _publish_original(session, author)
    assert parent.parent_template_id is None
    assert parent.remix_count == 0

    remix = _clone_then_publish(session, cloner, parent)

    # The remix records its parent...
    assert remix.parent_template_id == parent.id
    # ...and the parent's remix_count is bumped EXACTLY once.
    session.refresh(parent)
    assert parent.remix_count == 1


def test_second_remix_bumps_parent_again(session: Session):
    author = _user(session, "author@example.com")
    a = _user(session, "a@example.com")
    b = _user(session, "b@example.com")

    parent = _publish_original(session, author)
    _clone_then_publish(session, a, parent)
    _clone_then_publish(session, b, parent)

    session.refresh(parent)
    assert parent.remix_count == 2
    # Exactly two published children descend from the parent.
    children = MarketplaceRepository(session).get_children(parent.id)
    assert len(children) == 2


def test_non_cloned_publish_has_null_parent(session: Session):
    author = _user(session, "author@example.com")
    listing = _publish_original(session, author)
    assert listing.parent_template_id is None
    assert listing.remix_count == 0


def test_unpublished_parent_is_ignored_silently(session: Session):
    """A clone whose source listing was unpublished publishes as an original."""
    author = _user(session, "author@example.com")
    cloner = _user(session, "cloner@example.com")

    parent = _publish_original(session, author)
    # Clone first (records source_marketplace_id in the preset)...
    preset = svc.clone_to_user(session, cloner, parent.id)
    session.flush()
    # ...then the author soft-unpublishes the source before the remix is published.
    assert MarketplaceRepository(session).unpublish(parent.id, author) is True

    remix = svc.publish_from_template(session, cloner, preset.id)
    session.flush()

    # The unpublished parent is ignored: no link, and no phantom remix_count bump.
    assert remix.parent_template_id is None
    session.refresh(parent)
    assert parent.remix_count == 0


def test_missing_parent_is_ignored_silently(session: Session):
    """A dangling source_marketplace_id (parent never existed) is ignored."""
    author = _user(session, "author@example.com")
    # A preset that claims provenance from a non-existent listing.
    preset = UserPresetRepository(session).create(
        user_id=author,
        name="Ghost remix",
        config={"source_marketplace_id": "does-not-exist", "prompt": "hi"},
    )
    session.flush()
    listing = svc.publish_from_template(session, author, preset.id)
    session.flush()
    assert listing.parent_template_id is None


# =========================================================================== #
# lineage(): ancestors (depth-capped) + direct children
# =========================================================================== #
def test_lineage_returns_ancestors_and_children(session: Session):
    u0 = _user(session, "u0@example.com")
    u1 = _user(session, "u1@example.com")
    u2 = _user(session, "u2@example.com")
    u3 = _user(session, "u3@example.com")

    gen0 = _publish_original(session, u0)
    gen1 = _clone_then_publish(session, u1, gen0)
    gen2 = _clone_then_publish(session, u2, gen1)
    # A sibling remix of gen1 so gen1 has two direct children.
    sibling = _clone_then_publish(session, u3, gen1)

    result = svc.lineage(session, gen2.id)
    ancestor_ids = [a.id for a in result["ancestors"]]
    # Immediate parent first, then up toward the root.
    assert ancestor_ids == [gen1.id, gen0.id]
    # gen2 has no children.
    assert result["children"] == []

    mid = svc.lineage(session, gen1.id)
    assert [a.id for a in mid["ancestors"]] == [gen0.id]
    child_ids = {c.id for c in mid["children"]}
    assert child_ids == {gen2.id, sibling.id}


def test_lineage_ancestors_depth_capped(session: Session, monkeypatch):
    """The ancestor walk stops at LINEAGE_MAX_DEPTH hops."""
    monkeypatch.setattr(svc, "LINEAGE_MAX_DEPTH", 2)

    u0 = _user(session, "u0@example.com")
    u1 = _user(session, "u1@example.com")
    u2 = _user(session, "u2@example.com")
    u3 = _user(session, "u3@example.com")

    gen0 = _publish_original(session, u0)
    gen1 = _clone_then_publish(session, u1, gen0)
    gen2 = _clone_then_publish(session, u2, gen1)
    gen3 = _clone_then_publish(session, u3, gen2)

    result = svc.lineage(session, gen3.id)
    # Capped at 2 hops: only the two nearest ancestors are walked.
    assert [a.id for a in result["ancestors"]] == [gen2.id, gen1.id]


def test_lineage_unknown_id_is_empty(session: Session):
    result = svc.lineage(session, "nope")
    assert result == {"ancestors": [], "children": []}


def test_lineage_children_exclude_unpublished(session: Session):
    author = _user(session, "author@example.com")
    cloner = _user(session, "cloner@example.com")

    parent = _publish_original(session, author)
    remix = _clone_then_publish(session, cloner, parent)
    # Soft-unpublish the remix — it must drop out of the public children list.
    assert MarketplaceRepository(session).unpublish(remix.id, cloner) is True

    result = svc.lineage(session, parent.id)
    assert result["children"] == []


# =========================================================================== #
# most_remixed ordering is deterministic
# =========================================================================== #
def test_most_remixed_sort_is_deterministic(session: Session):
    author = _user(session, "author@example.com")
    c1 = _user(session, "c1@example.com")
    c2 = _user(session, "c2@example.com")
    c3 = _user(session, "c3@example.com")

    hot = _publish_original(session, author, title="Hot")
    warm = _publish_original(session, author, title="Warm")
    cold = _publish_original(session, author, title="Cold")

    # hot: 2 remixes, warm: 1 remix, cold: 0.
    _clone_then_publish(session, c1, hot)
    _clone_then_publish(session, c2, hot)
    _clone_then_publish(session, c3, warm)

    listings = svc.browse(session, sort=MARKETPLACE_SORT_REMIXED, limit=100)
    by_id = {row.id: row for row in listings}
    # The three originals rank strictly by remix_count desc among themselves.
    order = [row.id for row in listings if row.id in {hot.id, warm.id, cold.id}]
    assert order == [hot.id, warm.id, cold.id]
    assert by_id[hot.id].remix_count == 2
    assert by_id[warm.id].remix_count == 1
    assert by_id[cold.id].remix_count == 0

    # Deterministic + stable: the same query yields the identical order twice.
    again = svc.browse(session, sort=MARKETPLACE_SORT_REMIXED, limit=100)
    assert [r.id for r in again] == [r.id for r in listings]


def test_most_remixed_tie_break_by_id(session: Session):
    """Equal remix_count (0) ties break deterministically (created_at, id)."""
    author = _user(session, "author@example.com")
    a = _publish_original(session, author, title="A")
    b = _publish_original(session, author, title="B")
    c = _publish_original(session, author, title="C")

    ids = [a.id, b.id, c.id]
    listings = svc.browse(session, sort=MARKETPLACE_SORT_REMIXED, limit=100)
    ranked = [r.id for r in listings if r.id in set(ids)]
    again = svc.browse(session, sort=MARKETPLACE_SORT_REMIXED, limit=100)
    ranked_again = [r.id for r in again if r.id in set(ids)]
    assert ranked == ranked_again  # stable across identical queries


# =========================================================================== #
# Migration backfill populates a pre-existing clone
# =========================================================================== #
def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "20260813_1230_c3d9b7e2f4a8_marketplace_remix_trees.py"
    )
    spec = importlib.util.spec_from_file_location("remix_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_backfill_populates_preexisting_clone(session: Session):
    """The migration's _backfill_parent_links reconstructs a clone's parent link.

    Simulates the pre-migration state (parent_template_id is NULL for a clone
    published before the feature) and drives the backfill via a bound op context.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    author = _user(session, "author@example.com")
    cloner = _user(session, "cloner@example.com")

    parent = _publish_original(session, author, title="Parent")
    # A clone published the "old" way: preset carries source_marketplace_id, and
    # the listing shares the preset's owner + name (title) but has a NULL parent.
    UserPresetRepository(session).create(
        user_id=cloner,
        name="Remixed",
        config={"source_marketplace_id": parent.id, "prompt": "x"},
    )
    child = MarketplaceRepository(session).publish(
        author_user_id=cloner,
        title="Remixed",  # == preset.name (seed_title copied at publish)
        prompt="x",
    )
    session.flush()
    assert child.parent_template_id is None  # pre-migration state

    module = _load_migration_module()

    # Bind alembic op to our SQLite connection so _backfill_parent_links (which
    # calls op.get_bind()) runs against this same in-memory database.
    conn = session.connection()
    ctx = MigrationContext.configure(conn)
    with Operations.context(Operations(ctx)):
        module._backfill_parent_links()

    session.expire_all()
    refreshed = MarketplaceRepository(session).get(child.id)
    assert refreshed.parent_template_id == parent.id
    # An original never gets a spurious parent.
    parent_row = MarketplaceRepository(session).get(parent.id)
    assert parent_row.parent_template_id is None
