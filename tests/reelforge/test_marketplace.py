"""Template Marketplace service/repository unit tests.

Complements the HTTP-level coverage in ``test_marketplace_api.py`` with direct
service + repository assertions, anchoring in particular the two behaviours the
adversarial review flagged and the fix landed:

* **Rating integrity** — one rating row per ``(template, user)`` (a re-rate
  updates in place), and ``rating_avg`` / ``rating_count`` are recomputed exactly
  from the child rows (:func:`app.services.marketplace.rate`,
  ``TemplateRatingRepository.upsert_rating``).
* **Input clamping on publish** — an oversized ``language`` / ``layout`` (e.g.
  carried in an opaque preset config) is truncated to its column limit before
  persistence (:func:`app.services.marketplace.publish_from_template`).

Plus the core repository guarantees: owner-scoped unpublish, snapshot
immutability, clone-creates-a-private-copy, and browse limit-clamp + sort.

No external I/O: an in-memory SQLite DB stands in for Postgres, mirroring
``test_marketplace_api.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import MarketplaceTemplate, TemplateRating, User
from app.models.db.repositories import (
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


def _publish(session: Session, author_id: str, **kwargs) -> MarketplaceTemplate:
    defaults = dict(
        author_user_id=author_id,
        title="A great template",
        description="does great things",
        prompt="Write about {subject}",
        params={"caption_style": "karaoke_yellow"},
        tags=["saas", "demo"],
        language="en",
        layout="split",
    )
    defaults.update(kwargs)
    row = MarketplaceRepository(session).publish(**defaults)
    session.flush()
    return row


# =========================================================================== #
# Rating integrity (adversarial fix #1)
# =========================================================================== #
def test_rate_upsert_dedupes_and_recomputes_aggregate(session: Session):
    author = _user(session, "author@example.com")
    rater_a = _user(session, "a@example.com")
    rater_b = _user(session, "b@example.com")
    listing = _publish(session, author)

    # First rating: count 1, avg 5.0.
    svc.rate(session, rater_a, listing.id, 5)
    session.flush()
    assert listing.rating_count == 1
    assert listing.rating_avg == pytest.approx(5.0)
    assert session.query(TemplateRating).count() == 1

    # Same user re-rates: NO new row, avg reflects the new value.
    svc.rate(session, rater_a, listing.id, 3)
    session.flush()
    assert listing.rating_count == 1
    assert listing.rating_avg == pytest.approx(3.0)
    assert session.query(TemplateRating).count() == 1

    # A second distinct user rates: count 2, avg is the mean of both rows.
    svc.rate(session, rater_b, listing.id, 5)
    session.flush()
    assert listing.rating_count == 2
    assert listing.rating_avg == pytest.approx(4.0)
    assert session.query(TemplateRating).count() == 2


@pytest.mark.parametrize("bad", [0, -1, 6, 99])
def test_rate_rejects_out_of_range_stars(session: Session, bad: int):
    author = _user(session, "author@example.com")
    rater = _user(session, "r@example.com")
    listing = _publish(session, author)
    with pytest.raises(ValueError):
        svc.rate(session, rater, listing.id, bad)


# =========================================================================== #
# Publish input clamping (adversarial fix #2)
# =========================================================================== #
def test_publish_truncates_oversized_language_and_layout(session: Session):
    author = _user(session, "author@example.com")
    listing = svc.publish_from_template(
        session,
        author,
        title="Oversized",
        language="x" * 100,
        layout="y" * 100,
    )
    session.flush()
    # language is truncated to 20, layout to 40 (matching the column limits).
    assert len(listing.language) <= 20
    assert len(listing.layout) <= 40


def test_publish_via_preset_config_truncates_oversized_fields(session: Session):
    """The oversized value can arrive through an opaque preset config, too."""
    author = _user(session, "author@example.com")
    preset = UserPresetRepository(session).create(
        user_id=author,
        name="Kit",
        config={"language": "z" * 80, "layout": "w" * 80},
    )
    session.flush()
    listing = svc.publish_from_template(session, author, preset.id)
    session.flush()
    assert len(listing.language) <= 20
    assert len(listing.layout) <= 40


# =========================================================================== #
# Snapshot immutability
# =========================================================================== #
def test_publish_snapshots_immutably_from_preset(session: Session):
    author = _user(session, "author@example.com")
    preset = UserPresetRepository(session).create(
        user_id=author,
        name="Kit",
        config={"prompt": "original", "params": {"a": 1}, "tags": ["one"]},
    )
    session.flush()
    listing = svc.publish_from_template(session, author, preset.id)
    session.flush()
    assert listing.prompt == "original"

    # Mutating the source preset config must NOT change the published listing.
    preset.config = {"prompt": "changed", "params": {"a": 999}, "tags": ["two"]}
    session.flush()
    session.refresh(listing)
    assert listing.prompt == "original"
    assert listing.params == {"a": 1}


def test_publish_foreign_preset_is_rejected(session: Session):
    author = _user(session, "author@example.com")
    stranger = _user(session, "stranger@example.com")
    preset = UserPresetRepository(session).create(
        user_id=author, name="Kit", config={}
    )
    session.flush()
    # A different user cannot publish from someone else's preset.
    with pytest.raises(ValueError):
        svc.publish_from_template(session, stranger, preset.id)


# =========================================================================== #
# Owner-scoped unpublish
# =========================================================================== #
def test_unpublish_is_owner_scoped(session: Session):
    author = _user(session, "author@example.com")
    stranger = _user(session, "stranger@example.com")
    listing = _publish(session, author)
    repo = MarketplaceRepository(session)

    # A non-author cannot unpublish; the row stays published.
    assert repo.unpublish(listing.id, stranger) is False
    session.flush()
    session.refresh(listing)
    assert listing.published is True

    # The author can; a second unpublish is a harmless no-op.
    assert repo.unpublish(listing.id, author) is True
    session.flush()
    session.refresh(listing)
    assert listing.published is False
    assert repo.unpublish(listing.id, author) is False


# =========================================================================== #
# Clone
# =========================================================================== #
def test_clone_creates_private_preset_and_increments_count(session: Session):
    author = _user(session, "author@example.com")
    cloner = _user(session, "cloner@example.com")
    listing = _publish(session, author)

    preset = svc.clone_to_user(session, cloner, listing.id)
    session.flush()

    assert preset.user_id == cloner
    assert preset.config.get("source_marketplace_id") == listing.id
    assert preset.config.get("prompt") == listing.prompt
    session.refresh(listing)
    assert listing.clone_count == 1


def test_clone_unpublished_listing_is_rejected(session: Session):
    author = _user(session, "author@example.com")
    cloner = _user(session, "cloner@example.com")
    listing = _publish(session, author, published=False)
    with pytest.raises(ValueError):
        svc.clone_to_user(session, cloner, listing.id)


# =========================================================================== #
# Browse — clamp + sort
# =========================================================================== #
def test_browse_clamps_limit_and_returns_published_only(session: Session):
    author = _user(session, "author@example.com")
    for i in range(5):
        _publish(session, author, title=f"pub-{i}")
    _publish(session, author, title="hidden", published=False)
    session.flush()

    # An absurd limit is clamped and never raises; unpublished rows are excluded.
    rows = svc.browse(session, limit=10_000)
    assert all(r.published for r in rows)
    assert len(rows) == 5


def test_browse_default_sort_orders_by_rating_desc(session: Session):
    author = _user(session, "author@example.com")
    low = _publish(session, author, title="low")
    high = _publish(session, author, title="high")
    session.flush()

    # Give `high` a better rating than `low`.
    svc.rate(session, _user(session, "r1@example.com"), high.id, 5)
    svc.rate(session, _user(session, "r2@example.com"), low.id, 2)
    session.flush()

    rows = svc.browse(session, sort=svc.DEFAULT_SORT)
    ids = [r.id for r in rows]
    assert ids.index(high.id) < ids.index(low.id)
