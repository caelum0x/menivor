"""Launch Kit: first-100-users tooling (Menivor Growth phase 3,
plans/menivor.md "Menivor Growth").

Four read tools plus the small write surface each one needs to persist state:

* :func:`list_launch_platforms` -- the curated directory catalog
  (:mod:`app.domains.launch_kit.catalog`) plus this user's per-product
  submission state; :func:`set_platform_status` records that state (a human
  reports what they did -- nothing here submits anything on a directory).
* :func:`find_pain_point_threads` -- live, public, read-only Reddit search
  (:mod:`app.domains.launch_kit.reddit_search`); drafts a reply per thread
  and saves it as a :class:`~app.domains.launch_kit.models.PainPointDraft`
  for a human to read, edit and post by hand. ``approve_pain_point_draft`` /
  ``dismiss_pain_point_draft`` only ever change local status; nothing here
  ever calls Reddit's comment/vote APIs, so there is no code path that could
  spam or violate Reddit's self-promotion rules on its own.
* :func:`find_competitor_backlinks` -- wraps
  :mod:`app.domains.launch_kit.backlinks` (gated on DataForSEO credentials
  and an explicit ``allow_live`` flag so it never spends credits by itself).
* :func:`get_launch_checklist` -- the 10-step playbook
  (:mod:`app.domains.launch_kit.catalog.PLAYBOOK_STEPS`) for one product,
  done/pending from :class:`~app.domains.launch_kit.models.PlaybookStepStatus`
  plus the "launch everywhere" step derived from platform submissions;
  :func:`mark_playbook_step` records a step done/pending by hand.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.domains.adstudio.extract import clean_text
from app.domains.launch_kit import backlinks as backlinks_source
from app.domains.launch_kit import catalog
from app.domains.launch_kit import reddit_search
from app.domains.launch_kit.models import LaunchPlatformStatus, PainPointDraft, PlaybookStepStatus

PLATFORM_STATUSES = ("not_started", "submitted", "live")
STEP_STATUSES = ("pending", "done")
DRAFT_STATUSES = ("drafted", "approved", "dismissed")
MAX_PRODUCT_NAME = 200
MAX_QUERY = 300
DEFAULT_SEARCH_LIMIT = 10


class LaunchKitError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware else None


def _product(name: Any) -> str:
    title = clean_text(name, MAX_PRODUCT_NAME)
    if not title:
        raise LaunchKitError("product_name is required", 422)
    return title


# --------------------------------------------------------------------------- #
# 1. list_launch_platforms
# --------------------------------------------------------------------------- #
def list_launch_platforms(session: Any, user_id: str, *, product_name: str | None = None,
                          product_category: str | None = None) -> dict[str, Any]:
    """The curated directory catalog, optionally filtered to one category, with this user's
    per-product submission state merged in when ``product_name`` is given."""
    platforms = catalog.platforms_for_category(product_category)
    status_by_platform: dict[str, LaunchPlatformStatus] = {}
    if product_name:
        title = _product(product_name)
        rows = session.execute(select(LaunchPlatformStatus).where(
            LaunchPlatformStatus.user_id == user_id, LaunchPlatformStatus.product_name == title)).scalars().all()
        status_by_platform = {r.platform_id: r for r in rows}
    out = []
    for p in platforms:
        row = status_by_platform.get(p["id"])
        out.append({
            "id": p["id"], "name": p["name"], "url": p["url"], "categories": list(p["categories"]), "note": p["note"],
            "status": row.status if row else "not_started",
            "submitted_at": _iso(row.submitted_at) if row else None,
            "tracking_note": row.note if row else "",
        })
    return {"platforms": out, "category": product_category or "", "product_name": product_name or ""}


def set_platform_status(session: Any, user_id: str, *, product_name: str, platform_id: str, status: str,
                        note: str = "", now: datetime | None = None) -> dict[str, Any]:
    """Record what a human actually did on one directory. This never submits anything itself --
    it only remembers that the owner (or a teammate) submitted, so the checklist and the next
    `list_launch_platforms` call reflect reality."""
    title = _product(product_name)
    pid = str(platform_id or "").strip()
    if pid not in catalog.PLATFORM_BY_ID:
        raise LaunchKitError(f"unknown platform_id {pid!r}; see list_launch_platforms", 422)
    clean_status = str(status or "").strip().lower()
    if clean_status not in PLATFORM_STATUSES:
        raise LaunchKitError(f"status must be one of {', '.join(PLATFORM_STATUSES)}", 422)
    moment = now or _now()
    row = session.execute(select(LaunchPlatformStatus).where(
        LaunchPlatformStatus.user_id == user_id, LaunchPlatformStatus.product_name == title,
        LaunchPlatformStatus.platform_id == pid)).scalar_one_or_none()
    if row is None:
        row = LaunchPlatformStatus(user_id=user_id, product_name=title, platform_id=pid)
        session.add(row)
    row.status = clean_status
    row.note = clean_text(note, 500)
    row.updated_at = moment
    if clean_status != "not_started" and row.submitted_at is None:
        row.submitted_at = moment
    if clean_status == "not_started":
        row.submitted_at = None
    session.flush()
    return {"product_name": title, "platform_id": pid, "status": row.status, "submitted_at": _iso(row.submitted_at),
            "note": row.note}


# --------------------------------------------------------------------------- #
# 2. find_pain_point_threads
# --------------------------------------------------------------------------- #
def _draft_reply(thread_title: str, snippet: str, product_name: str) -> str:
    """A value-first starting point for a human to edit before posting -- never posted by this
    service. Mentions the product once, near the end, after acknowledging the actual problem."""
    name = product_name.strip() or "the tool we built"
    hook = thread_title.strip().rstrip("?.!") or "this"
    body = snippet.strip()[:220]
    lead = f"Ran into the same thing with {hook.lower()}." if hook else "Ran into the same thing."
    middle = f" {body}" if body else ""
    return (f"{lead}{middle} What helped us was narrowing it down to one root cause before changing "
            f"anything -- happy to share specifics if useful. (We ended up building {name} for exactly "
            f"this, so take that with a grain of salt, but the debugging approach is the real value here.)")


def find_pain_point_threads(session: Any, user_id: str, *, query: str, subreddits: list[str] | None = None,
                            product_name: str = "", limit: int = DEFAULT_SEARCH_LIMIT,
                            transport: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """Search Reddit's public search for threads about ``query`` and draft a reply for each one.
    Read-only against Reddit (see :mod:`app.domains.launch_kit.reddit_search`); every result is
    saved as a :class:`PainPointDraft` with status ``drafted`` so a human can review, edit and
    post it later -- this function itself never posts anything."""
    q = clean_text(query, MAX_QUERY)
    if not q:
        raise LaunchKitError("query is required", 422)
    http = transport
    if http is None:
        from app.domains.integrations.connectors.base import RequestsTransport

        http = RequestsTransport()
    try:
        threads = reddit_search.search(http, query=q, subreddits=subreddits, limit=limit)
    except reddit_search.RedditSearchError as exc:
        raise LaunchKitError(exc.message, exc.status_code) from exc
    moment = now or _now()
    title = clean_text(product_name, MAX_PRODUCT_NAME)
    existing_urls = {r.thread_url for r in session.execute(select(PainPointDraft).where(
        PainPointDraft.user_id == user_id, PainPointDraft.query == q)).scalars().all()}
    saved: list[dict[str, Any]] = []
    for thread in threads:
        reply = _draft_reply(thread.title, thread.snippet, title)
        if thread.url not in existing_urls:
            row = PainPointDraft(user_id=user_id, product_name=title, query=q, subreddit=thread.subreddit,
                                 thread_url=thread.url, thread_title=thread.title, snippet=thread.snippet,
                                 upvotes=thread.upvotes, age_days=thread.age_days, draft_reply=reply,
                                 status="drafted", raw=dict(thread.raw), created_at=moment)
            session.add(row)
            existing_urls.add(thread.url)
        saved.append({"thread_url": thread.url, "thread_title": thread.title, "snippet": thread.snippet,
                      "subreddit": thread.subreddit, "upvotes": thread.upvotes, "age_days": thread.age_days,
                      "draft_reply": reply})
    session.flush()
    return {"query": q, "threads": saved, "count": len(saved),
            "note": "Drafts only. Review and post these yourself -- nothing here posts to Reddit."}


def _draft_view(row: PainPointDraft) -> dict[str, Any]:
    return {"id": row.id, "product_name": row.product_name, "query": row.query, "subreddit": row.subreddit,
            "thread_url": row.thread_url, "thread_title": row.thread_title, "snippet": row.snippet,
            "upvotes": row.upvotes, "age_days": row.age_days, "draft_reply": row.draft_reply,
            "status": row.status, "created_at": _iso(row.created_at)}


def list_pain_point_drafts(session: Any, user_id: str, *, status: str | None = None,
                           product_name: str | None = None) -> list[dict[str, Any]]:
    stmt = select(PainPointDraft).where(PainPointDraft.user_id == user_id)
    if status:
        stmt = stmt.where(PainPointDraft.status == status)
    if product_name:
        stmt = stmt.where(PainPointDraft.product_name == _product(product_name))
    rows = session.execute(stmt.order_by(PainPointDraft.created_at.desc())).scalars().all()
    return [_draft_view(r) for r in rows]


def _owned_draft(session: Any, user_id: str, draft_id: str) -> PainPointDraft:
    row = session.get(PainPointDraft, draft_id) if draft_id else None
    if row is None or row.user_id != user_id:
        raise LaunchKitError("draft not found", 404)
    return row


def set_pain_point_draft_status(session: Any, user_id: str, draft_id: str, status: str) -> dict[str, Any]:
    """Human review only: mark a draft ``approved`` (ready to post, by a person) or ``dismissed``.
    There is no ``posted`` status here and no function that posts -- see the module docstring."""
    clean_status = str(status or "").strip().lower()
    if clean_status not in ("approved", "dismissed", "drafted"):
        raise LaunchKitError("status must be one of approved, dismissed, drafted", 422)
    row = _owned_draft(session, user_id, draft_id)
    row.status = clean_status
    session.flush()
    return _draft_view(row)


# --------------------------------------------------------------------------- #
# 3. find_competitor_backlinks
# --------------------------------------------------------------------------- #
def find_competitor_backlinks(domain: str, *, transport: Any = None, allow_live: bool = False) -> dict[str, Any]:
    try:
        return backlinks_source.fetch(domain, transport=transport, allow_live=allow_live)
    except backlinks_source.BacklinkError as exc:
        raise LaunchKitError(exc.message, exc.status_code) from exc


# --------------------------------------------------------------------------- #
# 4. get_launch_checklist
# --------------------------------------------------------------------------- #
def mark_playbook_step(session: Any, user_id: str, *, product_name: str, step_key: str, status: str,
                       note: str = "", now: datetime | None = None) -> dict[str, Any]:
    title = _product(product_name)
    key = str(step_key or "").strip().lower()
    if key not in catalog.STEP_BY_KEY:
        raise LaunchKitError(f"unknown step_key {key!r}; see get_launch_checklist", 422)
    clean_status = str(status or "").strip().lower()
    if clean_status not in STEP_STATUSES:
        raise LaunchKitError(f"status must be one of {', '.join(STEP_STATUSES)}", 422)
    moment = now or _now()
    row = session.execute(select(PlaybookStepStatus).where(
        PlaybookStepStatus.user_id == user_id, PlaybookStepStatus.product_name == title,
        PlaybookStepStatus.step_key == key)).scalar_one_or_none()
    if row is None:
        row = PlaybookStepStatus(user_id=user_id, product_name=title, step_key=key)
        session.add(row)
    row.status = clean_status
    row.note = clean_text(note, 500)
    row.updated_at = moment
    session.flush()
    return {"product_name": title, "step_key": key, "status": row.status, "note": row.note}


def get_launch_checklist(session: Any, user_id: str, *, product_name: str) -> dict[str, Any]:
    """Per-product status of the 10-step distribution playbook. ``launch_everywhere`` is derived
    from platform submissions (done once any platform is submitted/live and not overridden);
    every other step reads :class:`PlaybookStepStatus`, defaulting to pending when never touched."""
    title = _product(product_name)
    known = catalog.is_known_product(title)
    platform_rows = session.execute(select(LaunchPlatformStatus).where(
        LaunchPlatformStatus.user_id == user_id, LaunchPlatformStatus.product_name == title)).scalars().all()
    submitted_platforms = [r.platform_id for r in platform_rows if r.status in ("submitted", "live")]
    step_rows = {r.step_key: r for r in session.execute(select(PlaybookStepStatus).where(
        PlaybookStepStatus.user_id == user_id, PlaybookStepStatus.product_name == title)).scalars().all()}
    steps = []
    for s in catalog.PLAYBOOK_STEPS:
        row = step_rows.get(s["key"])
        if row is not None:
            status, note, updated_at = row.status, row.note, _iso(row.updated_at)
        elif s["key"] == "launch_everywhere" and submitted_platforms:
            status, note, updated_at = "done", f"{len(submitted_platforms)} platform(s) submitted/live.", None
        else:
            status, note, updated_at = "pending", "", None
        steps.append({"key": s["key"], "title": s["title"], "detail": s["detail"], "status": status, "note": note,
                      "updated_at": updated_at})
    done = sum(1 for s in steps if s["status"] == "done")
    if not known:
        logger.info(f"launch_kit: checklist requested for a product not in the portfolio catalog: {title!r}")
    return {"product_name": title, "known_product": known, "steps": steps, "done": done, "total": len(steps),
            "platforms_submitted": submitted_platforms}


__all__ = [
    "DRAFT_STATUSES", "LaunchKitError", "PLATFORM_STATUSES", "STEP_STATUSES", "find_competitor_backlinks",
    "find_pain_point_threads", "get_launch_checklist", "list_launch_platforms", "list_pain_point_drafts",
    "mark_playbook_step", "set_pain_point_draft_status", "set_platform_status",
]
