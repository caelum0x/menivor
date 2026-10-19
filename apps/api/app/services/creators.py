"""Creator Profiles + Follow Graph + Leaderboards.

Public creator identity layered on top of the existing per-user data. Three
capabilities, all exposing ONLY safe public fields (never credits / email / cost /
revenue or any other private/financial datum):

* **Public profile** (:func:`public_profile`) — a creator's public identity
  (handle / display_name / bio) plus their PUBLIC reputation aggregates
  (published templates, clones received, weighted average marketplace rating,
  follower/following counts). Addressable by ``user_id`` *or* ``handle``.
* **Follow graph** (:func:`follow` / :func:`unfollow`) — an idempotent, directed
  follow edge. A user can never follow themselves; a double-follow is a no-op; an
  unfollow removes exactly one edge.
* **Leaderboard** (:func:`leaderboard`) — creators ranked by a documented,
  deterministic reputation score (or a single chosen metric), clamped to a bounded
  page size, exposing only safe fields.

A thin, validation + aggregation layer over
:class:`~app.models.db.repositories.CreatorFollowRepository` and
:class:`~app.models.db.repositories.MarketplaceRepository`, mirroring
:mod:`app.services.marketplace` and :mod:`app.services.share`.

Reputation score (deterministic)
--------------------------------
For a creator, the composite reputation score is a pure, documented function of
four PUBLIC signals::

    reputation =
          REP_W_PUBLISHED * published_template_count
        + REP_W_CLONES    * total_clones_received
        + REP_W_RATING    * avg_rating           # rating-count-weighted, in [0, 5]
        + REP_W_FOLLOWERS * follower_count
        + REP_W_WINSCORE  * downstream_win_score  # in [0, 100]

Ties are broken by ``user_id`` so the ranking is fully deterministic.

Self-clone / gaming guard
-------------------------
The gaming-resistant ANCHOR of the score is ``downstream_win_score``: it is
sourced from :func:`app.services.marketplace.listing_win_scores`, which is
STRICTLY per-user provenance (a reel only counts toward a listing when the reel's
OWNER genuinely cloned that listing, defeating spoofed ``source_marketplace_id``
job params) AND applies a k-anonymity cohort floor
(:data:`LEADERBOARD_WINSCORE_MIN_COHORT` = 2 DISTINCT downstream cloners) so a
lone creator cloning THEIR OWN listing and logging fake metrics can never
manufacture a win score. The weaker denormalized signals (clones, rating) are
weighted modestly relative to that anchor, and each marketplace rating is one row
per distinct ``(template, user)`` — so a single actor cannot inflate a rating
either.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db.models import User
from app.models.db.repositories import (
    CreatorFollowRepository,
    MarketplaceRepository,
)
from app.services import marketplace as marketplace_svc

# --------------------------------------------------------------------------- #
# Safe public field contracts
# --------------------------------------------------------------------------- #
#: The EXACT set of keys the public profile DTO exposes. Every one is safe to
#: serve publicly; credits, email, cost/revenue and every other private field are
#: deliberately absent.
SAFE_PROFILE_FIELDS: tuple[str, ...] = (
    "handle",
    "display_name",
    "bio",
    "published_template_count",
    "total_clones_received",
    "avg_rating",
    "follower_count",
    "following_count",
)

# --------------------------------------------------------------------------- #
# Reputation-score tunables (documented, deterministic)
# --------------------------------------------------------------------------- #
REP_W_PUBLISHED: float = 1.0
REP_W_CLONES: float = 2.0
#: ``avg_rating`` lands in ``[0, 5]``; weight 8 maps a perfect-rated catalog to a
#: strong 40-point contribution.
REP_W_RATING: float = 8.0
REP_W_FOLLOWERS: float = 1.5
#: ``downstream_win_score`` lands in ``[0, 100]``; weight 0.5 maps a perfect
#: win-score to a strong 50-point contribution (the reputation anchor).
REP_W_WINSCORE: float = 0.5

#: Decimal places emitted scores / averages are rounded to (keeps values
#: deterministic and JSON-clean across SQLite/Postgres).
SCORE_ROUND: int = 4
RATING_ROUND: int = 2

#: k-anonymity floor for a listing's win score to count toward reputation — the
#: self-clone / gaming guard (see module docstring). Reuses the marketplace's
#: public floor so the whole feature shares one source of truth.
LEADERBOARD_WINSCORE_MIN_COHORT: int = marketplace_svc.WIN_SCORE_PUBLIC_MIN_COHORT

#: Hard cap on how many listing win-scores a single leaderboard build will
#: resolve, so ranking can never trigger an unbounded provenance scan. The top
#: candidates (by base score) are scored first; listings beyond the cap simply
#: contribute a 0 win-score to their author.
LEADERBOARD_WINSCORE_MAX_LISTINGS: int = marketplace_svc.MAX_LIMIT

# --------------------------------------------------------------------------- #
# Leaderboard metric selectors + page bounds
# --------------------------------------------------------------------------- #
METRIC_REPUTATION: str = "reputation"
METRIC_FOLLOWERS: str = "followers"
METRIC_CLONES: str = "clones"
METRIC_RATING: str = "rating"
METRIC_PUBLISHED: str = "published"
METRIC_WINSCORE: str = "win_score"
LEADERBOARD_METRICS: frozenset[str] = frozenset(
    {
        METRIC_REPUTATION,
        METRIC_FOLLOWERS,
        METRIC_CLONES,
        METRIC_RATING,
        METRIC_PUBLISHED,
        METRIC_WINSCORE,
    }
)
DEFAULT_METRIC: str = METRIC_REPUTATION

LEADERBOARD_MIN_LIMIT: int = 1
LEADERBOARD_MAX_LIMIT: int = 100
LEADERBOARD_DEFAULT_LIMIT: int = 20

#: Max length of a free-text bio surfaced publicly (defensive truncation).
_MAX_BIO_LEN: int = 2000


# --------------------------------------------------------------------------- #
# Clamping / normalization helpers
# --------------------------------------------------------------------------- #
def _clamp_limit(limit: int | None) -> int:
    """Clamp a requested leaderboard size into ``[1, 100]`` (default on garbage)."""
    try:
        value = int(limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return LEADERBOARD_DEFAULT_LIMIT
    return max(LEADERBOARD_MIN_LIMIT, min(value, LEADERBOARD_MAX_LIMIT))


def _normalize_metric(metric: str | None) -> str:
    """Return a recognized metric key, defaulting to ``reputation`` on garbage."""
    normalized = (metric or "").strip().lower()
    return normalized if normalized in LEADERBOARD_METRICS else DEFAULT_METRIC


# --------------------------------------------------------------------------- #
# User resolution (by id OR handle)
# --------------------------------------------------------------------------- #
def _resolve_user(session: Session, user_id_or_handle: str) -> User | None:
    """Resolve a user by primary-key id, else by public ``handle``.

    Tries the id path first (the canonical addressing key), then a
    case-insensitive ``handle`` match. A blank input never matches (returns
    ``None``).
    """
    normalized = (user_id_or_handle or "").strip()
    if not normalized:
        return None
    user = session.get(User, normalized)
    if user is not None:
        return user
    stmt = (
        select(User)
        .where(func.lower(User.handle) == normalized.lower())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


# --------------------------------------------------------------------------- #
# Public profile
# --------------------------------------------------------------------------- #
def public_profile(session: Session, user_id_or_handle: str) -> dict[str, Any]:
    """Return a creator's SAFE public profile DTO.

    Addressable by ``user_id`` OR public ``handle``. The returned dict contains
    EXACTLY :data:`SAFE_PROFILE_FIELDS` — the creator's public identity (handle,
    display_name, bio) and their PUBLIC reputation aggregates (published templates,
    clones received, weighted average marketplace rating, follower/following
    counts). It NEVER exposes credits, email, cost/revenue or any other private
    field.

    Args:
        session: An active SQLAlchemy session (read-only; not committed here).
        user_id_or_handle: The creator's id or public handle.

    Returns:
        ``{handle, display_name, bio, published_template_count,
        total_clones_received, avg_rating, follower_count, following_count}``.

    Raises:
        ValueError: If ``user_id_or_handle`` is blank.
        LookupError: If no such creator exists.
    """
    if not user_id_or_handle or not str(user_id_or_handle).strip():
        raise ValueError("user_id_or_handle is required")

    user = _resolve_user(session, user_id_or_handle)
    if user is None:
        raise LookupError("creator not found")

    aggregates = MarketplaceRepository(session).author_aggregates(user.id)
    follows = CreatorFollowRepository(session)
    return {
        "handle": user.handle or "",
        "display_name": user.display_name or "",
        "bio": (user.bio or "")[:_MAX_BIO_LEN],
        "published_template_count": int(aggregates["published_template_count"]),
        "total_clones_received": int(aggregates["total_clones_received"]),
        "avg_rating": round(float(aggregates["avg_rating"]), RATING_ROUND),
        "follower_count": follows.follower_count(user.id),
        "following_count": follows.following_count(user.id),
    }


# --------------------------------------------------------------------------- #
# Follow graph
# --------------------------------------------------------------------------- #
def follow(session: Session, follower_id: str, followee_id: str) -> dict[str, Any]:
    """Idempotently follow another creator; return a small result envelope.

    A user CANNOT follow themselves (raises ``ValueError``). Following a creator
    already followed is a harmless no-op that reports the current state — no
    duplicate edge is ever created. Validates that both ids are non-empty and that
    the followee exists.

    Args:
        session: An active SQLAlchemy session (the caller owns the transaction).
        follower_id: The user performing the follow (the resolved caller).
        followee_id: The creator being followed.

    Returns:
        ``{"following": True, "follower_count": int}`` — the followee's fresh
        follower count for an optimistic UI. No private field is disclosed.

    Raises:
        ValueError: If either id is blank or ``follower_id == followee_id``.
        LookupError: If the followee does not exist.
    """
    follower = (follower_id or "").strip()
    followee = (followee_id or "").strip()
    if not follower:
        raise ValueError("follower_id is required")
    if not followee:
        raise ValueError("followee_id is required")
    if follower == followee:
        raise ValueError("a user cannot follow themselves")

    if session.get(User, followee) is None:
        raise LookupError("creator not found")

    repo = CreatorFollowRepository(session)
    repo.follow(follower, followee)
    return {"following": True, "follower_count": repo.follower_count(followee)}


def unfollow(
    session: Session, follower_id: str, followee_id: str
) -> dict[str, Any]:
    """Remove the caller's follow edge (exactly one); return a result envelope.

    Removes the single directed ``follower -> followee`` edge. Unfollowing someone
    the caller does not follow is a harmless no-op (``removed`` is ``False``). A
    blank id is rejected with ``ValueError``.

    Returns:
        ``{"following": False, "removed": bool, "follower_count": int}`` — whether
        an edge was actually removed plus the followee's fresh follower count. No
        private field is disclosed.

    Raises:
        ValueError: If either id is blank.
    """
    follower = (follower_id or "").strip()
    followee = (followee_id or "").strip()
    if not follower:
        raise ValueError("follower_id is required")
    if not followee:
        raise ValueError("followee_id is required")

    repo = CreatorFollowRepository(session)
    removed = repo.unfollow(follower, followee)
    return {
        "following": False,
        "removed": removed,
        "follower_count": repo.follower_count(followee),
    }


# --------------------------------------------------------------------------- #
# Leaderboard
# --------------------------------------------------------------------------- #
def _reputation_score(entry: dict[str, Any]) -> float:
    """Compute the documented, deterministic composite reputation score."""
    return round(
        REP_W_PUBLISHED * entry["published_template_count"]
        + REP_W_CLONES * entry["total_clones_received"]
        + REP_W_RATING * entry["avg_rating"]
        + REP_W_FOLLOWERS * entry["follower_count"]
        + REP_W_WINSCORE * entry["win_score"],
        SCORE_ROUND,
    )


#: The per-metric sort value extractor. Every metric sorts DESC then breaks ties
#: by ``user_id`` ASC (applied in :func:`leaderboard`) for full determinism.
_METRIC_KEY = {
    METRIC_REPUTATION: lambda e: e["reputation_score"],
    METRIC_FOLLOWERS: lambda e: e["follower_count"],
    METRIC_CLONES: lambda e: e["total_clones_received"],
    METRIC_RATING: lambda e: e["avg_rating"],
    METRIC_PUBLISHED: lambda e: e["published_template_count"],
    METRIC_WINSCORE: lambda e: e["win_score"],
}


def _win_scores_by_author(
    session: Session,
    candidate_order: list[str],
    listings_by_author: dict[str, list[str]],
) -> dict[str, float]:
    """Resolve each candidate's downstream win-score (mean of their listings').

    Listing ids are gathered in ``candidate_order`` (best base-score first) and
    scored in ONE bounded :func:`app.services.marketplace.listing_win_scores` pass
    with the self-clone-gaming cohort floor applied. A creator's win-score is the
    MEAN of their listings' available scores (listings without qualifying
    downstream performance simply do not contribute); a creator with none scores
    ``0.0`` — never ``NaN``. Listings beyond
    :data:`LEADERBOARD_WINSCORE_MAX_LISTINGS` are not scored (contributing 0), so
    the pass is bounded.
    """
    ordered_ids: list[str] = []
    for author in candidate_order:
        ordered_ids.extend(listings_by_author.get(author, []))
        if len(ordered_ids) >= LEADERBOARD_WINSCORE_MAX_LISTINGS:
            break
    if not ordered_ids:
        return {}

    scores = marketplace_svc.listing_win_scores(
        session,
        ordered_ids[:LEADERBOARD_WINSCORE_MAX_LISTINGS],
        min_cohort=LEADERBOARD_WINSCORE_MIN_COHORT,
    )
    if not scores:
        return {}

    out: dict[str, float] = {}
    for author, listing_ids in listings_by_author.items():
        vals = [scores[lid] for lid in listing_ids if lid in scores]
        if vals:
            out[author] = sum(vals) / len(vals)
    return out


def leaderboard(
    session: Session,
    metric: str = DEFAULT_METRIC,
    limit: int = LEADERBOARD_DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Rank creators by a documented, deterministic reputation metric.

    Candidates are every creator with at least one PUBLISHED marketplace listing
    UNION every creator with at least one follower (so a followed-but-unpublished
    creator still ranks on the ``followers`` board). Each candidate is annotated
    with their public aggregates and the composite reputation score (see the module
    docstring), then ranked by ``metric`` DESC with a ``user_id`` ASC tie-break so
    the ordering is fully deterministic, and truncated to a clamped ``limit``.

    Every emitted entry contains ONLY safe fields (the profile aggregates + the
    score + a 1-based ``rank`` + the addressing ``user_id``/``handle``) — never
    credits, email, cost/revenue or any other private datum.

    Args:
        session: An active SQLAlchemy session (read-only; not committed here).
        metric: One of :data:`LEADERBOARD_METRICS` (``reputation`` default;
            unknown values fall back to ``reputation``).
        limit: Max entries to return (clamped to ``[1, 100]``).

    Returns:
        ``[{user_id, handle, display_name, published_template_count,
        total_clones_received, avg_rating, follower_count, following_count,
        win_score, reputation_score, rank}, ...]`` ordered best-first.
    """
    chosen_metric = _normalize_metric(metric)
    capped = _clamp_limit(limit)

    marketplace_repo = MarketplaceRepository(session)
    follow_repo = CreatorFollowRepository(session)

    author_aggs = marketplace_repo.all_author_aggregates()
    follower_counts = follow_repo.follower_counts()
    following_counts = follow_repo.following_counts()

    candidate_ids = set(author_aggs) | set(follower_counts)
    if not candidate_ids:
        return []

    # Build a base entry per candidate (win_score filled in below).
    entries: dict[str, dict[str, Any]] = {}
    for uid in candidate_ids:
        aggs = author_aggs.get(uid, {})
        entries[uid] = {
            "user_id": uid,
            "published_template_count": int(
                aggs.get("published_template_count", 0)
            ),
            "total_clones_received": int(aggs.get("total_clones_received", 0)),
            "avg_rating": round(
                float(aggs.get("avg_rating", 0.0)), RATING_ROUND
            ),
            "follower_count": int(follower_counts.get(uid, 0)),
            "following_count": int(following_counts.get(uid, 0)),
            "win_score": 0.0,
        }

    # Downstream win-score: order candidates by their base (non-win-score)
    # reputation so the bounded win-score pass scores the strongest creators first.
    for entry in entries.values():
        entry["_base"] = _reputation_score({**entry, "win_score": 0.0})
    base_order = sorted(
        entries.values(), key=lambda e: (-e["_base"], e["user_id"])
    )
    win_scores = _win_scores_by_author(
        session,
        [e["user_id"] for e in base_order],
        marketplace_repo.published_listing_ids_by_author(),
    )
    for uid, score in win_scores.items():
        if uid in entries:
            entries[uid]["win_score"] = round(float(score), SCORE_ROUND)

    # Finalize the composite score now that win_score is known.
    for entry in entries.values():
        entry.pop("_base", None)
        entry["reputation_score"] = _reputation_score(entry)

    # Attach the safe public identity (handle/display_name) for the returned page
    # only — resolve just the top slice to avoid loading every User row.
    key_fn = _METRIC_KEY[chosen_metric]
    ranked = sorted(
        entries.values(), key=lambda e: (-key_fn(e), e["user_id"])
    )[:capped]

    result: list[dict[str, Any]] = []
    for rank, entry in enumerate(ranked, start=1):
        user = session.get(User, entry["user_id"])
        result.append(
            {
                "user_id": entry["user_id"],
                "handle": (user.handle or "") if user is not None else "",
                "display_name": (
                    (user.display_name or "") if user is not None else ""
                ),
                "published_template_count": entry["published_template_count"],
                "total_clones_received": entry["total_clones_received"],
                "avg_rating": entry["avg_rating"],
                "follower_count": entry["follower_count"],
                "following_count": entry["following_count"],
                "win_score": entry["win_score"],
                "reputation_score": entry["reputation_score"],
                "rank": rank,
            }
        )
    return result


__all__ = [
    "SAFE_PROFILE_FIELDS",
    "LEADERBOARD_METRICS",
    "DEFAULT_METRIC",
    "LEADERBOARD_MIN_LIMIT",
    "LEADERBOARD_MAX_LIMIT",
    "LEADERBOARD_DEFAULT_LIMIT",
    "REP_W_PUBLISHED",
    "REP_W_CLONES",
    "REP_W_RATING",
    "REP_W_FOLLOWERS",
    "REP_W_WINSCORE",
    "LEADERBOARD_WINSCORE_MIN_COHORT",
    "public_profile",
    "follow",
    "unfollow",
    "leaderboard",
]
