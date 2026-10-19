"""Template Marketplace service — publish / browse / clone / rate.

A thin, validation-and-clamping layer over :class:`MarketplaceRepository` and
:class:`TemplateRatingRepository` (and :class:`UserPresetRepository` for the
clone path). Controllers/workers depend on this service rather than touching the
repositories directly, mirroring :mod:`app.services.workspaces`.

Feature contract
----------------
* **Publish** — a creator publishes an IMMUTABLE snapshot of a private template
  (a saved :class:`UserPreset` "brand kit", identified by ``template_id``) *or*
  an inline snapshot passed as keyword fields. The content
  (``prompt`` / ``params`` / ``tags`` / ``language`` / ``layout``) is copied into
  the listing so a later edit to the author's private template never mutates the
  public listing. Publishing is owner-scoped — a ``template_id`` that is not the
  caller's own preset is rejected.
* **Browse** — search published listings by free-text (title/description), tag
  and language, sorted by rating+recency (default), pure recency, or clone count.
  ``limit`` is clamped to ``[1, 100]`` and ``offset`` to ``>= 0`` so an untrusted
  page request can never trigger an unbounded scan.
* **Clone** — any authenticated user clones a published listing into their own
  private templates via the SAME path a private template is created
  (:meth:`UserPresetRepository.create`), and the listing's ``clone_count`` is
  bumped.
* **Rate** — any authenticated user rates a listing 1..5; exactly one rating per
  ``(user, template)`` (an upsert), and the listing's ``rating_avg`` /
  ``rating_count`` are recomputed atomically.

Every public function validates its inputs and raises ``ValueError`` on a bad
argument (empty ids, unknown/foreign template, out-of-range stars) so the API
layer can map it to a clean ``4xx`` rather than leaking a raw DB error.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db.models import Job, JobPerformance, MarketplaceTemplate, UserPreset
from app.models.db.repositories import (
    MARKETPLACE_DEFAULT_LIMIT,
    MARKETPLACE_MAX_LIMIT,
    MARKETPLACE_SORT_PROVEN,
    MARKETPLACE_SORT_REMIXED,
    MARKETPLACE_SORT_TOP,
    MARKETPLACE_SORTS,
    TEMPLATE_RATING_MAX_STARS,
    TEMPLATE_RATING_MIN_STARS,
    MarketplaceRepository,
    TemplateRatingRepository,
    UserPresetRepository,
)

# Reuse the EXACT win-score aggregation used by the Hook Performance Loop so the
# marketplace's "proven" ranking and the SPARK idea engine share one scoring
# formula (never duplicated here). ``_WinScoreGroup`` folds raw
# :class:`JobPerformance` rows into a deterministic, divide-by-zero-safe score.
from app.services.hook_performance import _Group as _WinScoreGroup

# --------------------------------------------------------------------------- #
# Tunables (re-exported from the repository so the whole feature shares one
# source of truth for the bounds).
# --------------------------------------------------------------------------- #
MIN_STARS: int = TEMPLATE_RATING_MIN_STARS
MAX_STARS: int = TEMPLATE_RATING_MAX_STARS
MAX_LIMIT: int = MARKETPLACE_MAX_LIMIT
DEFAULT_LIMIT: int = MARKETPLACE_DEFAULT_LIMIT
DEFAULT_SORT: str = MARKETPLACE_SORT_TOP
#: The browse ``sort`` value the API + frontends pass to rank listings by the
#: real-world win-score of the reels made from their clones. Re-exported from the
#: repository so the whole feature shares one source of truth for the name.
PROVEN_SORT: str = MARKETPLACE_SORT_PROVEN
#: The browse ``sort`` value the API + frontends pass to rank listings by how many
#: published listings descend from them in the remix tree (``remix_count``).
#: Re-exported from the repository so the whole feature shares one source of truth.
REMIXED_SORT: str = MARKETPLACE_SORT_REMIXED

#: Hard cap on how many ancestors the remix-tree :func:`lineage` walk will follow
#: up the ``parent_template_id`` chain, so a (theoretically impossible) deep or
#: cyclic chain can never trigger an unbounded walk. A remix tree is shallow in
#: practice; 20 is generous headroom.
LINEAGE_MAX_DEPTH: int = 20

#: The provenance key a clone writes into its :class:`UserPreset` ``config`` (and
#: which a reel rendered from that clone carries in its ``Job.params``) recording
#: the marketplace listing it descends from. Kept in sync with
#: :func:`clone_to_user` below.
SOURCE_MARKETPLACE_KEY: str = "source_marketplace_id"

#: Cap on how many listing ids a single win-score aggregation may resolve, so an
#: untrusted caller can never request an unbounded fan-out. A browse page is
#: already clamped to ``MAX_LIMIT`` listings, so this simply mirrors that bound.
_MAX_LISTING_IDS: int = MARKETPLACE_MAX_LIMIT

#: k-anonymity floor for EXPOSING a listing's numeric ``win_score`` to other
#: users. A listing must have at least this many DISTINCT downstream cloners
#: before its blended score is surfaced in an API response, so a stranger can
#: never read a scalar derived from a single creator's private per-template
#: engagement/retention metrics. Internal ORDERING (:func:`proven_ranking`) uses
#: the default floor of 1 — it consumes the relative order, never revealing the
#: value — while the browse controller requests this floor for the field it
#: serialises.
WIN_SCORE_PUBLIC_MIN_COHORT: int = 2

# Cap on the free-text query length so a pathological search term can never
# build a giant LIKE pattern.
_MAX_QUERY_LEN: int = 200
_MAX_TAG_LEN: int = 60


# --------------------------------------------------------------------------- #
# Clamping / validation helpers
# --------------------------------------------------------------------------- #
def _clamp_limit(limit: int | None) -> int:
    """Clamp a requested page size into ``[1, MAX_LIMIT]`` (default on garbage)."""
    try:
        value = int(limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def _clamp_offset(offset: int | None) -> int:
    """Clamp a requested offset into ``>= 0`` (0 on garbage)."""
    try:
        value = int(offset)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _normalize_sort(sort: str | None) -> str:
    """Return a recognized sort key, defaulting to ``top`` on an unknown value."""
    normalized = (sort or "").strip().lower()
    return normalized if normalized in MARKETPLACE_SORTS else DEFAULT_SORT


def _validate_stars(stars: object) -> int:
    """Return ``stars`` as an int in ``[1, 5]`` or raise ``ValueError``.

    Unlike the repository's defensive clamp, the service *rejects* an
    out-of-range rating so the API surfaces a clean 400 rather than silently
    persisting a coerced value the user did not choose.
    """
    try:
        value = int(stars)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError("stars must be an integer between 1 and 5")
    if value < MIN_STARS or value > MAX_STARS:
        raise ValueError(f"stars must be between {MIN_STARS} and {MAX_STARS}")
    return value


def _normalize_tags(tags: object) -> list[str]:
    """Normalize an arbitrary tags value into a de-duplicated lowercase list.

    Accepts a list/tuple of strings or a comma-separated string; each tag is
    trimmed, lowercased and truncated, blanks dropped, and duplicates removed
    (order preserved). A non-list/str value yields ``[]``.
    """
    if isinstance(tags, str):
        raw = tags.split(",")
    elif isinstance(tags, (list, tuple)):
        raw = list(tags)
    else:
        return []

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw:
        token = str(item or "").strip().lower()[:_MAX_TAG_LEN]
        if token and token not in seen:
            seen.add(token)
            cleaned.append(token)
    return cleaned


# --------------------------------------------------------------------------- #
# Publish
# --------------------------------------------------------------------------- #
def publish_from_template(
    session: Session,
    user_id: str,
    template_id: str | None = None,
    *,
    title: str | None = None,
    description: str | None = None,
    prompt: str | None = None,
    params: dict | None = None,
    tags: object = None,
    language: str | None = None,
    layout: str | None = None,
    published: bool = True,
) -> MarketplaceTemplate:
    """Publish an immutable public listing from a private template or inline data.

    When ``template_id`` is given it must be a :class:`UserPreset` OWNED by
    ``user_id`` (owner-scoped — a foreign/missing id raises ``ValueError``); its
    ``name`` and opaque ``config`` seed the snapshot. Explicit keyword fields
    override the values pulled from the preset, and are the sole source when
    ``template_id`` is ``None`` (an inline publish).

    The snapshot is a COPY: ``params`` / ``tags`` are persisted as fresh JSON
    blobs, so a later edit to the source preset's ``config`` never mutates this
    listing. Raises ``ValueError`` on a blank ``user_id`` or an empty resolved
    title.
    """
    owner = (user_id or "").strip()
    if not owner:
        raise ValueError("user_id must be a non-empty string")

    # Seed the snapshot from the caller's private preset when one is referenced.
    seed_title = ""
    seed_config: dict = {}
    if template_id is not None:
        normalized_tid = (template_id or "").strip()
        if not normalized_tid:
            raise ValueError("template_id must be a non-empty string")
        preset = UserPresetRepository(session).get(normalized_tid, owner)
        if preset is None:
            # Missing OR owned by someone else — indistinguishable on purpose so a
            # caller can never probe another user's preset ids.
            raise ValueError("template not found")
        seed_title = preset.name or ""
        seed_config = dict(preset.config or {})

    # REMIX-TREE provenance: if the source preset was itself CLONED from a
    # marketplace listing (its config carries ``source_marketplace_id``), this new
    # listing is a remix of that parent. Resolve the parent link now so it can be
    # recorded on the row and the parent's ``remix_count`` bumped after insert.
    # Guard: the parent must EXIST and still be PUBLISHED — an unresolvable /
    # unpublished parent is ignored silently (the listing publishes as an original,
    # ``parent_template_id`` stays NULL), so a stale or hidden id never dangles.
    parent_link_id = _resolve_remix_parent(session, seed_config)

    # Explicit kwargs win over the preset-derived values; the preset config
    # supplies sensible fallbacks so publishing an existing kit needs no retype.
    resolved_title = (title if title is not None else seed_title) or ""
    resolved_title = str(resolved_title).strip()
    if not resolved_title:
        raise ValueError("a non-empty title is required to publish")

    resolved_description = (
        description if description is not None else seed_config.get("description", "")
    )
    resolved_prompt = (
        prompt if prompt is not None else seed_config.get("prompt", "")
    )
    resolved_params = params if params is not None else seed_config.get("params", {})
    if not isinstance(resolved_params, dict):
        resolved_params = {}
    resolved_tags = tags if tags is not None else seed_config.get("tags", [])
    resolved_language = (
        language if language is not None else seed_config.get("language", "en")
    )
    resolved_layout = (
        layout if layout is not None else seed_config.get("layout", "")
    )

    marketplace = MarketplaceRepository(session)
    listing = marketplace.publish(
        author_user_id=owner,
        title=resolved_title,
        description=str(resolved_description or ""),
        prompt=str(resolved_prompt or ""),
        params=dict(resolved_params or {}),
        tags=_normalize_tags(resolved_tags),
        language=(str(resolved_language or "en").strip().lower() or "en")[:20],
        layout=str(resolved_layout or "")[:40],
        published=bool(published),
        parent_template_id=parent_link_id,
    )
    # Bump the parent's remix_count exactly once for this new remix. Done after a
    # successful insert so a rejected publish never inflates the parent's count.
    if parent_link_id:
        marketplace.increment_remix(parent_link_id)
    logger.info(
        f"published marketplace template {listing.id} "
        f"(author={owner}, from_preset={template_id}, parent={parent_link_id})"
    )
    return listing


def _resolve_remix_parent(session: Session, seed_config: dict) -> str | None:
    """Resolve the remix-tree parent listing id from a source preset's config.

    Returns the ``source_marketplace_id`` recorded in ``seed_config`` ONLY when it
    names an existing, still-``published`` :class:`MarketplaceTemplate`; otherwise
    returns ``None`` (an original publish, or an unresolvable / unpublished
    parent). Because a parent is always a listing that existed and was published
    before this remix, following the link can never form a cycle.
    """
    source_id = seed_config.get(SOURCE_MARKETPLACE_KEY) if seed_config else None
    if not isinstance(source_id, str):
        return None
    normalized = source_id.strip()
    if not normalized:
        return None
    parent = MarketplaceRepository(session).get(normalized)
    if parent is None or not parent.published:
        return None
    return parent.id


# --------------------------------------------------------------------------- #
# Browse
# --------------------------------------------------------------------------- #
def browse(
    session: Session,
    *,
    query: str = "",
    tag: str = "",
    language: str = "",
    sort: str = DEFAULT_SORT,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> list[MarketplaceTemplate]:
    """Return published listings matching the filters, clamped + sorted.

    ``query`` (title/description substring), ``tag`` (single JSON-list
    membership) and ``language`` are all optional and normalized here; ``sort``
    is validated to one of the known orders; ``limit`` is clamped to ``[1, 100]``
    and ``offset`` to ``>= 0`` so an untrusted page request can never scan the
    whole table.
    """
    normalized_query = (query or "").strip()[:_MAX_QUERY_LEN]
    normalized_tag = (tag or "").strip().lower()[:_MAX_TAG_LEN]
    normalized_language = (language or "").strip().lower()
    normalized_sort = _normalize_sort(sort)

    listings = MarketplaceRepository(session).list(
        query=normalized_query,
        tag=normalized_tag,
        language=normalized_language,
        sort=normalized_sort,
        limit=_clamp_limit(limit),
        offset=_clamp_offset(offset),
    )

    # The repository returns the ``proven`` page in ``top`` (rating/recency)
    # order because the win-score is a Python-side aggregate; re-rank that
    # bounded page by real-world performance here.
    if normalized_sort == PROVEN_SORT:
        listings = proven_ranking(session, listings)
    return listings


# --------------------------------------------------------------------------- #
# Proven-performance ranking (win-score, computed at query time)
# --------------------------------------------------------------------------- #
def _clean_listing_ids(listing_ids: Iterable[str]) -> list[str]:
    """De-duplicate + trim listing ids, drop blanks, and clamp the count.

    Order is preserved (first occurrence wins). A non-iterable or empty input
    yields ``[]`` so callers can pass an untrusted collection safely.
    """
    if not listing_ids:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in listing_ids:
        token = str(raw or "").strip()
        if token and token not in seen:
            seen.add(token)
            cleaned.append(token)
            if len(cleaned) >= _MAX_LISTING_IDS:
                break
    return cleaned


def listing_win_scores(
    session: Session, listing_ids: Iterable[str], min_cohort: int = 1
) -> dict[str, float]:
    """Aggregate the real-world win-score of the reels made from each listing.

    Provenance chain (all evaluated at query time — no new table):
    ``MarketplaceTemplate.id`` → cloned into a :class:`UserPreset` whose
    ``config[source_marketplace_id]`` records the source listing → a reel
    (:class:`Job`) rendered from that clone carries the same
    ``source_marketplace_id`` in its ``params`` → the creator logs the reel's
    outcome as a :class:`JobPerformance` row. All downstream performance rows for
    a listing are folded into ONE :class:`~app.services.hook_performance._Group`
    and scored with the SAME deterministic, divide-by-zero-safe win-score used by
    the Hook Performance Loop (imported, never re-derived).

    Strictly per-user provenance: a reel only counts toward a listing when the
    reel's OWNER actually cloned that listing (a matching ``UserPreset`` exists),
    so a spoofed ``source_marketplace_id`` in another creator's job params can
    never inflate a listing's score.

    Args:
        session: An active SQLAlchemy session (read-only; not committed here).
        listing_ids: The listing ids to score (de-duplicated + clamped).
        min_cohort: k-anonymity floor — a listing's score is only emitted when it
            has at least this many DISTINCT downstream cloners. Defaults to ``1``
            (every proven listing) for internal ordering; the browse controller
            passes :data:`WIN_SCORE_PUBLIC_MIN_COHORT` so a numeric score derived
            from a single creator's private metrics is never exposed to strangers.

    Returns:
        ``{listing_id: win_score}`` containing ONLY listings with at least one
        downstream reel AND at least ``min_cohort`` distinct cloners. A listing
        with no performance data (or below the cohort floor) is simply absent (the
        caller falls back to ``rating_avg``) — never a ``0``/``NaN`` entry.
    """
    ids = _clean_listing_ids(listing_ids)
    if not ids:
        return {}
    id_set = set(ids)

    # Hop 1 — the clones: which users cloned each source listing. A user only
    # ever appears under a listing they genuinely cloned, giving us the per-user
    # provenance gate for hop 2.
    cloners_by_listing: dict[str, set[str]] = defaultdict(set)
    preset_stmt = select(UserPreset.user_id, UserPreset.config)
    for user_id, config in session.execute(preset_stmt).all():
        blob = config if isinstance(config, dict) else {}
        source_id = blob.get(SOURCE_MARKETPLACE_KEY)
        if isinstance(source_id, str) and source_id in id_set:
            cloners_by_listing[source_id].add(user_id)
    if not cloners_by_listing:
        return {}

    owner_ids = {uid for owners in cloners_by_listing.values() for uid in owners}

    # Hop 2 — the reels: JobPerformance rows for those cloners' jobs whose params
    # carry the listing's provenance stamp. Bounded to the cloner set (never a
    # whole-table scan) and gated on the reel owner having cloned the listing.
    groups: dict[str, _WinScoreGroup] = defaultdict(_WinScoreGroup)
    perf_stmt = (
        select(JobPerformance, Job.params, Job.user_id)
        .join(Job, JobPerformance.job_id == Job.id)
        .where(
            Job.user_id.in_(owner_ids),
            JobPerformance.user_id.in_(owner_ids),
        )
    )
    for perf, params, job_user_id in session.execute(perf_stmt).all():
        blob = params if isinstance(params, dict) else {}
        source_id = blob.get(SOURCE_MARKETPLACE_KEY)
        if not (isinstance(source_id, str) and source_id in id_set):
            continue
        if job_user_id not in cloners_by_listing.get(source_id, ()):
            continue  # reel owner never cloned this listing — ignore (anti-spoof)
        groups[source_id].add(perf)

    floor = max(1, int(min_cohort))
    return {
        source_id: group.win_score()
        for source_id, group in groups.items()
        if group.reels > 0
        and len(cloners_by_listing.get(source_id, ())) >= floor
    }


def proven_ranking(
    session: Session, listings: list[MarketplaceTemplate]
) -> list[MarketplaceTemplate]:
    """Re-rank listings by proven downstream win-score (rating fallback).

    Listings with at least one downstream reel (see :func:`listing_win_scores`)
    are ordered FIRST, best win-score first; listings with no performance data
    fall back to their existing ``rating_avg`` (then ``rating_count``) ordering
    and follow. Every tie is broken deterministically by ``id`` so the ordering
    is stable and divide-by-zero safe (a listing with no reels never yields
    ``NaN`` — it is simply scored by rating).

    The input list is not mutated; a new, reordered list is returned.
    """
    if not listings:
        return []
    scores = listing_win_scores(session, [listing.id for listing in listings])

    def _sort_key(listing: MarketplaceTemplate) -> tuple:
        score = scores.get(listing.id)
        if score is not None:
            # Proven bucket (0 sorts before 1): best win-score first.
            return (0, -score, -(listing.rating_count or 0), listing.id)
        # Unproven bucket: fall back to the "top" rating ordering.
        return (
            1,
            -(listing.rating_avg or 0.0),
            -(listing.rating_count or 0),
            listing.id,
        )

    return sorted(listings, key=_sort_key)


def get(session: Session, template_id: str) -> MarketplaceTemplate | None:
    """Return a single listing by id (any published state), or ``None``."""
    normalized = (template_id or "").strip()
    if not normalized:
        return None
    return MarketplaceRepository(session).get(normalized)


# --------------------------------------------------------------------------- #
# Remix-tree lineage
# --------------------------------------------------------------------------- #
def lineage(
    session: Session,
    template_id: str,
    *,
    children_limit: int = MAX_LIMIT,
) -> dict[str, list[MarketplaceTemplate]]:
    """Return the remix-tree lineage of a listing: its ancestors and children.

    ``ancestors`` walks UP the ``parent_template_id`` chain — the immediate parent
    first, then its parent, and so on toward the root — capped at
    :data:`LINEAGE_MAX_DEPTH` hops (with a defensive visited-set guard, though a
    cycle is structurally impossible because a parent is always a strictly-older
    row). ``children`` are the DIRECT, still-published remixes of this listing
    (:meth:`MarketplaceRepository.get_children`), newest first, with
    ``children_limit`` clamped to ``[1, 100]``.

    Returns ``{"ancestors": [...], "children": [...]}`` where each entry is a
    :class:`MarketplaceTemplate` row (the API layer serializes only the safe,
    public listing fields). An unknown / blank ``template_id`` yields two empty
    lists.
    """
    normalized = (template_id or "").strip()
    if not normalized:
        return {"ancestors": [], "children": []}

    repo = MarketplaceRepository(session)
    current = repo.get(normalized)
    if current is None:
        return {"ancestors": [], "children": []}

    ancestors: list[MarketplaceTemplate] = []
    seen: set[str] = {current.id}
    parent_id = current.parent_template_id
    depth = 0
    while parent_id and depth < LINEAGE_MAX_DEPTH:
        if parent_id in seen:
            break  # defensive: never revisit a node (cycles are impossible)
        parent = repo.get(parent_id)
        if parent is None:
            break  # dangling link (e.g. a hard-deleted ancestor) — stop cleanly
        ancestors.append(parent)
        seen.add(parent.id)
        parent_id = parent.parent_template_id
        depth += 1

    children = repo.get_children(normalized, limit=children_limit)
    return {"ancestors": ancestors, "children": children}


# --------------------------------------------------------------------------- #
# Clone
# --------------------------------------------------------------------------- #
def clone_to_user(
    session: Session, user_id: str, template_id: str
) -> UserPreset:
    """Clone a PUBLISHED listing into the caller's private templates.

    Creates a private :class:`UserPreset` for ``user_id`` via the same path a
    private template is created (:meth:`UserPresetRepository.create`), copying the
    listing's snapshot content into the preset ``config`` (with a
    ``source_marketplace_id`` for provenance), and bumps the listing's
    ``clone_count``. Raises ``ValueError`` on a blank id, or when the listing is
    missing/unpublished (an unpublished listing can no longer be cloned).
    """
    owner = (user_id or "").strip()
    if not owner:
        raise ValueError("user_id must be a non-empty string")
    normalized_tid = (template_id or "").strip()
    if not normalized_tid:
        raise ValueError("template_id must be a non-empty string")

    marketplace = MarketplaceRepository(session)
    listing = marketplace.get(normalized_tid)
    if listing is None or not listing.published:
        raise ValueError("template not found")

    # Snapshot the listing content into a fresh private-preset config (copies of
    # the JSON blobs) so the clone is fully decoupled from the listing.
    config = {
        "prompt": listing.prompt,
        "params": dict(listing.params or {}),
        "tags": list(listing.tags or []),
        "language": listing.language,
        "layout": listing.layout,
        "description": listing.description,
        SOURCE_MARKETPLACE_KEY: listing.id,
    }
    preset = UserPresetRepository(session).create(
        user_id=owner,
        name=listing.title,
        config=config,
    )
    # Self-clone guard: a creator cloning THEIR OWN listing must never inflate its
    # public ``clone_count``. That counter feeds the author reputation aggregates
    # and the creators leaderboard (``total_clones_received`` +
    # ``REP_W_CLONES``-weighted reputation), so counting self-clones would let an
    # author rank themselves up by cloning their own listing repeatedly. Only an
    # EXTERNAL clone (a different user) counts toward the public signal; the
    # private preset is still created either way so the owner can reuse the kit.
    if owner != listing.author_user_id:
        marketplace.increment_clone(listing.id)
    logger.info(
        f"cloned marketplace template {listing.id} -> preset {preset.id} "
        f"(user={owner})"
    )
    return preset


# --------------------------------------------------------------------------- #
# Rate
# --------------------------------------------------------------------------- #
def rate(
    session: Session, user_id: str, template_id: str, stars: int
) -> MarketplaceTemplate:
    """Rate a listing 1..5 (one rating per user, upsert) and return the listing.

    Validates ``stars`` into ``[1, 5]`` (raising ``ValueError`` on an
    out-of-range value) and requires an existing, published listing. The rating
    is upserted (a re-rate updates the caller's existing row rather than adding a
    duplicate) and the listing's ``rating_avg`` / ``rating_count`` are recomputed
    atomically. Raises ``ValueError`` on a blank id or a missing/unpublished
    listing.
    """
    owner = (user_id or "").strip()
    if not owner:
        raise ValueError("user_id must be a non-empty string")
    normalized_tid = (template_id or "").strip()
    if not normalized_tid:
        raise ValueError("template_id must be a non-empty string")
    validated_stars = _validate_stars(stars)

    marketplace = MarketplaceRepository(session)
    listing = marketplace.get(normalized_tid)
    if listing is None or not listing.published:
        raise ValueError("template not found")

    TemplateRatingRepository(session).upsert_rating(
        listing.id, owner, validated_stars
    )
    # Reload so the caller sees the freshly recomputed aggregate.
    session.refresh(listing)
    logger.info(
        f"rated marketplace template {listing.id} "
        f"stars={validated_stars} (user={owner})"
    )
    return listing


__all__ = [
    "MIN_STARS",
    "MAX_STARS",
    "MAX_LIMIT",
    "DEFAULT_LIMIT",
    "DEFAULT_SORT",
    "PROVEN_SORT",
    "REMIXED_SORT",
    "LINEAGE_MAX_DEPTH",
    "SOURCE_MARKETPLACE_KEY",
    "publish_from_template",
    "browse",
    "get",
    "lineage",
    "clone_to_user",
    "rate",
    "listing_win_scores",
    "proven_ranking",
]
