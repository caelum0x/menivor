"""OTT catalog and CMS rules (MV1).

* One channel per creator, created on first use with a handle from the
  creator's profile (or email name), unique and URL-safe.
* A title comes from the creator's own finished, kept render (or an MV2 upload).
* **Compliance gate** before a title is published: the source is not
  takedown-blocked, its stored pre-publish content verdict is not ``block``,
  its title and synopsis name no tool or model (the copy denylist rule), and
  an uploaded title has passed the upload content check (QM1.2).
* Unpublish or takedown hides a title at once; public reads are cached for at
  most 30 s, so it is gone everywhere within 60 s.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import or_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import (
    ACCESS_TIERS, GEO_MODES, HIDDEN_GATE, HIDDEN_OWNER, HIDDEN_TAKEDOWN, KINDS, LAYOUTS, STATUS_DRAFT, STATUS_HIDDEN,
    STATUS_PUBLISHED, OttChannel, OttCollection, OttSeries, OttTitle,
)
from .repository import OttRepository

TASK_STATE_COMPLETE = 1
MAX_HANDLE = 40
_HANDLE = re.compile(r"[^a-z0-9-]+")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
RATINGS = ("", "G", "PG", "PG-13", "R", "TV-Y", "TV-G", "TV-PG", "TV-14", "TV-MA")


class OttError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def now() -> datetime:
    return datetime.now(timezone.utc)


def clean_handle(raw: str) -> str:
    handle = _HANDLE.sub("-", str(raw or "").strip().lower()).strip("-")[:MAX_HANDLE]
    return handle


def _vendor_check(*texts: str) -> None:
    from app.domains.presets_hub.catalog import vendor_hits

    if vendor_hits(" ".join(t for t in texts if t)):
        raise OttError(400, "copy_vendor", "titles and descriptions cannot name tools or models")


# --------------------------------------------------------------------------- #
# Channel
# --------------------------------------------------------------------------- #
def _suggest_handle(session: Session, user_id: str) -> str:
    from app.models.db.models import User

    user = session.get(User, user_id)
    base = str(getattr(user, "handle", "") or "") if user is not None else ""
    if not base and user is not None:
        base = str(getattr(user, "email", "") or "").split("@")[0]
    base = clean_handle(base) or "channel"
    repo = OttRepository(session)
    candidate, n = base, 1
    while repo.handle_taken(candidate):
        n += 1
        candidate = f"{base[:MAX_HANDLE - 4]}-{n}"
    return candidate


def ensure_channel(session: Session, user_id: str) -> OttChannel:
    repo = OttRepository(session)
    channel = repo.channel_for_user(user_id)
    if channel is not None:
        return channel
    handle = _suggest_handle(session, user_id)
    return repo.add(OttChannel(user_id=user_id, handle=handle, title=handle.replace("-", " ").title(),
                               brand_colors=[]))


def update_channel(session: Session, user_id: str, body: Mapping[str, Any]) -> OttChannel:
    channel = ensure_channel(session, user_id)
    if body.get("handle") is not None:
        handle = clean_handle(body["handle"])
        if len(handle) < 3:
            raise OttError(400, "handle", "a handle needs at least 3 letters or digits")
        taken = OttRepository(session).channel_by_handle(handle)
        if taken is not None and taken.id != channel.id:
            raise OttError(409, "handle_taken", "that handle is taken")
        channel.handle = handle
    if body.get("layout") is not None:
        if body["layout"] not in LAYOUTS:
            raise OttError(400, "layout", f"layout is one of {', '.join(LAYOUTS)}")
        channel.layout = body["layout"]
    if body.get("brand_colors") is not None:
        colors = [c for c in body["brand_colors"] if _COLOR.match(str(c))]
        if len(colors) != len(body["brand_colors"]):
            raise OttError(400, "colors", "colours are #RRGGBB")
        channel.brand_colors = colors
    for field in ("title", "tagline"):
        if body.get(field) is not None:
            text = " ".join(str(body[field]).split())
            _vendor_check(text)
            setattr(channel, field, text)
    session.flush()
    return channel


# --------------------------------------------------------------------------- #
# Titles
# --------------------------------------------------------------------------- #
def _owned_render(session: Session, user_id: str, job_id: str):
    from app.domains.reels import keep
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None or str(job.user_id) != str(user_id) or getattr(job, "deleted_at", None) is not None:
        raise OttError(404, "not_found", "render not found")
    if job.state != TASK_STATE_COMPLETE or not job.result_key:
        raise OttError(409, "not_finished", "only a finished render can become a title")
    if keep.is_pending(dict(job.params or {})):
        raise OttError(409, "keep_required", "keep this variant first")
    return job


def _job_title(job: Any) -> str:
    params = dict(job.params or {})
    text = str(getattr(job, "title", "") or params.get("video_subject") or "Untitled")
    return " ".join(text.split())[:120] or "Untitled"


def gate(session: Session, title: OttTitle) -> str | None:
    """Why a title may not be published (``None`` when it may)."""
    from app.domains.compliance.takedown import is_blocked_in_session
    from app.domains.presets_hub.catalog import vendor_hits
    from app.models.db.models import Job

    if is_blocked_in_session(session, title.id):  # a report naming the title itself (uploads have no job)
        return "this video is paused while a report is reviewed"
    if title.source_job_id:
        if is_blocked_in_session(session, title.source_job_id):
            return "this video is paused while a report is reviewed"
        job = session.get(Job, title.source_job_id)
        verdict = (dict(getattr(job, "stages", None) or {}).get("_content_gate") or {}) if job else {}
        if isinstance(verdict, Mapping) and verdict.get("decision") == "block":
            return "the content check held this video"
    if vendor_hits(" ".join([title.title, title.synopsis])):
        return "titles and descriptions cannot name tools or models"
    from .upload_check import gate_reason  # Wave Q QM1.2 (P-M5): uploads pass the content check first

    return gate_reason(session, title)


def add_title(session: Session, user_id: str, job_id: str) -> OttTitle:
    channel = ensure_channel(session, user_id)
    repo = OttRepository(session)
    existing = repo.title_for_job(channel.id, job_id)
    if existing is not None:
        return existing
    job = _owned_render(session, user_id, job_id)
    duration = float(dict(job.params or {}).get("target_duration_s") or 0)
    position = len(repo.titles(channel.id))
    return repo.add(OttTitle(channel_id=channel.id, source_job_id=job.id, title=_job_title(job),
                             artwork_key=str(job.poster_key or ""), duration_s=duration, genres=[],
                             geo_countries=[], position=position))


def _own_title(session: Session, user_id: str, title_id: str) -> OttTitle:
    channel = OttRepository(session).channel_for_user(user_id)
    title = OttRepository(session).title(channel.id, title_id) if channel else None
    if title is None:
        raise OttError(404, "not_found", "title not found")
    return title


def update_title(session: Session, user_id: str, title_id: str, body: Mapping[str, Any]) -> OttTitle:
    title = _own_title(session, user_id, title_id)
    if body.get("title") is not None or body.get("synopsis") is not None:
        _vendor_check(str(body.get("title") or ""), str(body.get("synopsis") or ""))
    checks = {"kind": KINDS, "access_tier": ACCESS_TIERS, "geo_mode": GEO_MODES, "rating": RATINGS}
    for field, allowed in checks.items():
        if body.get(field) is not None and body[field] not in allowed:
            raise OttError(400, field, f"{field} is one of {', '.join(a or 'none' for a in allowed)}")
    if body.get("geo_countries") is not None:
        countries = [str(c).upper() for c in body["geo_countries"]]
        if not all(_COUNTRY.match(c) for c in countries):
            raise OttError(400, "geo_countries", "countries are two-letter codes")
        title.geo_countries = sorted(set(countries))
    if body.get("genres") is not None:
        title.genres = [" ".join(str(g).split())[:30] for g in body["genres"] if str(g).strip()]
    if body.get("credits") is not None:
        title.credits = clean_credits(body["credits"])
    if body.get("series_id") is not None:
        series = session.get(OttSeries, body["series_id"])
        if series is None or series.channel_id != title.channel_id:
            raise OttError(404, "series", "series not found")
        title.series_id = series.id
    was_free = title.access_tier == "free"
    start, end = body.get("available_from"), body.get("available_until")
    if start and end and end <= start:
        raise OttError(400, "availability", "the end of the window must be after its start")
    for field in ("title", "synopsis", "kind", "rating", "season", "episode", "available_from", "available_until",
                  "access_tier", "geo_mode", "position"):
        if body.get(field) is not None:
            setattr(title, field, body[field])
    session.flush()
    if was_free and title.access_tier != "free":
        _protect_after_tier_change(session, title, user_id)
    return title


def _protect_after_tier_change(session: Session, title: OttTitle, user_id: str) -> None:
    """Free to paid (Wave Q QM1.2, P-M7): new key, re-encrypt; the title is unwatchable until packaged."""
    from sqlalchemy import event

    from app.services.ott_transcode import service as transcode
    from app.services.ott_transcode.models import LANE_BOX1

    from . import events

    # QM verify: a title that is live now was announced; record it before the re-encrypt makes it
    # unwatchable, so the re-packaging finish never sends ott.title.published or the push again.
    events.mark_announced_if_live(session, title)
    job = transcode.requeue_protected(session, title, user_id=user_id)
    if job is not None and job.lane == LANE_BOX1:
        job_id = job.id

        def _enqueue(_session) -> None:
            from app.services.ott_transcode.router import enqueue_box1

            enqueue_box1(job_id)

        event.listen(session, "after_commit", _enqueue, once=True)


def publish_title(session: Session, user_id: str, title_id: str) -> OttTitle:
    title = _own_title(session, user_id, title_id)
    reason = gate(session, title)
    if reason:
        raise OttError(409, "compliance_gate", reason)
    title.status, title.hidden_reason = STATUS_PUBLISHED, ""
    title.published_at = title.published_at or now()
    channel = session.get(OttChannel, title.channel_id)
    if channel.status != STATUS_PUBLISHED:
        channel.status, channel.published_at = STATUS_PUBLISHED, channel.published_at or now()
    session.flush()
    # Wave Q QM1.5 (U39) + QM verify: ott.title.published and the new-episode push go out once per title,
    # after commit, and only when it is watchable. Not packaged yet: the packaging finish announces it.
    from . import events

    events.maybe_title_published(session, title)
    return title


def unpublish_title(session: Session, user_id: str, title_id: str) -> OttTitle:
    title = _own_title(session, user_id, title_id)
    title.status, title.hidden_reason = STATUS_HIDDEN, HIDDEN_OWNER
    session.flush()
    return title


def on_media_blocked(session: Session, job_id: str | None) -> int:
    """Takedown hook: hide every OTT title made from the blocked job, or the blocked title itself (never raises)."""
    if not job_id:
        return 0
    try:
        with session.begin_nested():
            media = or_(OttTitle.source_job_id == str(job_id), OttTitle.id == str(job_id))
            result = session.execute(update(OttTitle).where(media, OttTitle.status != STATUS_HIDDEN)
                                     .values(status=STATUS_HIDDEN, hidden_reason=HIDDEN_TAKEDOWN))
        return int(result.rowcount or 0)
    except SQLAlchemyError:
        return 0


def sweep_gate(session: Session, *, limit: int = 500) -> int:
    """Hide published titles that fail the gate now (a missed hook or a later verdict)."""
    from sqlalchemy import select

    hidden = 0
    rows = session.execute(select(OttTitle).where(OttTitle.status == STATUS_PUBLISHED).limit(limit)).scalars().all()
    for title in rows:
        reason = gate(session, title)
        if reason:
            title.status = STATUS_HIDDEN
            title.hidden_reason = HIDDEN_TAKEDOWN if "report" in reason else HIDDEN_GATE
            hidden += 1
    session.flush()
    return hidden


def create_series(session: Session, user_id: str, title: str, synopsis: str = "") -> OttSeries:
    channel = ensure_channel(session, user_id)
    _vendor_check(title, synopsis)
    position = len(OttRepository(session).series(channel.id))
    return OttRepository(session).add(OttSeries(channel_id=channel.id, title=title.strip(), synopsis=synopsis,
                                                position=position))


def create_collection(session: Session, user_id: str, title: str, title_ids: list[str]) -> OttCollection:
    channel = ensure_channel(session, user_id)
    _vendor_check(title)
    repo = OttRepository(session)
    owned = {t.id for t in repo.titles(channel.id)}
    if any(tid not in owned for tid in title_ids):
        raise OttError(404, "title", "a title in this rail is not yours")
    return repo.add(OttCollection(channel_id=channel.id, title=title.strip(), title_ids=list(title_ids),
                                  position=len(repo.collections(channel.id))))


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
def _url(key: str) -> str:
    from app.domains.gallery.service import media_url

    return media_url(key)


MAX_CREDITS = 30


def clean_credits(raw: Any) -> list[dict[str, str]]:
    """Cast and crew lines: name and role, trimmed, at most 30, empty lines dropped."""
    out = []
    for item in list(raw or [])[:MAX_CREDITS]:
        name = " ".join(str((item or {}).get("name") or "").split())[:80]
        role = " ".join(str((item or {}).get("role") or "").split())[:40]
        if name and role:
            out.append({"name": name, "role": role})
    return out


def title_view(title: OttTitle) -> dict[str, Any]:
    return {
        "id": title.id, "title": title.title, "synopsis": title.synopsis, "kind": title.kind,
        "series_id": title.series_id, "season": title.season, "episode": title.episode,
        "artwork_url": _url(title.artwork_key), "duration_s": title.duration_s, "genres": list(title.genres or []),
        "rating": title.rating, "access_tier": title.access_tier, "geo_mode": title.geo_mode,
        "geo_countries": list(title.geo_countries or []), "status": title.status,
        "hidden_reason": title.hidden_reason, "package_status": title.package_status, "position": title.position,
        "available_from": title.available_from.isoformat() if title.available_from else None,
        "available_until": title.available_until.isoformat() if title.available_until else None,
        "source_job_id": title.source_job_id, "credits": list(title.credits or []),
    }


def channel_view(session: Session, channel: OttChannel) -> dict[str, Any]:
    repo = OttRepository(session)
    return {
        "id": channel.id, "handle": channel.handle, "title": channel.title, "tagline": channel.tagline,
        "layout": channel.layout, "brand_colors": list(channel.brand_colors or []), "status": channel.status,
        "storefront_path": f"/c/{channel.handle}",
        "titles": [title_view(t) for t in repo.titles(channel.id)],
        "series": [{"id": s.id, "title": s.title, "synopsis": s.synopsis} for s in repo.series(channel.id)],
        "collections": [{"id": c.id, "title": c.title, "title_ids": list(c.title_ids or [])}
                        for c in repo.collections(channel.id)],
    }


__all__ = ["OttError", "add_title", "channel_view", "clean_handle", "create_collection", "create_series",
           "ensure_channel", "gate", "on_media_blocked", "publish_title", "sweep_gate", "title_view",
           "unpublish_title", "update_channel", "update_title", "STATUS_DRAFT"]
