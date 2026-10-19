"""Campaigns: "post these videos across these accounts", planned within each account's limits.

A campaign fans N videos out to the chosen accounts (``spread``: each video once,
balanced across accounts; ``every``: each video on every account) and writes one
queue row per (video, account) at a planned time that keeps every account inside
its daily cap, spacing and posting hours. The runner (:mod:`.runner`) publishes
the rows when they come due and re-checks the limits at that moment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from . import accounts as acct_service
from . import pacing
from .models import (
    ACCOUNT_CONNECTED,
    CAMPAIGN_ACTIVE,
    CAMPAIGN_CANCELED,
    COUNTED_POST_STATUSES,
    POST_CANCELED,
    POST_FAILED,
    POST_HELD,
    POST_SCHEDULED,
    POST_STATUSES,
    TIKTOK,
    MultipostAccount,
    MultipostCampaign,
    MultipostPost,
)
from .oauth import ConnectError

MAX_VIDEOS = 100
MAX_ACCOUNTS = 50
MAX_POSTS = 500
MAX_LEAD = timedelta(days=90)
VISIBILITIES = frozenset({"public", "friends", "private"})
MODES = frozenset({"spread", "every"})
TIKTOK_MODES = frozenset({"direct", "draft"})


class CampaignError(ConnectError):
    """Bad campaign input or state (``status_code`` maps to HTTP)."""


@dataclass(frozen=True)
class CampaignInput:
    job_ids: tuple[str, ...]
    account_ids: tuple[str, ...]
    visibility: str
    name: str = ""
    mode: str = "spread"
    start_at: datetime | None = None
    caption: str = ""
    hashtags: tuple[str, ...] = ()
    tiktok_mode: str = "direct"
    allow_comments: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    brand_content: bool = False
    brand_organic: bool = False
    titles: dict = field(default_factory=dict)  # optional per-video title/caption override {job_id: text}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe(values: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def _validate(session: Any, user_id: str, data: CampaignInput, now: datetime
              ) -> tuple[list[str], list[MultipostAccount], datetime]:
    job_ids = _dedupe(data.job_ids)
    account_ids = _dedupe(data.account_ids)
    if not 1 <= len(job_ids) <= MAX_VIDEOS:
        raise CampaignError(f"choose 1 to {MAX_VIDEOS} videos")
    if not 1 <= len(account_ids) <= MAX_ACCOUNTS:
        raise CampaignError(f"choose 1 to {MAX_ACCOUNTS} accounts")
    if data.visibility not in VISIBILITIES:
        raise CampaignError("choose who can see the posts")
    if data.mode not in MODES:
        raise CampaignError("unknown distribution mode")
    if data.tiktok_mode not in TIKTOK_MODES:
        raise CampaignError("unknown TikTok mode")
    if data.brand_content and data.visibility == "private":
        raise CampaignError("branded content cannot be private; choose who can see the posts")
    start = acct_service.aware(data.start_at) or now
    if start < now - timedelta(minutes=5):
        raise CampaignError("the start time is in the past")
    if start - now > MAX_LEAD:
        raise CampaignError("schedule at most 90 days ahead")
    start = max(start, now)

    from app.models.db.models import Job

    for job_id in job_ids:
        job = session.get(Job, job_id)
        if job is None or str(getattr(job, "user_id", "")) != str(user_id):
            raise CampaignError("one of the videos was not found", status_code=404)
    rows: list[MultipostAccount] = []
    for account_id in account_ids:
        row = acct_service.get_for(session, user_id, account_id)
        if row.status != ACCOUNT_CONNECTED:
            name = row.display_name or row.handle or row.provider
            raise CampaignError(f"{name} is {row.status.replace('_', ' ')}; fix it before scheduling",
                                status_code=409)
        rows.append(row)
    total = len(job_ids) * (len(rows) if data.mode == "every" else 1)
    if total > MAX_POSTS:
        raise CampaignError(f"that would create {total} posts; the limit is {MAX_POSTS} per batch")
    return job_ids, rows, start


def _taken(session: Any, account_id: str, since: datetime) -> tuple[datetime, ...]:
    statuses = list(COUNTED_POST_STATUSES | {POST_SCHEDULED})
    rows = session.execute(select(
        MultipostPost.status, MultipostPost.scheduled_at, MultipostPost.next_attempt_at, MultipostPost.published_at,
    ).where(MultipostPost.account_id == account_id, MultipostPost.status.in_(statuses))).all()
    out = []
    for status, scheduled_at, next_attempt_at, published_at in rows:
        when = published_at if status == "published" and published_at else (next_attempt_at or scheduled_at)
        when = acct_service.aware(when)
        if when is not None and when >= since - pacing.DAY:
            out.append(when)
    return tuple(sorted(out))


def _plan(session: Any, job_ids: list[str], rows: list[MultipostAccount], start: datetime, mode: str):
    plans = [pacing.AccountPlan(r.id, acct_service.limits_for(r), _taken(session, r.id, start)) for r in rows]
    return pacing.plan(job_ids, plans, start, mode=mode)


def preview(session: Any, user_id: str, data: CampaignInput) -> dict:
    """The schedule a campaign would get, without writing anything."""
    now = _now()
    job_ids, rows, start = _validate(session, user_id, data, now)
    by_id = {r.id: r for r in rows}
    slots = _plan(session, job_ids, rows, start, data.mode)
    return {
        "start_at": start.isoformat(),
        "posts": [_slot_view(job_id, by_id[account_id], at) for job_id, account_id, at in slots],
        "last_post_at": slots[-1][2].isoformat() if slots else None,
        "notes": _notes(rows, data),
    }


def _slot_view(job_id: str, row: MultipostAccount, at: datetime) -> dict:
    return {"job_id": job_id, "account_id": row.id, "provider": row.provider,
            "account_name": row.display_name or row.handle, "at": at.isoformat()}


def _notes(rows: list[MultipostAccount], data: CampaignInput) -> list[str]:
    from . import settings

    notes: list[str] = []
    providers = {r.provider for r in rows}
    if TIKTOK in providers and not settings.tiktok_audited() and data.tiktok_mode == "direct":
        notes.append("TikTok posts go out as private until TikTok approves this app.")
    if "youtube" in providers and not settings.youtube_verified():
        notes.append("YouTube uploads stay private until Google verifies this app.")
    if "instagram" in providers:
        notes.append(f"Instagram posts end with \"{settings.instagram_caption_disclosure()}\" "
                     "because Instagram has no AI label you can set from outside the app.")
    notes.append("Every post is labelled as AI-generated where the platform supports it.")
    return notes


def create(session: Any, user_id: str, data: CampaignInput) -> dict:
    now = _now()
    job_ids, rows, start = _validate(session, user_id, data, now)
    by_id = {r.id: r for r in rows}
    slots = _plan(session, job_ids, rows, start, data.mode)
    campaign = MultipostCampaign(
        user_id=user_id, name=(data.name or "").strip()[:200] or f"Batch of {len(job_ids)} videos",
        mode=data.mode, caption=(data.caption or "").strip()[:2200],
        hashtags=[t.strip().lstrip("#")[:100] for t in data.hashtags if t and t.strip()][:30],
        visibility=data.visibility, tiktok_mode=data.tiktok_mode,
        allow_comments=bool(data.allow_comments), allow_duet=bool(data.allow_duet),
        allow_stitch=bool(data.allow_stitch), brand_content=bool(data.brand_content),
        brand_organic=bool(data.brand_organic), ai_generated=True,
        job_ids=job_ids, account_ids=[r.id for r in rows], start_at=start,
    )
    session.add(campaign)
    session.flush()
    for job_id, account_id, at in slots:
        override = str((data.titles or {}).get(job_id) or "").strip()
        session.add(MultipostPost(
            campaign_id=campaign.id, user_id=user_id, account_id=account_id, job_id=job_id,
            provider=by_id[account_id].provider, status=POST_SCHEDULED, scheduled_at=at,
            title=override[:300], caption=override[:2200] or campaign.caption,
        ))
    session.flush()
    return detail(session, user_id, campaign.id)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def post_view(post: MultipostPost, account: MultipostAccount | None = None) -> dict:
    aware = acct_service.aware
    return {
        "id": post.id,
        "campaign_id": post.campaign_id,
        "job_id": post.job_id,
        "account_id": post.account_id,
        "account_name": (account.display_name or account.handle) if account else "",
        "provider": post.provider,
        "status": post.status,
        "scheduled_at": aware(post.scheduled_at).isoformat() if post.scheduled_at else None,
        "next_attempt_at": aware(post.next_attempt_at).isoformat() if post.next_attempt_at else None,
        "attempts": post.attempts,
        "provider_status": post.provider_status,
        "url": post.url,
        "error": post.error,
        "published_at": aware(post.published_at).isoformat() if post.published_at else None,
    }


def _accounts_by_id(session: Any, posts: list[MultipostPost]) -> dict[str, MultipostAccount]:
    ids = list({p.account_id for p in posts})
    if not ids:
        return {}
    rows = session.execute(select(MultipostAccount).where(MultipostAccount.id.in_(ids))).scalars().all()
    return {r.id: r for r in rows}


def _counts(posts: list[MultipostPost]) -> dict[str, int]:
    counts = {status: 0 for status in sorted(POST_STATUSES)}
    for post in posts:
        counts[post.status] = counts.get(post.status, 0) + 1
    return counts


def _owned_campaign(session: Any, user_id: str, campaign_id: str) -> MultipostCampaign:
    row = session.get(MultipostCampaign, campaign_id)
    if row is None or row.user_id != user_id:
        raise CampaignError("batch not found", status_code=404)
    return row


def detail(session: Any, user_id: str, campaign_id: str) -> dict:
    row = _owned_campaign(session, user_id, campaign_id)
    posts = list(session.execute(select(MultipostPost).where(MultipostPost.campaign_id == row.id)
                                 .order_by(MultipostPost.scheduled_at)).scalars())
    accts = _accounts_by_id(session, posts)
    return {**campaign_view(row, posts), "posts": [post_view(p, accts.get(p.account_id)) for p in posts]}


def campaign_view(row: MultipostCampaign, posts: list[MultipostPost]) -> dict:
    return {
        "id": row.id, "name": row.name, "status": row.status, "mode": row.mode,
        "visibility": row.visibility, "tiktok_mode": row.tiktok_mode, "ai_generated": row.ai_generated,
        "videos": len(row.job_ids or []), "accounts": len(row.account_ids or []),
        "start_at": acct_service.aware(row.start_at).isoformat() if row.start_at else None,
        "created_at": acct_service.aware(row.created_at).isoformat() if row.created_at else None,
        "counts": _counts(posts),
    }


def list_campaigns(session: Any, user_id: str, *, limit: int = 50) -> list[dict]:
    rows = session.execute(select(MultipostCampaign).where(MultipostCampaign.user_id == user_id)
                           .order_by(MultipostCampaign.created_at.desc()).limit(limit)).scalars().all()
    out = []
    for row in rows:
        posts = list(session.execute(select(MultipostPost).where(MultipostPost.campaign_id == row.id)).scalars())
        out.append(campaign_view(row, posts))
    return out


def list_posts(session: Any, user_id: str, *, status: str = "", limit: int = 200) -> list[dict]:
    query = select(MultipostPost).where(MultipostPost.user_id == user_id)
    if status:
        if status not in POST_STATUSES:
            raise CampaignError("unknown status")
        query = query.where(MultipostPost.status == status)
    posts = list(session.execute(query.order_by(MultipostPost.scheduled_at.desc()).limit(limit)).scalars())
    accts = _accounts_by_id(session, posts)
    return [post_view(p, accts.get(p.account_id)) for p in posts]


# --------------------------------------------------------------------------- #
# Changes
# --------------------------------------------------------------------------- #
def _owned_post(session: Any, user_id: str, post_id: str) -> MultipostPost:
    post = session.get(MultipostPost, post_id)
    if post is None or post.user_id != user_id:
        raise CampaignError("post not found", status_code=404)
    return post


def cancel_post(session: Any, user_id: str, post_id: str) -> dict:
    post = _owned_post(session, user_id, post_id)
    if post.status not in (POST_SCHEDULED, POST_HELD):
        raise CampaignError("only posts that have not started can be canceled", status_code=409)
    post.status = POST_CANCELED
    session.flush()
    return post_view(post)


def retry_post(session: Any, user_id: str, post_id: str) -> dict:
    post = _owned_post(session, user_id, post_id)
    if post.status not in (POST_FAILED, POST_HELD):
        raise CampaignError("only failed or held posts can be retried", status_code=409)
    account = acct_service.get_for(session, user_id, post.account_id)
    if account.status != ACCOUNT_CONNECTED:
        raise CampaignError("reconnect this account before retrying", status_code=409)
    post.status = POST_SCHEDULED
    post.next_attempt_at = _now()
    post.attempts = 0
    post.error = ""
    post.provider_status = ""
    post.publish_ref = ""
    session.flush()
    return post_view(post, account)


def cancel_campaign(session: Any, user_id: str, campaign_id: str) -> dict:
    row = _owned_campaign(session, user_id, campaign_id)
    posts = session.execute(select(MultipostPost).where(
        MultipostPost.campaign_id == row.id, MultipostPost.status == POST_SCHEDULED,
    )).scalars().all()
    for post in posts:
        post.status = POST_CANCELED
    row.status = CAMPAIGN_CANCELED
    session.flush()
    return detail(session, user_id, row.id)


__all__ = [
    "CAMPAIGN_ACTIVE", "CampaignError", "CampaignInput", "cancel_campaign", "cancel_post", "create", "detail",
    "list_campaigns", "list_posts", "post_view", "preview", "retry_post",
]
