"""Pure hashtag-analysis helpers that turn raw TikTok post dicts into the
usage-count series + co-occurrence signals the EXISTING scorer consumes.

Ported and trimmed from ``external/tiktok-hashtag-analysis`` (bellingcat) — the
matplotlib / seaborn / yt-dlp / requests / file-IO surface is dropped so this
module is import-safe, side-effect-free, and fully unit-testable. Every function
is pure: it takes in-memory post dicts (the raw ``itemList`` entries a
:class:`TikTokPullClient` returns) and returns plain Python data.

The single new primitive is :func:`bucket_daily_counts`, which folds each post's
``createTime`` into an oldest→newest per-day count series — exactly the shape
``TrendSignal.counts`` (see ``app.domains.trends.scoring``) needs to score a
trend's velocity/saturation/opportunity.

--------------------------------------------------------------------------------
MIT NOTICE
This file adapts code from bellingcat/tiktok-hashtag-analysis
(https://github.com/bellingcat/tiktok-hashtag-analysis), licensed under the MIT
License. Original copyright (c) Bellingcat. See that project for the full text.
--------------------------------------------------------------------------------
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone, tzinfo

__all__ = [
    "normalize_hashtags",
    "cooccurring_hashtags",
    "prioritize_hashtags",
    "merge_posts",
    "native_sound_id",
    "bucket_daily_counts",
]


def normalize_hashtags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    """Strip ``#``/whitespace, lower-case, drop blanks, and dedupe (order-stable).

    Mirrors the upstream ``process_hashtag_list`` but returns a de-duplicated
    list preserving first-seen order so callers get a deterministic scrape plan.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags or []:
        tag = str(raw or "").strip().lstrip("#").strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def cooccurring_hashtags(posts: list[dict] | None) -> Counter:
    """Count how often each hashtag co-occurs across ``posts``.

    Counts each hashtag at most once per post (a video that repeats ``#fyp`` in
    its caption still contributes one), reading ``video['textExtra'][].hashtagName``
    — the same field the upstream ``aggregate_cooccurring_hashtags`` used. Pure.
    """
    counter: Counter = Counter()
    for post in posts or []:
        names = {
            str(entry.get("hashtagName") or "").strip().lower()
            for entry in (post.get("textExtra") or [])
            if isinstance(entry, dict) and entry.get("hashtagName")
        }
        counter.update(name for name in names if name)
    return counter


def prioritize_hashtags(
    state: dict[str, float | int | None] | None,
) -> list[str]:
    """Order hashtags least-recently-scraped first.

    ``state`` maps a hashtag → its last-scraped epoch timestamp (``None``/``0``
    for "never scraped"). Never-scraped tags sort first (highest priority), then
    oldest-scraped, matching the upstream ``prioritize_hashtags`` heuristic that
    keeps every tracked tag freshly sampled without a filesystem scan.
    """
    items = list((state or {}).items())
    items.sort(key=lambda kv: (kv[1] or 0))
    return [tag for tag, _ in items]


def merge_posts(existing: list[dict] | None, fetched: list[dict] | None) -> list[dict]:
    """Incremental merge: keep every freshly ``fetched`` post plus prior posts
    whose ``id`` was not re-fetched, de-duplicating by ``id`` (fresh wins).

    Mirrors the upstream merge (``old_fetched_data + fetched_data``) so repeated
    pulls accumulate a growing, de-duplicated post history for a trend.
    """
    fetched = list(fetched or [])
    fetched_ids = {str(v.get("id")) for v in fetched if v.get("id") is not None}
    retained = [
        v
        for v in (existing or [])
        if v.get("id") is not None and str(v.get("id")) not in fetched_ids
    ]
    return retained + fetched


def native_sound_id(posts: list[dict] | None) -> str | None:
    """The most common native ``music.id`` across ``posts`` (for upload attach).

    Editing muted then attaching the *exact* native sound on publish is the
    highest-leverage trend move, so we surface the dominant sound id from the
    scraped posts for the compose/publishing handoff. ``None`` when unknown.
    """
    counter: Counter = Counter()
    for post in posts or []:
        music = post.get("music")
        if isinstance(music, dict) and music.get("id"):
            counter.update([str(music["id"])])
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def bucket_daily_counts(
    posts: list[dict] | None,
    *,
    tz: tzinfo = timezone.utc,
) -> tuple[int, ...]:
    """Fold post ``createTime`` values into an oldest→newest per-day count series.

    Each post's ``createTime`` (unix epoch seconds) is bucketed into a calendar
    day in ``tz``; the result is a CONTIGUOUS daily series from the oldest to the
    newest observed day (days with zero posts are filled with ``0``) so the
    downstream scorer sees a real velocity/saturation curve. Returns ``()`` when
    no post carries a usable ``createTime``. Pure and deterministic.
    """
    days: list[datetime] = []
    for post in posts or []:
        raw = post.get("createTime")
        if raw is None:
            continue
        try:
            ts = int(raw)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        days.append(datetime.fromtimestamp(ts, tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        ))
    if not days:
        return ()
    per_day: Counter = Counter(day.date() for day in days)
    start, end = min(per_day), max(per_day)
    series: list[int] = []
    cursor = start
    while cursor <= end:
        series.append(int(per_day.get(cursor, 0)))
        cursor = cursor + timedelta(days=1)
    return tuple(series)
