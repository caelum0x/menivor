"""Approval actions for the Wave L producers: Design Studio, URL capture, store catalog.

Approving one of these items does the work the item describes, through each
subsystem's existing service:

* ``design_publish`` (pushed by :func:`app.domains.design.service.schedule`):
  approve queues one image post per chosen platform at the scheduled time
  (:func:`app.domains.publishing.extended.images.create_image_posts`);
  platforms that cannot take images, or are not connected, are listed in the
  result with their reason. Reject returns the design to "exported".
* ``capture_publish`` (scanned from finished captures of the last
  :data:`RECENT_DAYS` days): approve creates one captions-only reel job per
  captured format from its ``screen_recording_key`` (credits are debited like
  ``POST /jobs``; the summary states the cost). Reject only dismisses the item.
* ``catalog_import`` (scanned from recent store imports): approve creates the
  Ad Studio project for the product and queues its default free variants
  (showcase ads rendered locally, no provider spend). Reject only dismisses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.domains.approvals.adapters import Adapter, ApprovalExecError, Candidate, _clip
from app.domains.approvals.models import (
    RISK_LOW,
    RISK_MEDIUM,
    SOURCE_CAPTURE_PUBLISH,
    SOURCE_CATALOG_IMPORT,
    SOURCE_DESIGN_PUBLISH,
    ApprovalItem,
)

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover - the service reports the import failure
    get_session = None  # type: ignore[assignment]

#: Finished captures / store imports newer than this show up in the feed.
RECENT_DAYS = 14
SCAN_LIMIT = 100
#: Default Ad Studio batch for an approved catalog product (free local renders).
DEFAULT_ANGLES = 2
DEFAULT_FORMATS = ("showcase",)
DEFAULT_ASPECTS = ("9:16",)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_session() -> None:
    if get_session is None:
        raise ApprovalExecError("persistence is not available", status_code=503)


def _item_payload(user_id: str, source: str, ref: str) -> dict:
    with get_session() as session:  # type: ignore[misc]
        row = session.execute(
            select(ApprovalItem).where(ApprovalItem.user_id == user_id, ApprovalItem.source == source,
                                       ApprovalItem.external_ref == ref)
        ).scalar_one_or_none()
        return dict(row.payload or {}) if row is not None else {}


def _no_scan(_session: Any, _user_id: str) -> tuple[list[Candidate], bool]:
    """Producer-pushed source: nothing to mirror, and never expire on sync."""
    return [], False


# --------------------------------------------------------------------------- #
# design_publish
# --------------------------------------------------------------------------- #
def _parse_when(raw: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _approve_design(user_id: str, ref: str, edits: dict) -> dict:
    _require_session()
    from app.domains.design.models import DesignDoc
    from app.domains.publishing.extended.images import ImagePostError, create_image_posts

    payload = _item_payload(user_id, SOURCE_DESIGN_PUBLISH, ref)
    with get_session() as session:  # type: ignore[misc]
        doc = session.get(DesignDoc, ref)
        if doc is None or doc.user_id != user_id:
            raise ApprovalExecError("the design was deleted", status_code=404, gone=True)
        title = doc.title or "Design"
    keys = [str(k) for k in payload.get("image_keys") or []]
    caption = str(edits.get("caption") if "caption" in edits else payload.get("caption") or "")
    try:
        out = create_image_posts(
            user_id, image_keys=keys, platforms=list(payload.get("platforms") or []), caption=caption,
            title=title, scheduled_at=_parse_when(payload.get("scheduled_at")),
            channel_ids=[str(c) for c in payload.get("channel_ids") or []],
            source={"kind": "design", "design_id": ref},
        )
    except ImagePostError as exc:
        reasons = "; ".join(f"{d['platform']}: {d['message']}" for d in exc.details)
        raise ApprovalExecError(f"{exc}{': ' + reasons if reasons else ''}"[:1000],
                                status_code=exc.status_code) from exc
    posts = out["posts"]
    return {
        "action": "design_scheduled",
        "post_ids": [p["id"] for p in posts],
        "posts": [{"id": p["id"], "platform": p["platform"], "status": p["status"],
                   "scheduled_at": p["scheduled_at"],
                   **({"channel_label": p["channel_label"]} if p.get("channel_label") else {})} for p in posts],
        "skipped": out["skipped"],
        "open_path": "/publish",
    }


def _reject_design(user_id: str, ref: str) -> dict:
    _require_session()
    from app.domains.design.models import STATUS_EXPORTED, STATUS_SCHEDULED, DesignDoc

    with get_session() as session:  # type: ignore[misc]
        doc = session.get(DesignDoc, ref)
        if doc is not None and doc.user_id == user_id and doc.status == STATUS_SCHEDULED:
            doc.status = STATUS_EXPORTED
    return {"action": "design_unscheduled", "design_id": ref}


# --------------------------------------------------------------------------- #
# capture_publish
# --------------------------------------------------------------------------- #
def _capture_outputs(meta: dict) -> list[dict]:
    return [dict(o) for o in (meta or {}).get("outputs") or [] if isinstance(o, dict) and o.get("key")]


def _scan_capture(session: Any, user_id: str) -> tuple[list[Candidate], bool]:
    from app.domains.approvals.reel_jobs import cost_per_job
    from app.domains.capture.ads import draft_script
    from app.domains.capture.models import STATUS_SUCCEEDED, CaptureJob

    since = _utcnow() - timedelta(days=RECENT_DAYS)
    rows = session.execute(
        select(CaptureJob)
        .where(CaptureJob.user_id == user_id, CaptureJob.status == STATUS_SUCCEEDED,
               CaptureJob.created_at >= since)
        .order_by(CaptureJob.created_at.desc())
        .limit(SCAN_LIMIT + 1)
    ).scalars().all()
    complete = len(rows) <= SCAN_LIMIT
    cost = cost_per_job()
    out: list[Candidate] = []
    for row in rows[:SCAN_LIMIT]:
        meta = dict(row.meta or {})
        outputs = _capture_outputs(meta)
        if not outputs or meta.get("approval"):
            continue
        draft = draft_script(row)
        aspects = [str(o.get("aspect") or "") for o in outputs]
        credits = cost * len(outputs)
        out.append(Candidate(
            external_ref=row.id,
            title=_clip(f"Make reel ads from the capture of {draft['title']}", 300),
            summary=_clip(f"Renders {len(outputs)} captions-only reel(s) ({', '.join(aspects)}) from the "
                          f"recording, using {credits} credit(s). Script: {draft['script']}", 1000),
            risk=RISK_MEDIUM,
            payload={
                "capture_id": row.id, "source_url": row.source_url, "source_kind": row.source_kind,
                "aspects": aspects, "script": draft["script"], "credits": credits, "mode": "captions",
                "open_path": f"/capture/{row.id}", "editable_fields": ["script"],
            },
        ))
    return out, complete


def _approve_capture(user_id: str, ref: str, edits: dict) -> dict:
    _require_session()
    from app.domains.approvals.reel_jobs import queue_reel_jobs
    from app.domains.capture import ads
    from app.domains.capture.models import STATUS_SUCCEEDED, CaptureJob

    with get_session() as session:  # type: ignore[misc]
        row = session.get(CaptureJob, ref)
        if row is None or row.user_id != user_id:
            raise ApprovalExecError("the capture was deleted", status_code=404, gone=True)
        if row.status != STATUS_SUCCEEDED:
            raise ApprovalExecError("the capture is no longer finished; retry it first", status_code=409, gone=True)
        meta = dict(row.meta or {})
        previous = dict(meta.get("approval") or {})
        snapshot = SimpleNamespace(id=row.id, source_url=row.source_url, source_kind=row.source_kind, meta=meta)
    if previous.get("job_ids"):
        # Already turned into reels (e.g. a retried decision): never debit twice.
        return {"action": "reels_queued", "job_ids": list(previous["job_ids"]), "credits": 0, "replayed": True,
                "open_path": "/jobs"}
    script = str(edits.get("script") or "").strip() or ads.draft_script(snapshot)["script"]
    outputs = _capture_outputs(meta)
    if not outputs:
        raise ApprovalExecError("this capture has no finished video", status_code=409, gone=True)
    try:
        requests = [ads.build_job_request(snapshot, output, mode="captions", script=script, language="auto")
                    for output in outputs]
    except ads.AdRequestError as exc:
        raise ApprovalExecError(str(exc), status_code=422) from exc
    queued = queue_reel_jobs(user_id, requests, source_context={"kind": "capture", "id": ref})
    with get_session() as session:  # type: ignore[misc]
        row = session.get(CaptureJob, ref)
        if row is not None:
            row.meta = {**dict(row.meta or {}), "approval": {"job_ids": list(queued.job_ids),
                                                            "at": _utcnow().isoformat()}}
    return {
        "action": "reels_queued",
        "job_ids": list(queued.job_ids),
        "credits": queued.credits,
        "enqueue_failures": list(queued.enqueue_failures),
        "open_path": "/jobs",
    }


def _reject_capture(_user_id: str, ref: str) -> dict:
    return {"action": "capture_dismissed", "capture_id": ref}


# --------------------------------------------------------------------------- #
# catalog_import
# --------------------------------------------------------------------------- #
def _price(minor: int | None, currency: str) -> str:
    if minor is None:
        return ""
    return f"{minor / 100:,.2f} {currency}".strip()


def _scan_catalog(session: Any, user_id: str) -> tuple[list[Candidate], bool]:
    from app.domains.adstudio.catalog_models import STATUS_SUCCEEDED, StoreCatalogImport, StoreCatalogProduct

    since = _utcnow() - timedelta(days=RECENT_DAYS)
    rows = session.execute(
        select(StoreCatalogProduct, StoreCatalogImport)
        .join(StoreCatalogImport, StoreCatalogImport.id == StoreCatalogProduct.import_id)
        .where(StoreCatalogProduct.user_id == user_id, StoreCatalogImport.user_id == user_id,
               StoreCatalogImport.status == STATUS_SUCCEEDED, StoreCatalogImport.created_at >= since,
               StoreCatalogProduct.adstudio_project_id.is_(None))
        .order_by(StoreCatalogImport.created_at.desc(), StoreCatalogProduct.created_at.asc())
        .limit(SCAN_LIMIT + 1)
    ).all()
    complete = len(rows) <= SCAN_LIMIT
    out: list[Candidate] = []
    for product, imp in rows[:SCAN_LIMIT]:
        price = _price(product.price_minor, product.currency)
        store = imp.store_name or imp.store_url
        out.append(Candidate(
            external_ref=product.id,
            title=_clip(f"Make ads for {product.title or 'a product'} from {store}", 300),
            summary=_clip(f"Creates an Ad Studio project{' (' + price + ')' if price else ''} and renders "
                          f"{DEFAULT_ANGLES} free showcase ads (9:16). {product.description or ''}", 1000),
            risk=RISK_LOW,
            payload={
                "product_id": product.id, "import_id": imp.id, "store": store, "title": product.title,
                "price": price, "url": product.url, "image_url": (list(product.image_urls or []) or [""])[0],
                "formats": list(DEFAULT_FORMATS), "aspects": list(DEFAULT_ASPECTS), "angles": DEFAULT_ANGLES,
                "open_path": f"/ad-studio/catalog/{imp.id}",
            },
        ))
    return out, complete


def _default_variants(session: Any, user_id: str, project: Any) -> tuple[list[str], str]:
    """Queue the default showcase batch; returns (variant ids, note when skipped)."""
    from app.domains.adstudio import service as adstudio_service
    from app.domains.adstudio.repository import AdStudioRepository

    if AdStudioRepository(session).variants(project.id):
        return [], "the project already has ads"
    angle_ids = [str(a.get("id")) for a in (project.angles or []) if a.get("id")][:DEFAULT_ANGLES]
    if not angle_ids:
        return [], "the product has no ad angles yet; add one in Ad Studio"
    if not project.images:
        return [], "the product has no images; add one in Ad Studio before rendering"
    try:
        ids = adstudio_service.queue_variants(session, user_id=user_id, project=project, angle_ids=angle_ids,
                                              formats=list(DEFAULT_FORMATS), aspects=list(DEFAULT_ASPECTS),
                                              options={})
    except adstudio_service.AdStudioError as exc:
        return [], exc.message
    return ids, ""


def _approve_catalog(user_id: str, ref: str, _edits: dict) -> dict:
    _require_session()
    from app.domains.adstudio.catalog_models import StoreCatalogProduct
    from app.domains.adstudio.repository import AdStudioRepository
    from app.domains.adstudio.service import AdStudioError
    from app.domains.adstudio.store_catalog import service as catalog_service
    from app.domains.adstudio.worker import dispatch_render

    with get_session() as session:  # type: ignore[misc]
        product = session.get(StoreCatalogProduct, ref)
        if product is None or product.user_id != user_id:
            raise ApprovalExecError("the product was removed from the import", status_code=404, gone=True)
        project_id, import_id = product.adstudio_project_id, product.import_id
        if not project_id:
            try:
                provider, products = catalog_service.products_for_projects(session, user_id, import_id, [ref])
            except AdStudioError as exc:
                raise ApprovalExecError(exc.message, status_code=exc.status_code,
                                        gone=exc.status_code in (404, 409)) from exc
    if not project_id:
        # Network phase (feed images, angles) with no DB session open.
        prepared = catalog_service.prepare_projects(provider, products, language=None, use_llm=False)
        with get_session() as session:  # type: ignore[misc]
            result = catalog_service.persist_projects(session, user_id, prepared)[0]
        if not result.get("project_id"):
            raise ApprovalExecError(result.get("error") or "the product could not be turned into a project",
                                    status_code=422)
        project_id = result["project_id"]
    with get_session() as session:  # type: ignore[misc]
        project = AdStudioRepository(session).get_project(project_id)
        if project is None or str(project.user_id) != str(user_id):
            raise ApprovalExecError("the Ad Studio project was deleted", status_code=404, gone=True)
        try:
            variant_ids, note = _default_variants(session, user_id, project)
        except AdStudioError as exc:  # pragma: no cover - mapped above; defensive
            variant_ids, note = [], exc.message
    for variant_id in variant_ids:
        try:
            dispatch_render(variant_id)
        except Exception as exc:  # noqa: BLE001 - the stale sweep fails it; the project stands
            logger.warning(f"approvals: could not dispatch ad render {variant_id}: {exc}")
    out = {"action": "adstudio_project_created", "project_id": project_id, "variant_ids": variant_ids,
           "open_path": f"/ad-studio/{project_id}"}
    if note:
        out["note"] = note
    return out


def _reject_catalog(_user_id: str, ref: str) -> dict:
    return {"action": "product_skipped", "product_id": ref}


PRODUCER_ADAPTERS: dict[str, Adapter] = {
    SOURCE_DESIGN_PUBLISH: Adapter(SOURCE_DESIGN_PUBLISH, _no_scan, _approve_design, _reject_design),
    SOURCE_CAPTURE_PUBLISH: Adapter(SOURCE_CAPTURE_PUBLISH, _scan_capture, _approve_capture, _reject_capture),
    SOURCE_CATALOG_IMPORT: Adapter(SOURCE_CATALOG_IMPORT, _scan_catalog, _approve_catalog, _reject_catalog),
}

__all__ = ["DEFAULT_ANGLES", "PRODUCER_ADAPTERS", "RECENT_DAYS"]
