"""The results page payload: which hooks and styles win, a views chart, the posts.

Only numbers a platform reported (or the creator typed) are used. A counter that
was never reported stays ``None`` and is left out of every sum; nothing is
estimated. Rankings compare average views per post, then engagement.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from .access import SUGGESTED, label, metrics_access
from .models import COUNTERS, SOURCE_PUBLISHED, STATE_NEEDS_ACCESS, STATE_NO_STATS, STATE_WAITING, PostSnapshot
from .tracker import aware, iter_user_posts

CHART_DAYS = 30
MAX_WINNERS = 5
_MAX_SNAPSHOTS = 20_000
_ENGAGEMENT_KEYS = ("likes", "comments", "shares", "saves")
#: Classic create presets by the layout they render (``/create?preset=``).
_LAYOUT_PRESET = {"pip": "talking", "hook_intro": "product", "split": "story", "captions_only": "faceless"}


@dataclass
class _Group:
    posts: int = 0
    views: int = 0
    viewed_posts: int = 0
    engagements: int = 0
    sample: dict = field(default_factory=dict)

    def add(self, post: Any) -> None:
        self.posts += 1
        if post.views is not None:
            self.views += int(post.views)
            self.viewed_posts += 1
        self.engagements += sum(int(getattr(post, k) or 0) for k in _ENGAGEMENT_KEYS)

    @property
    def avg_views(self) -> float | None:
        return self.views / self.viewed_posts if self.viewed_posts else None

    @property
    def engagement_rate(self) -> float | None:
        return round(self.engagements / self.views, 4) if self.views > 0 else None

    def rank_key(self) -> tuple:
        return (-(self.avg_views if self.avg_views is not None else -1.0), -self.engagements)


def _job_facts(session: Any, job_ids: set[str], user_id: str) -> dict[str, dict]:
    from app.domains.insights.remake import winning_hook
    from app.models.db.models import Job

    if not job_ids:
        return {}
    out: dict[str, dict] = {}
    for job in session.execute(select(Job).where(Job.id.in_(job_ids), Job.user_id == user_id)).scalars().all():
        params = job.params if isinstance(job.params, dict) else {}
        hook = winning_hook(job)[0][:200]
        preset = str(params.get("style") or "") or _LAYOUT_PRESET.get(str(params.get("layout") or ""), "")
        topic = str(params.get("source_url") or params.get("video_subject") or hook)[:600]
        out[job.id] = {"hook": hook, "preset": preset, "topic": topic}
    return out


def _hook_of(post: Any, facts: dict[str, dict]) -> str:
    fact = facts.get(post.job_id or "")
    return (fact or {}).get("hook") or str(post.title or "").strip()[:200]


def _ranked(groups: dict[str, _Group], key_name: str) -> list[dict]:
    rows = [(k, g) for k, g in groups.items() if k and (g.viewed_posts or g.engagements)]
    rows.sort(key=lambda item: (item[1].rank_key(), item[0]))
    out = []
    for name, g in rows[:MAX_WINNERS]:
        avg = g.avg_views
        out.append({
            key_name: name,
            "posts": g.posts,
            "views": g.views if g.viewed_posts else None,
            "avg_views": None if avg is None else round(avg),
            "engagements": g.engagements,
            "engagement_rate": g.engagement_rate,
            "remake": dict(g.sample),
        })
    return out


def _why(winners: list[dict]) -> str:
    if not winners:
        return ""
    top = winners[0]
    if top["avg_views"] is None:
        return f"Most engagement so far: {top['engagements']:,} likes, comments and shares."
    others = [w["avg_views"] for w in winners[1:] if w["avg_views"]]
    base = f"Averages {top['avg_views']:,} views per post"
    if others:
        typical = sum(others) / len(others)
        if typical > 0 and top["avg_views"] >= 1.2 * typical:
            ratio = f"{top['avg_views'] / typical:.1f}".removesuffix(".0")
            return f"{base}, {ratio}x your other hooks."
    return f"{base}."


def _series(session: Any, user_id: str, today: date) -> list[dict]:
    """Daily total views (latest reading of each post as of each day), last 30 days."""
    rows = session.execute(
        select(PostSnapshot.post_id, PostSnapshot.captured_at, PostSnapshot.views)
        .where(PostSnapshot.user_id == user_id, PostSnapshot.views.is_not(None))
        .order_by(PostSnapshot.captured_at.asc())
        .limit(_MAX_SNAPSHOTS)
    ).all()
    if not rows:
        return []
    start = max(aware(rows[0][1]).date(), today - timedelta(days=CHART_DAYS - 1))
    latest: dict[str, int] = {}
    points: list[dict] = []
    i = 0
    day = start
    while day <= today:
        while i < len(rows) and aware(rows[i][1]).date() <= day:
            latest[rows[i][0]] = int(rows[i][2])
            i += 1
        points.append({"date": day.isoformat(), "views": sum(latest.values())})
        day += timedelta(days=1)
    return points if len(points) >= 2 else []


def _post_record(post: Any, hook: str) -> dict:
    checked = aware(post.last_checked_at)
    return {
        "id": post.id,
        "platform": post.platform,
        "label": label(post.platform),
        "url": post.url or "",
        "title": post.title or hook,
        "from_menivor": post.source == SOURCE_PUBLISHED,
        "state": post.state,
        "note": post.note or "",
        **{k: getattr(post, k) for k in COUNTERS},
        "last_checked_at": checked.isoformat() if checked else None,
        "can_type_numbers": post.state in (STATE_NO_STATS, STATE_NEEDS_ACCESS, STATE_WAITING),
    }


def _platforms(connected: dict[str, str]) -> list[dict]:
    names = list(dict.fromkeys([*connected.keys(), *SUGGESTED]))
    out = []
    for plat in names:
        is_connected = plat in connected
        if not is_connected and plat not in SUGGESTED:
            continue
        out.append(metrics_access(plat, connected=is_connected, scopes=connected.get(plat, "")).to_record())
    return out


def build_results(session: Any, user_id: str, *, now: datetime, connected: dict[str, str]) -> dict:
    posts = list(iter_user_posts(session, user_id))
    facts = _job_facts(session, {p.job_id for p in posts if p.job_id}, user_id)
    hooks: dict[str, _Group] = defaultdict(_Group)
    styles: dict[str, _Group] = defaultdict(_Group)
    measured = [p for p in posts if p.last_checked_at is not None]
    for post in measured:
        fact = facts.get(post.job_id or "", {})
        hook = _hook_of(post, facts)
        if hook:
            group = hooks[hook]
            group.add(post)
            group.sample = group.sample or {"q": fact.get("topic") or hook, "preset": fact.get("preset", "")}
        preset = fact.get("preset", "")
        if preset:
            group = styles[preset]
            group.add(post)
            group.sample = group.sample or {"q": fact.get("topic") or hook, "preset": preset}
    hook_winners = _ranked(hooks, "hook")
    style_winners = _ranked(styles, "preset")
    views_known = [int(p.views) for p in measured if p.views is not None]
    return {
        "has_data": bool(measured),
        "tracking": len(posts),
        "totals": {
            "posts": len(measured),
            "views": sum(views_known) if views_known else None,
            "engagements": sum(int(getattr(p, k) or 0) for p in measured for k in _ENGAGEMENT_KEYS),
        },
        "winner": ({**hook_winners[0], "why": _why(hook_winners)} if hook_winners else None),
        "hooks": hook_winners,
        "styles": style_winners,
        "series": _series(session, user_id, now.date()),
        "posts": [_post_record(p, _hook_of(p, facts)) for p in posts],
        "platforms": _platforms(connected),
    }


__all__ = ["CHART_DAYS", "build_results"]
