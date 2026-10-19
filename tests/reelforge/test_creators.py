"""Creator Profiles + Follow Graph + Leaderboards — service + repository tests.

Runs entirely against an in-memory SQLite engine (no Postgres/Neon required),
mirroring ``test_share.py`` / ``test_marketplace.py``. Anchors the hard security +
behavior requirements of the feature:

* **Idempotent follow** — a double-follow creates exactly one edge.
* **No self-follow** — a user can never follow themselves.
* **Unfollow removes exactly one edge** — and is a no-op when absent.
* **Safe public profile** — ``public_profile`` returns ONLY the safe field set and
  NEVER credits / email / cost / revenue or any private datum.
* **Deterministic + clamped + safe leaderboard** — a stable ordering, a bounded
  page size, and no private-field leakage; the win-score reputation anchor is
  gated by a self-clone-gaming cohort floor.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import CreatorFollow, Job, MarketplaceTemplate, User
from app.models.db.repositories import (
    CreatorFollowRepository,
    MarketplaceRepository,
)
from app.services import creators as svc
from app.services import hook_performance, marketplace


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


def _user(
    session: Session,
    email: str,
    *,
    handle: str | None = None,
    display_name: str = "",
    bio: str | None = None,
    credits: int = 999,
) -> str:
    u = User(
        email=email,
        handle=handle,
        display_name=display_name,
        bio=bio,
        credits=credits,
    )
    session.add(u)
    session.flush()
    return u.id


def _publish(
    session: Session,
    author_id: str,
    *,
    title: str = "Kit",
    clone_count: int = 0,
    rating_avg: float = 0.0,
    rating_count: int = 0,
    published: bool = True,
) -> MarketplaceTemplate:
    listing = MarketplaceRepository(session).publish(
        author_user_id=author_id, title=title, published=published
    )
    listing.clone_count = clone_count
    listing.rating_avg = rating_avg
    listing.rating_count = rating_count
    session.flush()
    return listing


def _job(session: Session, user_id: str, source_marketplace_id: str) -> Job:
    job = Job(
        user_id=user_id,
        kind="avatar_reel",
        state=1,
        params={"source_marketplace_id": source_marketplace_id},
        stages={},
    )
    session.add(job)
    session.flush()
    return job


def _clone_and_log(session: Session, listing_id: str, cloner_id: str) -> None:
    """Clone a listing to ``cloner_id`` and log a strong reel outcome for it.

    Drives the full marketplace provenance chain the leaderboard win-score reads:
    UserPreset(source_marketplace_id) -> Job(params.source_marketplace_id) ->
    JobPerformance.
    """
    marketplace.clone_to_user(session, cloner_id, listing_id)
    job = _job(session, cloner_id, listing_id)
    hook_performance.log_performance(
        session,
        cloner_id,
        job.id,
        {"views": 100, "likes": 60, "comments": 20, "retention_pct": 90},
    )


# =========================================================================== #
# Follow graph — idempotent, no self-follow, unfollow removes one
# =========================================================================== #
def test_follow_is_idempotent(session: Session):
    a = _user(session, "a@example.com")
    b = _user(session, "b@example.com")

    first = svc.follow(session, a, b)
    second = svc.follow(session, a, b)  # double-follow

    assert first["following"] is True
    assert second["following"] is True
    # Exactly ONE edge exists despite following twice.
    edges = session.query(CreatorFollow).filter_by(
        follower_user_id=a, followee_user_id=b
    ).count()
    assert edges == 1
    assert second["follower_count"] == 1


def test_cannot_self_follow(session: Session):
    a = _user(session, "a@example.com")
    with pytest.raises(ValueError):
        svc.follow(session, a, a)
    # Repository enforces it too (defense in depth).
    with pytest.raises(ValueError):
        CreatorFollowRepository(session).follow(a, a)
    assert session.query(CreatorFollow).count() == 0


def test_follow_unknown_followee_raises(session: Session):
    a = _user(session, "a@example.com")
    with pytest.raises(LookupError):
        svc.follow(session, a, "does-not-exist")
    assert session.query(CreatorFollow).count() == 0


def test_follow_validates_inputs(session: Session):
    a = _user(session, "a@example.com")
    with pytest.raises(ValueError):
        svc.follow(session, "", a)
    with pytest.raises(ValueError):
        svc.follow(session, a, "")


def test_unfollow_removes_exactly_one_edge(session: Session):
    a = _user(session, "a@example.com")
    b = _user(session, "b@example.com")
    c = _user(session, "c@example.com")

    svc.follow(session, a, b)
    svc.follow(session, c, b)  # an unrelated follower of b
    assert CreatorFollowRepository(session).follower_count(b) == 2

    result = svc.unfollow(session, a, b)
    assert result["removed"] is True
    assert result["following"] is False
    # Only a's edge was removed; c still follows b.
    assert CreatorFollowRepository(session).follower_count(b) == 1
    assert CreatorFollowRepository(session).is_following(c, b) is True
    assert CreatorFollowRepository(session).is_following(a, b) is False


def test_unfollow_absent_edge_is_noop(session: Session):
    a = _user(session, "a@example.com")
    b = _user(session, "b@example.com")
    result = svc.unfollow(session, a, b)
    assert result["removed"] is False
    assert result["follower_count"] == 0


# =========================================================================== #
# Public profile — SAFE fields only
# =========================================================================== #
def test_public_profile_returns_only_safe_fields(session: Session):
    author = _user(
        session,
        "creator@example.com",
        handle="viralvin",
        display_name="Vin the Creator",
        bio="I make bangers",
        credits=50_000,
    )
    fan = _user(session, "fan@example.com")

    # Two published listings drive the aggregates: weighted avg rating
    # = (5*1 + 1*3) / (1 + 3) = 2.0; total clones = 4 + 6 = 10; count = 2.
    _publish(session, author, title="A", clone_count=4, rating_avg=5.0, rating_count=1)
    _publish(session, author, title="B", clone_count=6, rating_avg=1.0, rating_count=3)
    svc.follow(session, fan, author)

    dto = svc.public_profile(session, author)

    # EXACT safe field set — nothing more, nothing less.
    assert set(dto.keys()) == set(svc.SAFE_PROFILE_FIELDS)
    assert dto["handle"] == "viralvin"
    assert dto["display_name"] == "Vin the Creator"
    assert dto["bio"] == "I make bangers"
    assert dto["published_template_count"] == 2
    assert dto["total_clones_received"] == 10
    assert dto["avg_rating"] == 2.0
    assert dto["follower_count"] == 1
    assert dto["following_count"] == 0

    # Hard security assertions: no private/financial datum anywhere in the DTO.
    serialized = repr(dto)
    assert "creator@example.com" not in serialized
    for banned in ("credits", "email", "cost", "revenue", "50000", "50_000"):
        assert banned not in serialized
    for banned_key in ("credits", "email", "cost_usd", "user_id"):
        assert banned_key not in dto


def test_public_profile_resolves_by_handle(session: Session):
    author = _user(session, "creator@example.com", handle="SlugKing")
    _publish(session, author, title="A")

    by_id = svc.public_profile(session, author)
    by_handle = svc.public_profile(session, "slugking")  # case-insensitive

    assert by_id == by_handle
    assert by_handle["handle"] == "SlugKing"


def test_public_profile_unknown_raises(session: Session):
    with pytest.raises(ValueError):
        svc.public_profile(session, "")
    with pytest.raises(LookupError):
        svc.public_profile(session, "nobody")


def test_public_profile_unpublished_listings_excluded(session: Session):
    author = _user(session, "creator@example.com")
    _publish(session, author, title="live", clone_count=3)
    _publish(session, author, title="hidden", clone_count=99, published=False)

    dto = svc.public_profile(session, author)
    # Only the published listing counts toward public reputation.
    assert dto["published_template_count"] == 1
    assert dto["total_clones_received"] == 3


# =========================================================================== #
# Leaderboard — deterministic, clamped, safe
# =========================================================================== #
def test_leaderboard_is_deterministic_and_clamped(session: Session):
    # Three creators with strictly different published-count reputations.
    top = _user(session, "top@example.com", handle="top")
    mid = _user(session, "mid@example.com", handle="mid")
    low = _user(session, "low@example.com", handle="low")
    for _ in range(3):
        _publish(session, top)
    for _ in range(2):
        _publish(session, mid)
    _publish(session, low)

    board = svc.leaderboard(session, metric="published")
    assert [e["user_id"] for e in board] == [top, mid, low]
    assert [e["rank"] for e in board] == [1, 2, 3]
    # Ranking is stable across repeated calls.
    assert svc.leaderboard(session, metric="published") == board

    # Clamp: a huge limit returns only what exists; a tiny/garbage limit is clamped.
    assert len(svc.leaderboard(session, metric="published", limit=999)) == 3
    assert len(svc.leaderboard(session, metric="published", limit=1)) == 1
    assert len(svc.leaderboard(session, metric="published", limit=0)) == 1


def test_leaderboard_tie_break_is_by_user_id(session: Session):
    # Two creators with identical reputations -> deterministic user_id tie-break.
    a = _user(session, "a@example.com")
    b = _user(session, "b@example.com")
    _publish(session, a)
    _publish(session, b)

    board = svc.leaderboard(session, metric="published")
    ordered_ids = [e["user_id"] for e in board]
    assert ordered_ids == sorted([a, b])  # ascending user_id tie-break


def test_leaderboard_metric_selectors(session: Session):
    author = _user(session, "author@example.com")
    follower_star = _user(session, "star@example.com")

    _publish(session, author, clone_count=100)
    # Give follower_star three followers but no published listings.
    for i in range(3):
        fan = _user(session, f"fan{i}@example.com")
        svc.follow(session, fan, follower_star)

    # "followers" ranks the followed-but-unpublished creator first.
    by_followers = svc.leaderboard(session, metric="followers")
    assert by_followers[0]["user_id"] == follower_star
    assert by_followers[0]["follower_count"] == 3

    # "clones" ranks the heavily-cloned author first.
    by_clones = svc.leaderboard(session, metric="clones")
    assert by_clones[0]["user_id"] == author
    assert by_clones[0]["total_clones_received"] == 100

    # An unknown metric falls back to the composite reputation ranking.
    assert svc.leaderboard(session, metric="bogus") == svc.leaderboard(
        session, metric="reputation"
    )


def test_leaderboard_does_not_leak_private_fields(session: Session):
    a = _user(session, "secret@example.com", handle="a", credits=123456)
    _publish(session, a, clone_count=5, rating_avg=4.0, rating_count=2)

    board = svc.leaderboard(session)
    serialized = repr(board)
    assert "secret@example.com" not in serialized
    for banned in ("credits", "email", "cost", "revenue", "123456"):
        assert banned not in serialized
    for entry in board:
        for banned_key in ("credits", "email", "cost_usd"):
            assert banned_key not in entry


def test_leaderboard_empty_when_no_candidates(session: Session):
    _user(session, "lurker@example.com")  # no listings, no followers
    assert svc.leaderboard(session) == []


# =========================================================================== #
# Leaderboard win-score — reputation anchor + self-clone-gaming guard
# =========================================================================== #
def test_winscore_requires_cohort_floor(session: Session):
    """A single (self-)cloner never manufactures a win-score (gaming guard)."""
    author = _user(session, "author@example.com")
    listing = _publish(session, author)

    # Only ONE distinct downstream cloner -> below the cohort floor (2).
    solo = _user(session, "solo@example.com")
    _clone_and_log(session, listing.id, solo)

    board = svc.leaderboard(session, metric="reputation")
    entry = next(e for e in board if e["user_id"] == author)
    assert entry["win_score"] == 0.0


def test_winscore_counts_with_enough_distinct_cloners(session: Session):
    """Two distinct downstream cloners clear the floor -> win-score contributes."""
    author = _user(session, "author@example.com")
    listing = _publish(session, author)

    for who in ("b@example.com", "c@example.com"):
        _clone_and_log(session, listing.id, _user(session, who))

    board = svc.leaderboard(session, metric="win_score")
    entry = next(e for e in board if e["user_id"] == author)
    assert entry["win_score"] > 0.0
    # The win-score lifts the reputation above its base (published-only) value.
    base_only = svc.REP_W_PUBLISHED * entry["published_template_count"]
    assert entry["reputation_score"] > base_only
