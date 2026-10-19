"""Marketplace "proven" win-score ranking — service unit tests.

Feature 3 ranks marketplace listings by the REAL-WORLD performance of the reels
made from their clones, computed entirely at query time (no new table):

* A listing is cloned into a private :class:`UserPreset` whose ``config`` records
  the source listing under ``source_marketplace_id``.
* A reel (:class:`Job`) rendered from that clone carries the same
  ``source_marketplace_id`` in its ``params``, and the creator logs the reel's
  outcome as a :class:`JobPerformance` row.
* :func:`marketplace.listing_win_scores` folds every downstream reel of a listing
  into one win-score using the SAME formula as the Hook Performance Loop
  (:class:`app.services.hook_performance._Group`), and
  :func:`marketplace.proven_ranking` orders proven listings first (best score
  first), with a deterministic ``rating_avg`` fallback for listings that have no
  performance data yet.

These tests anchor: (1) a listing with better downstream reels ranks ahead of a
weaker one under ``sort='proven'``; (2) a listing with zero downstream reels
falls back to rating and never raises / never yields ``NaN``; (3) the score is
literally the Hook-Performance formula (asserted by comparison AND monkeypatch),
never a re-derived copy.

No external I/O: an in-memory SQLite DB stands in for Postgres, mirroring
``test_marketplace.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import Job, JobPerformance, MarketplaceTemplate, User
from app.models.db.repositories import (
    MARKETPLACE_SORT_PROVEN,
    MarketplaceRepository,
)
from app.services import hook_performance
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
    user = User(email=email, credits=0)
    session.add(user)
    session.flush()
    return user.id


def _publish(
    session: Session, author_id: str, *, title: str, rating_avg: float = 0.0
) -> MarketplaceTemplate:
    row = MarketplaceRepository(session).publish(
        author_user_id=author_id,
        title=title,
        description="d",
        prompt="p",
        params={},
        tags=[],
        language="en",
        layout="split",
    )
    row.rating_avg = rating_avg
    session.flush()
    return row


def _clone(session: Session, user_id: str, listing: MarketplaceTemplate):
    """Clone ``listing`` into ``user_id``'s private presets (stamps provenance)."""
    return svc.clone_to_user(session, user_id, listing.id)


def _reel_with_outcome(
    session: Session,
    user_id: str,
    listing_id: str,
    metrics: dict,
) -> JobPerformance:
    """Render a reel from a listing's clone and log its real-world outcome.

    The job carries the listing's provenance stamp in its params (as a real reel
    rendered from the cloned preset would), then a :class:`JobPerformance` row is
    logged via the owner-verifying service so ownership matches production.
    """
    job = Job(
        user_id=user_id,
        params={svc.SOURCE_MARKETPLACE_KEY: listing_id, "video_subject": "hi"},
    )
    session.add(job)
    session.flush()
    return hook_performance.log_performance(session, user_id, job.id, metrics)


# =========================================================================== #
# 1. Proven ordering: better downstream reels rank first
# =========================================================================== #
def test_proven_sort_orders_higher_winscore_first(session: Session):
    author = _user(session, "author@example.com")
    creator = _user(session, "creator@example.com")

    # Listing A gets strong reels; listing B weak reels. Both are published.
    listing_a = _publish(session, author, title="A", rating_avg=1.0)
    listing_b = _publish(session, author, title="B", rating_avg=5.0)

    _clone(session, creator, listing_a)
    _clone(session, creator, listing_b)

    # A: high engagement + high retention -> high win-score.
    _reel_with_outcome(
        session, creator, listing_a.id,
        {"views": 1000, "likes": 500, "shares": 200, "retention_pct": 90.0},
    )
    # B: weak engagement + low retention -> low win-score.
    _reel_with_outcome(
        session, creator, listing_b.id,
        {"views": 1000, "likes": 5, "retention_pct": 5.0},
    )
    session.flush()

    scores = svc.listing_win_scores(session, [listing_a.id, listing_b.id])
    assert scores[listing_a.id] > scores[listing_b.id]

    # Even though B has the higher rating_avg (5.0 vs 1.0), 'proven' puts A first
    # because A's reels genuinely convert better.
    ranked = svc.browse(session, sort=MARKETPLACE_SORT_PROVEN)
    order = [row.id for row in ranked]
    assert order.index(listing_a.id) < order.index(listing_b.id)

    # 'proven' is a recognized sort value on the service too.
    assert svc.PROVEN_SORT == "proven" == MARKETPLACE_SORT_PROVEN


def test_proven_ranking_direct_orders_proven_before_unproven(session: Session):
    author = _user(session, "author2@example.com")
    creator = _user(session, "creator2@example.com")

    proven = _publish(session, author, title="proven", rating_avg=1.0)
    unproven = _publish(session, author, title="unproven", rating_avg=4.9)

    _clone(session, creator, proven)
    _reel_with_outcome(
        session, creator, proven.id,
        {"views": 100, "likes": 60, "retention_pct": 80.0},
    )
    session.flush()

    # unproven has a far better rating, but a proven listing (any downstream
    # data) always ranks ahead under 'proven'.
    ranked = svc.proven_ranking(session, [unproven, proven])
    assert [row.id for row in ranked] == [proven.id, unproven.id]


# =========================================================================== #
# 2. Fallback: zero downstream reels -> rating, never errors / NaN
# =========================================================================== #
def test_listing_with_no_reels_falls_back_to_rating(session: Session):
    author = _user(session, "author3@example.com")

    high_rated = _publish(session, author, title="high", rating_avg=4.5)
    low_rated = _publish(session, author, title="low", rating_avg=2.0)

    # No clones, no reels, no performance rows at all.
    scores = svc.listing_win_scores(session, [high_rated.id, low_rated.id])
    assert scores == {}  # absent, not a 0/NaN entry

    ranked = svc.proven_ranking(session, [low_rated, high_rated])
    order = [row.id for row in ranked]
    assert order == [high_rated.id, low_rated.id]  # pure rating_avg fallback
    # Sanity: no NaN leaked into any score.
    for value in scores.values():
        assert value == value  # NaN != NaN


def test_empty_and_blank_inputs_are_safe(session: Session):
    assert svc.listing_win_scores(session, []) == {}
    assert svc.listing_win_scores(session, ["", "  "]) == {}
    assert svc.proven_ranking(session, []) == []


def test_unknown_sort_falls_back_and_does_not_crash(session: Session):
    author = _user(session, "author4@example.com")
    _publish(session, author, title="only", rating_avg=3.0)
    session.flush()
    # An unrecognized sort must not raise and must still return listings.
    rows = svc.browse(session, sort="totally-bogus")
    assert len(rows) == 1


# =========================================================================== #
# 3. Formula reuse: the win-score IS the Hook-Performance formula
# =========================================================================== #
def test_win_score_matches_hook_performance_formula(session: Session):
    author = _user(session, "author5@example.com")
    creator = _user(session, "creator5@example.com")
    listing = _publish(session, author, title="L")
    _clone(session, creator, listing)

    perfs = [
        _reel_with_outcome(
            session, creator, listing.id,
            {"views": 400, "likes": 120, "comments": 30, "retention_pct": 70.0},
        ),
        _reel_with_outcome(
            session, creator, listing.id,
            {"views": 600, "likes": 200, "shares": 40, "retention_pct": 55.0},
        ),
    ]
    session.flush()

    # Independently fold the SAME rows through the Hook-Performance group and
    # assert the service returns exactly that score (no re-derived math).
    expected_group = hook_performance._Group()
    for perf in perfs:
        expected_group.add(perf)
    expected = expected_group.win_score()

    scores = svc.listing_win_scores(session, [listing.id])
    assert scores[listing.id] == pytest.approx(expected)


def test_win_score_delegates_to_hook_performance_group(
    session: Session, monkeypatch: pytest.MonkeyPatch
):
    """Monkeypatching the Hook-Performance group's scorer changes the marketplace
    score too — proving the marketplace does not carry its own copy of the
    formula."""
    author = _user(session, "author6@example.com")
    creator = _user(session, "creator6@example.com")
    listing = _publish(session, author, title="L")
    _clone(session, creator, listing)
    _reel_with_outcome(
        session, creator, listing.id,
        {"views": 100, "likes": 50, "retention_pct": 50.0},
    )
    session.flush()

    sentinel = 42.4242
    monkeypatch.setattr(
        hook_performance._Group, "win_score", lambda self: sentinel
    )
    scores = svc.listing_win_scores(session, [listing.id])
    assert scores[listing.id] == sentinel


# =========================================================================== #
# 4. Provenance is strictly per-user (anti-spoof)
# =========================================================================== #
def test_spoofed_provenance_without_clone_is_ignored(session: Session):
    author = _user(session, "author7@example.com")
    honest = _user(session, "honest@example.com")
    spoofer = _user(session, "spoofer@example.com")
    listing = _publish(session, author, title="L")

    # Only `honest` actually cloned the listing.
    _clone(session, honest, listing)
    _reel_with_outcome(
        session, honest, listing.id,
        {"views": 100, "likes": 40, "retention_pct": 60.0},
    )
    # `spoofer` never cloned it but stamps the provenance id into their job.
    _reel_with_outcome(
        session, spoofer, listing.id,
        {"views": 100, "likes": 100, "retention_pct": 100.0},
    )
    session.flush()

    # Score reflects ONLY the honest cloner's reel.
    honest_only = hook_performance._Group()
    honest_only.add(
        session.query(JobPerformance).filter_by(user_id=honest).one()
    )
    scores = svc.listing_win_scores(session, [listing.id])
    assert scores[listing.id] == pytest.approx(honest_only.win_score())
