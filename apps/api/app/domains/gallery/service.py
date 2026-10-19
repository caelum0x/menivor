"""Gallery service (MH3): opt-in publish, public reads, Recreate, remix counting.

* Only an owner's finished, kept, unblocked output can be published, and only
  the preset id plus whitelisted render settings are stored. The script,
  subject, links, voices, avatars and uploads never leave the job row.
* Recreate returns the body of the normal create call with the item's safe
  settings and the caller's own topic or link; money moves only there.
* A remix counts once, when its job is finished and kept (charge on keep:
  paid at create, or kept later). Remixing your own item does not count.
* Only a real Recreate counts (P-M2): the job was created after the item was
  published, it is linked within ``REMIX_LINK_WINDOW`` of its creation (the
  Recreate screen links it right after create), and it carries the item's
  recipe (the shelf preset, or the item's style, camera move and effects).
  Any other finished job is refused at link time and never counted.
* A takedown block hides the item in the same transaction (``on_media_blocked``).
* The MN5 provenance tag is read from :func:`app.services.provenance.provenance_tags`;
  nothing here writes a tag.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import GalleryItem, GalleryRemix

TASK_STATE_COMPLETE = 1
SAFE_PARAM_KEYS: tuple[str, ...] = (
    "style", "camera_motion", "effects", "vfx_intensity", "caption_style", "layout", "background_id",
    "aspect", "hook_style", "target_duration_s", "language", "auto_zoom", "auto_tighten",
)
MAX_TITLE = 80
PAGE_SIZE = 24
WALL_MAX = 6
HIDDEN_TAKEDOWN = "takedown"
#: A Recreate job is linked right after create; later links are not Recreates.
REMIX_LINK_WINDOW = timedelta(minutes=30)
#: The recipe keys a Recreate copies from the item (``recreate_plan``).
RECIPE_KEYS: tuple[str, ...] = ("style", "camera_motion", "effects")
HIDDEN_OWNER = "owner"


class GalleryError(Exception):
    status_code = 400

    def __init__(self, message: str, code: str = "gallery") -> None:
        super().__init__(message)
        self.code = code


class NotFound(GalleryError):
    status_code = 404


class NotReady(GalleryError):
    status_code = 409


def now() -> datetime:
    return datetime.now(timezone.utc)


def media_url(key: str) -> str:
    """A short-lived signed URL for a private result key ("" when unset)."""
    if not key:
        return ""
    from app.platform.storage.r2 import get_r2_client

    return get_r2_client().presign_result_get(key)


def safe_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(params or {})
    return {k: source[k] for k in SAFE_PARAM_KEYS if k in source and source[k] not in (None, "", [], ())}


def preset_id_for(params: Mapping[str, Any] | None) -> str:
    source = dict(params or {})
    run = source.get("preset_run")
    if isinstance(run, Mapping) and run.get("preset_id"):
        return f"shelf:{run['preset_id']}"
    if source.get("style"):
        return f"style:{source['style']}"
    return "reel"


def clean_title(title: str) -> str:
    from app.domains.presets_hub.catalog import vendor_hits

    text = " ".join(str(title or "").split())[:MAX_TITLE]
    if vendor_hits(text):
        raise GalleryError("Titles cannot name tools or models.", "title_vendor")
    return text


def _job_is_kept(params: Mapping[str, Any] | None) -> bool:
    from app.domains.reels import keep

    return not keep.is_pending(dict(params or {}))


def _owned_job(session: Session, job_id: str, user_id: str):
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None or str(job.user_id) != str(user_id) or getattr(job, "deleted_at", None) is not None:
        raise NotFound("job not found")
    return job


def publish(session: Session, *, user_id: str, job_id: str, title: str = "") -> GalleryItem:
    from app.domains.compliance.takedown import is_blocked_in_session

    job = _owned_job(session, job_id, user_id)
    if job.state != TASK_STATE_COMPLETE or not (job.preview_key or job.result_key):
        raise NotReady("only a finished render can be published", "not_finished")
    if not _job_is_kept(job.params):
        raise NotReady("keep this variant before you publish it", "keep_required")
    if is_blocked_in_session(session, job.id):
        raise NotReady("this video is paused while a report is reviewed", "blocked")
    text = clean_title(title)
    existing = session.execute(select(GalleryItem).where(GalleryItem.job_id == job.id)).scalar_one_or_none()
    if existing is not None:
        if existing.hidden_reason == HIDDEN_OWNER:
            existing.hidden_at, existing.hidden_reason = None, ""
        existing.title = text or existing.title
        session.flush()
        return existing
    item = GalleryItem(job_id=job.id, user_id=str(user_id), title=text, preset_id=preset_id_for(job.params),
                       safe_params=safe_params(job.params))
    session.add(item)
    session.flush()
    return item


def unpublish(session: Session, *, user_id: str, item_id: str) -> None:
    item = session.get(GalleryItem, item_id)
    if item is None or str(item.user_id) != str(user_id):
        raise NotFound("item not found")
    if item.hidden_at is None:
        item.hidden_at, item.hidden_reason = now(), HIDDEN_OWNER
    session.flush()


def on_media_blocked(session: Session, job_id: str | None) -> int:
    """Takedown hook: hide the job's gallery item in the caller's transaction.

    Runs in a savepoint and never raises, so a takedown block can never fail
    because of the gallery (public reads also filter blocked jobs).
    """
    if not job_id:
        return 0
    try:
        with session.begin_nested():
            result = session.execute(
                update(GalleryItem)
                .where(GalleryItem.job_id == str(job_id), GalleryItem.hidden_at.is_(None))
                .values(hidden_at=now(), hidden_reason=HIDDEN_TAKEDOWN, wall_approved=False)
            )
        return int(result.rowcount or 0)
    except SQLAlchemyError as exc:
        logger.warning(f"gallery hide for blocked job {job_id} skipped: {type(exc).__name__}")
        return 0


def _visible_query():
    from app.domains.compliance.takedown import STATUS_BLOCKED, TakedownReport
    from app.models.db.models import Job

    blocked = select(TakedownReport.job_id).where(TakedownReport.status == STATUS_BLOCKED,
                                                  TakedownReport.job_id.is_not(None))
    return (
        select(GalleryItem, Job)
        .join(Job, Job.id == GalleryItem.job_id)
        .where(GalleryItem.hidden_at.is_(None), Job.deleted_at.is_(None), GalleryItem.job_id.not_in(blocked))
    )


def item_view(item: GalleryItem, job: Any) -> dict[str, Any]:
    from app.domains.presets_hub import catalog
    from app.services import provenance

    tags = provenance.provenance_tags(job.id)
    kind, _, ref = item.preset_id.partition(":")
    preset = catalog.get(ref) if kind == "shelf" else None
    return {
        "id": item.id,
        "title": item.title,
        "preset_id": item.preset_id,
        "preset_name": preset.name if preset else "",
        "remix_count": int(item.remix_count or 0),
        "preview_url": media_url(job.preview_key or job.result_key),
        "poster_url": media_url(job.poster_key),
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "recreate_url": f"/gallery?recreate={item.id}",
        "provenance": {
            "ai_generated": tags["ai_generated"] == "true",
            "content_id": tags["menivor_content_id"],
            "report_url": provenance.REPORT_URL,
            "generator": tags["generator"],
        },
    }


def list_public(session: Session, *, limit: int = PAGE_SIZE, before: datetime | None = None) -> list[dict]:
    query = _visible_query().order_by(GalleryItem.published_at.desc()).limit(max(1, min(limit, 60)))
    if before is not None:
        query = query.where(GalleryItem.published_at < before)
    return [item_view(item, job) for item, job in session.execute(query).all()]


def get_public(session: Session, item_id: str) -> dict:
    row = session.execute(_visible_query().where(GalleryItem.id == item_id)).first()
    if row is None:
        raise NotFound("item not found")
    return item_view(*row)


def wall(session: Session) -> list[dict]:
    query = (_visible_query().where(GalleryItem.wall_approved.is_(True))
             .order_by(GalleryItem.published_at.desc()).limit(WALL_MAX))
    return [item_view(item, job) for item, job in session.execute(query).all()]


def set_wall(session: Session, item_id: str, approved: bool) -> None:
    item = session.get(GalleryItem, item_id)
    if item is None or (approved and item.hidden_at is not None):
        raise NotFound("item not found")
    item.wall_approved = bool(approved)
    session.flush()


def recreate_plan(session: Session, item_id: str, *, subject: str, image_key: str | None = None) -> dict:
    from app.domains.presets_hub import service as presets

    row = session.execute(_visible_query().where(GalleryItem.id == item_id)).first()
    if row is None:
        raise NotFound("item not found")
    item = row[0]
    kind, _, ref = item.preset_id.partition(":")
    if kind == "shelf":
        try:
            plan = presets.resolve(ref, subject=subject, image_key=image_key)
        except presets.PresetInputError as exc:
            raise GalleryError(str(exc), "recreate_input") from exc
        except presets.PresetNotFound as exc:
            raise NotFound("preset not found") from exc
        return {**plan, "item_id": item.id}
    try:
        params = {**presets.subject_params(subject), **dict(item.safe_params or {})}
    except presets.PresetInputError as exc:
        raise GalleryError(str(exc), "recreate_input") from exc
    return {"route": "jobs", "body": {"params": params, "variants": 1}, "item_id": item.id}


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _carries_recipe(item: GalleryItem, params: Mapping[str, Any]) -> bool:
    """Whether a job's settings are the item's recipe (what ``recreate_plan`` returns)."""
    kind, _, ref = item.preset_id.partition(":")
    if kind == "shelf":
        from app.domains.presets_hub import catalog

        run = params.get("preset_run")
        if isinstance(run, Mapping) and str(run.get("preset_id") or "") == ref:
            return True
        preset = catalog.get(ref)
        if preset is None:
            return False
        if preset.kind == catalog.KIND_FILTER:
            return (params.get("camera_motion") == preset.camera_motion
                    and list(params.get("effects") or []) == list(preset.effects))
        head = preset.prompt_template.split("{subject}")[0].strip()
        return bool(head) and head in str(params.get("prompt") or "")
    recipe = {k: v for k, v in dict(item.safe_params or {}).items() if k in RECIPE_KEYS}
    return all(params.get(k) == v for k, v in recipe.items())


def is_recreate_of(item: GalleryItem, job: Any, *, linked_at: datetime | None = None) -> bool:
    """P-M2: the job was made with Recreate from this item (timing and recipe)."""
    created = _utc(getattr(job, "created_at", None))
    published = _utc(item.published_at)
    if created is None or published is None or created < published:
        return False
    if (linked_at or now()) - created > REMIX_LINK_WINDOW:
        return False
    return _carries_recipe(item, dict(job.params or {}))


def link_remix(session: Session, *, item_id: str, user_id: str, job_id: str) -> GalleryRemix:
    item = session.get(GalleryItem, item_id)
    if item is None or item.hidden_at is not None:
        raise NotFound("item not found")
    job = _owned_job(session, job_id, user_id)
    if str(item.user_id) == str(user_id):
        raise NotReady("remixes of your own item do not count", "self_remix")
    existing = session.execute(select(GalleryRemix).where(GalleryRemix.job_id == job_id)).scalar_one_or_none()
    if existing is not None:
        return existing
    if not is_recreate_of(item, job):
        raise NotReady("only a video made with Recreate from this item counts", "not_a_recreate")
    remix = GalleryRemix(item_id=item.id, job_id=job_id, user_id=str(user_id))
    session.add(remix)
    session.flush()
    return remix


def _settle_one(session: Session, remix: GalleryRemix) -> bool:
    from app.models.db.models import Job

    job = session.get(Job, remix.job_id)
    if job is None or job.state != TASK_STATE_COMPLETE or not _job_is_kept(job.params):
        return False
    item = session.get(GalleryItem, remix.item_id)
    if item is None or not is_recreate_of(item, job, linked_at=_utc(remix.created_at)):
        return False
    claimed = session.execute(
        update(GalleryRemix).where(GalleryRemix.id == remix.id, GalleryRemix.counted_at.is_(None))
        .values(counted_at=now())
    ).rowcount
    if not claimed:
        return False
    session.execute(update(GalleryItem).where(GalleryItem.id == remix.item_id)
                    .values(remix_count=GalleryItem.remix_count + 1))
    return True


def settle_remixes(session: Session, *, limit: int = 500) -> int:
    """Count every kept remix once; safe to run concurrently (compare-and-set)."""
    pending = session.execute(
        select(GalleryRemix).where(GalleryRemix.counted_at.is_(None)).order_by(GalleryRemix.created_at).limit(limit)
    ).scalars().all()
    counted = sum(1 for remix in pending if _settle_one(session, remix))
    session.flush()
    return counted


def remix_view(session: Session, *, user_id: str, job_id: str) -> dict:
    remix = session.execute(select(GalleryRemix).where(GalleryRemix.job_id == job_id)).scalar_one_or_none()
    if remix is None or str(remix.user_id) != str(user_id):
        raise NotFound("remix not found")
    if remix.counted_at is None:
        _settle_one(session, remix)
        session.flush()
        session.refresh(remix)
    return {"job_id": job_id, "item_id": remix.item_id, "counted": remix.counted_at is not None}
