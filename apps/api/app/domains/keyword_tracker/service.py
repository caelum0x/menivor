"""Keyword tracker: add/remove tracked (app, keyword, country) triples, read
daily top-50 App Store rank history, and the beat-driven refresh that keeps it
current (Menivor Growth phase 2, plans/menivor.md "Daily top-50 rank checks
per app/keyword (public search API, cached), with history charts").

Every rank reading goes through
:mod:`app.domains.appaudit.visibility` (``cached_search`` + ``rank_in_results``)
— the same public, keyless iTunes Search API the free App Store Audit tool
already uses, with its existing 24h in-process cache. Nothing here scrapes an
authenticated UI and nothing calls a paid/keyed endpoint for the rank check
itself.

Popularity (Apple's own Search Popularity index) is the one field that *does*
need a paid/keyed endpoint — it is filled in only when the caller's scope has
a connected ``apple_search_ads`` account, via
:func:`app.domains.integrations.service.keyword_insights`, exactly as the
plan specifies ("Popularity/difficulty only when the customer connects Apple
Ads"). With no connection, ``popularity`` stays ``None`` and the UI says this
honestly under the keyword list — the plan's own fallback note, now backed by
a real check instead of a permanent "not available".

Free vs paid: reuses the same "has this person paid Menivor anything" signal
already gating clean downloads and publishing
(:func:`app.services.user_entitlements.user_entitlements`), not a new billing
concept. Free accounts may track ``FREE_KEYWORD_LIMIT`` keywords; a paid
source (web plan, credit pack, workspace seat, RevenueCat Pro, comp) raises
that to ``PAID_KEYWORD_LIMIT``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.domains.appaudit.visibility import SearchFn, cached_search, rank_in_results
from app.domains.keyword_tracker.models import KeywordRankSnapshot, TrackedKeyword
from app.domains.capture.store import StoreError

FREE_KEYWORD_LIMIT = 10
PAID_KEYWORD_LIMIT = 200
# The iTunes Search cache is 24h; refreshing more often than that just re-reads
# the same cached rows, so the daily beat tick only re-checks a keyword once
# its last reading is older than this.
REFRESH_EVERY = timedelta(hours=20)
# Apple's own Search Popularity index does not refresh any faster than
# Menivor's own rank check does, so re-asking Apple Search Ads more often than
# this would just repeat the same answer. Independent of REFRESH_EVERY (this
# one needs a connected Apple Ads account; the rank check needs nothing).
POPULARITY_REFRESH_EVERY = timedelta(hours=20)
MAX_POPULARITY_TERMS_PER_CALL = 50
_COUNTRY_RE = re.compile(r"^[a-z]{2}$")
_APP_ID_RE = re.compile(r"^\d{1,32}$")
HISTORY_DAYS_DEFAULT = 30
MAX_TERM_LEN = 100
MAX_NAME_LEN = 300


class KeywordTrackerError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite round-trips a ``DateTime(timezone=True)`` column back as naive;
    treat a naive value as UTC (everything here is written in UTC) so it can
    always be compared against an aware ``now``."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware else None


def _normalize_app_id(value: Any) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    if not text or not _APP_ID_RE.match(text):
        raise KeywordTrackerError("app_id must be the numeric App Store id (the id in an apps.apple.com URL)", 422)
    return text


def _normalize_term(value: Any) -> str:
    term = str(value or "").strip()
    if not term:
        raise KeywordTrackerError("term is required", 422)
    if len(term) > MAX_TERM_LEN:
        raise KeywordTrackerError(f"term must be {MAX_TERM_LEN} characters or fewer", 422)
    return term


def _normalize_country(value: Any) -> str:
    country = str(value or "us").strip().lower() or "us"
    if not _COUNTRY_RE.match(country):
        raise KeywordTrackerError("country must be a 2-letter store code (e.g. us, gb, de)", 422)
    return country


# --------------------------------------------------------------------------- #
# Free vs paid limit
# --------------------------------------------------------------------------- #
def keyword_limit(user_id: str) -> int:
    """How many keywords ``user_id`` may track right now."""
    from app.services.user_entitlements import user_entitlements

    try:
        paid = user_entitlements(user_id).paid
    except Exception as exc:  # noqa: BLE001 - never block the tracker on an entitlement outage
        logger.warning(f"keyword_tracker: entitlement check failed for {user_id}: {type(exc).__name__}")
        paid = False
    return PAID_KEYWORD_LIMIT if paid else FREE_KEYWORD_LIMIT


# --------------------------------------------------------------------------- #
# History + view shaping
# --------------------------------------------------------------------------- #
#: How far back a 30-day-change baseline is allowed to reach for its "most
#: recent snapshot at or before the cutoff" lookup. Wider than the 30-day
#: window it serves so a keyword checked daily always has a baseline once it
#: is >=30 days old, instead of the display window itself hiding it.
_BASELINE_LOOKBACK_DAYS = 400


def _snapshots(session: Any, keyword_id: str, *, now: datetime) -> list[KeywordRankSnapshot]:
    cutoff = now - timedelta(days=_BASELINE_LOOKBACK_DAYS)
    stmt = (
        select(KeywordRankSnapshot)
        .where(KeywordRankSnapshot.keyword_id == keyword_id, KeywordRankSnapshot.checked_at >= cutoff)
        .order_by(KeywordRankSnapshot.checked_at)
    )
    return list(session.execute(stmt).scalars().all())


def _change(snapshots: list[KeywordRankSnapshot], *, current: int | None, now: datetime,
            days: int) -> int | None:
    """Rank movement over ``days``: positive means the rank improved (a lower
    number now). ``None`` when either end is unranked or there is no reading
    old enough yet."""
    if current is None:
        return None
    cutoff = now - timedelta(days=days)
    # The most recent snapshot at or before the cutoff (the closest reading to
    # "days ago" without looking into the future).
    before = [s for s in snapshots if _aware(s.checked_at) <= cutoff and s.position is not None]
    if not before:
        return None
    baseline = before[-1].position
    if baseline is None:
        return None
    return baseline - current


def keyword_view(session: Any, row: TrackedKeyword, *, now: datetime | None = None,
                 history_days: int = HISTORY_DAYS_DEFAULT) -> dict[str, Any]:
    moment = now or _now()
    snapshots = _snapshots(session, row.id, now=moment)
    display_cutoff = moment - timedelta(days=history_days)
    history = [{"date": _aware(s.checked_at).date().isoformat(), "position": s.position}
               for s in snapshots if _aware(s.checked_at) >= display_cutoff]
    return {
        "id": row.id,
        "app_id": row.app_id,
        "app_name": row.app_name,
        "country": row.country,
        "term": row.term,
        "current_rank": row.last_position,
        "checked_count": row.last_checked_count,
        "last_checked_at": _iso(row.last_checked_at),
        "last_error": row.last_error or "",
        # Apple's own Search Popularity index (5-100); None until a connected
        # Apple Ads account has scored it (see refresh_popularity below).
        "popularity": row.popularity,
        "change_7d": _change(snapshots, current=row.last_position, now=moment, days=7),
        "change_30d": _change(snapshots, current=row.last_position, now=moment, days=30),
        "history": history,
    }


# --------------------------------------------------------------------------- #
# Add / remove / list
# --------------------------------------------------------------------------- #
def _owned(session: Any, user_id: str, keyword_id: str) -> TrackedKeyword:
    row = session.get(TrackedKeyword, keyword_id) if keyword_id else None
    if row is None or row.user_id != user_id:
        raise KeywordTrackerError("tracked keyword not found", 404)
    return row


def list_keywords(session: Any, user_id: str, *, now: datetime | None = None, scope: Any = None,
                  transport: Any = None) -> dict[str, Any]:
    """``scope`` (an ``app.domains.integrations.scope.Scope``) is optional: pass
    it to also decorate every row with Apple's Search Popularity index, when
    that scope has a connected Apple Search Ads account. Without it (or with
    no connection), every row's ``popularity`` is whatever was last cached --
    ``None`` if it was never connected."""
    rows = session.execute(
        select(TrackedKeyword).where(TrackedKeyword.user_id == user_id).order_by(TrackedKeyword.created_at),
    ).scalars().all()
    moment = now or _now()
    apple_ads_connected = False
    if scope is not None:
        apple_ads_connected = refresh_popularity(session, rows, scope=scope, transport=transport, now=moment)
    limit = keyword_limit(user_id)
    return {
        "keywords": [keyword_view(session, row, now=moment) for row in rows],
        "limit": limit,
        "paid": limit == PAID_KEYWORD_LIMIT,
        "apple_ads_connected": apple_ads_connected,
    }


# --------------------------------------------------------------------------- #
# Popularity (Apple Search Ads keyword insights; only when connected)
# --------------------------------------------------------------------------- #
def _popularity_stale(row: TrackedKeyword, now: datetime) -> bool:
    checked = _aware(row.popularity_checked_at)
    return checked is None or (now - checked) > POPULARITY_REFRESH_EVERY


def refresh_popularity(session: Any, rows: list[TrackedKeyword], *, scope: Any, transport: Any = None,
                       now: datetime | None = None) -> bool:
    """Best-effort: for every row whose popularity reading is stale, ask
    ``scope``'s connected Apple Search Ads account for Apple's own Search
    Popularity index, grouped by (app, country) so each distinct pair costs
    one call. Returns whether an Apple Ads account is connected at all (the
    caller surfaces that as ``apple_ads_connected`` so the UI can say so
    honestly). Never raises -- an Apple Ads hiccup must never block the
    keyword list from loading; it just leaves ``popularity`` as it was.
    """
    from app.domains.integrations import service as integrations_service
    from app.domains.integrations.connectors.base import RequestsTransport

    connected = bool(integrations_service.visible_accounts(session, scope, provider="apple_search_ads"))
    if not connected:
        return False
    moment = now or _now()
    stale = [r for r in rows if _popularity_stale(r, moment)]
    if not stale:
        return True
    live_transport = transport or RequestsTransport()
    groups: dict[tuple[str, str], list[TrackedKeyword]] = {}
    for row in stale:
        groups.setdefault((row.app_id, row.country), []).append(row)
    for (app_id, country), group_rows in groups.items():
        terms = [r.term for r in group_rows][:MAX_POPULARITY_TERMS_PER_CALL]
        try:
            insights = integrations_service.keyword_insights(
                session, scope, adam_id=app_id, country=country, terms=terms, transport=live_transport,
            )
        except Exception as exc:  # noqa: BLE001 - never block the keyword list on an Apple Ads hiccup
            logger.warning(f"keyword_tracker: popularity fetch failed for {app_id}/{country}: {type(exc).__name__}")
            continue
        by_term = {i["term"]: i.get("popularity") for i in insights}
        for row in group_rows:
            if row.term in by_term:
                row.popularity = by_term[row.term]
                row.popularity_checked_at = moment
    session.flush()
    return True


def add_keyword(session: Any, user_id: str, *, app_id: str, term: str, app_name: str = "", country: str = "us",
                search: SearchFn | None = None, now: datetime | None = None,
                cache_now: float | None = None) -> dict[str, Any]:
    """Track one (app, term, country) triple and run its first rank check right away."""
    norm_app_id = _normalize_app_id(app_id)
    norm_term = _normalize_term(term)
    norm_country = _normalize_country(country)
    norm_name = str(app_name or "").strip()[:MAX_NAME_LEN]

    existing = session.execute(
        select(TrackedKeyword).where(
            TrackedKeyword.user_id == user_id, TrackedKeyword.app_id == norm_app_id,
            TrackedKeyword.term == norm_term, TrackedKeyword.country == norm_country,
        ),
    ).scalar_one_or_none()
    if existing is not None:
        raise KeywordTrackerError("you're already tracking that keyword for this app and country", 409)

    count = session.execute(
        select(TrackedKeyword).where(TrackedKeyword.user_id == user_id),
    ).scalars().all()
    limit = keyword_limit(user_id)
    if len(count) >= limit:
        plan_note = "Upgrade to a paid plan to track more." if limit == FREE_KEYWORD_LIMIT else ""
        raise KeywordTrackerError(f"you can track up to {limit} keywords on your plan. {plan_note}".strip(), 402)

    row = TrackedKeyword(
        user_id=user_id, app_id=norm_app_id, app_name=norm_name, country=norm_country, term=norm_term,
    )
    session.add(row)
    session.flush()
    moment = now or _now()
    refresh_keyword(session, row, search=search, now=moment, cache_now=cache_now)
    return keyword_view(session, row, now=moment)


def remove_keyword(session: Any, user_id: str, keyword_id: str) -> bool:
    row = _owned(session, user_id, keyword_id)
    session.execute(KeywordRankSnapshot.__table__.delete().where(KeywordRankSnapshot.keyword_id == row.id))
    session.delete(row)
    session.flush()
    return True


# --------------------------------------------------------------------------- #
# Refresh (one keyword; and the beat's "everything due" pass)
# --------------------------------------------------------------------------- #
def refresh_keyword(session: Any, row: TrackedKeyword, *, search: SearchFn | None = None,
                    now: datetime | None = None, cache_now: float | None = None) -> dict[str, Any]:
    """Check one keyword's rank right now and append a history snapshot.

    ``now`` is the wall-clock moment recorded on the row/snapshot; ``cache_now``
    (a ``time.monotonic()`` value) only controls staleness of
    :func:`app.domains.appaudit.visibility.cached_search`'s 24h cache and is
    normally left unset so the real clock decides (tests pass it explicitly,
    mirroring ``tests/reelforge/test_appaudit.py``).
    """
    moment = now or _now()
    kwargs: dict[str, Any] = {"now": cache_now}
    if search is not None:
        kwargs["search"] = search
    try:
        rows, _cached = cached_search(row.term, row.country, **kwargs)
        position = rank_in_results(rows, row.app_id)
        checked_count = len(rows)
        row.last_error = ""
    except StoreError as exc:
        position = row.last_position
        checked_count = row.last_checked_count
        row.last_error = exc.message[:1000]
        logger.warning(f"keyword_tracker: rank check failed for {row.id}: {exc.message}")
        session.flush()
        return keyword_view(session, row, now=moment)

    snapshot = KeywordRankSnapshot(keyword_id=row.id, checked_at=moment, position=position,
                                   checked_count=checked_count)
    session.add(snapshot)
    row.last_checked_at = moment
    row.last_position = position
    row.last_checked_count = checked_count
    session.flush()
    return keyword_view(session, row, now=moment)


def refresh_one(session: Any, user_id: str, keyword_id: str, *, search: SearchFn | None = None,
                now: datetime | None = None, cache_now: float | None = None) -> dict[str, Any]:
    """Owner-scoped manual "check now" (also used by tests)."""
    row = _owned(session, user_id, keyword_id)
    return refresh_keyword(session, row, search=search, now=now, cache_now=cache_now)


def refresh_due(session: Any, *, now: datetime | None = None, search: SearchFn | None = None,
                cache_now: float | None = None, limit: int = 500) -> int:
    """Beat: refresh every keyword not checked in the last ~20h. One failing
    keyword never stops the tick (mirrors app.domains.competitors.service.refresh_due)."""
    moment = now or _now()
    cutoff = moment - REFRESH_EVERY
    rows = session.execute(
        select(TrackedKeyword)
        .where((TrackedKeyword.last_checked_at.is_(None)) | (TrackedKeyword.last_checked_at < cutoff))
        .order_by(TrackedKeyword.created_at)
        .limit(limit),
    ).scalars().all()
    done = 0
    for row in rows:
        try:
            refresh_keyword(session, row, search=search, now=moment, cache_now=cache_now)
            done += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"keyword_tracker refresh tick: keyword {row.id} failed: {type(exc).__name__}")
    return done


__all__ = [
    "FREE_KEYWORD_LIMIT",
    "KeywordTrackerError",
    "PAID_KEYWORD_LIMIT",
    "POPULARITY_REFRESH_EVERY",
    "add_keyword",
    "keyword_limit",
    "keyword_view",
    "list_keywords",
    "refresh_due",
    "refresh_keyword",
    "refresh_one",
    "refresh_popularity",
    "remove_keyword",
]
