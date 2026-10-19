"""Content Month service: website -> ~30 post ideas -> swipe -> rendered carousels and reels.

Flow:

1. ``create_plan``: read the website (SSRF-guarded), build a :class:`SiteBrief`,
   generate a month of ideas mapped to viral formats (LLM + rules floor), import
   the brand logo once, store the plan and its ideas.
2. ``decide``: the swipe (``kept`` / ``skipped`` / back to ``pending``).
3. ``render_carousel``: a kept carousel becomes a Design Studio document (so it
   can be edited and scheduled there), rendered on the server to PNG pages
   (stored through the Design Studio export), a PDF and a slideshow MP4.
4. Kept reels carry ``reel_job``: the exact ``POST /jobs`` body for Menivor's
   reel pipeline. The client creates the job (normal credits and checks apply)
   and links it back with ``attach_job``.

Every read and write is scoped to the owning user.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger
from sqlalchemy import func, select

from app.domains.content_month import formats as fm
from app.domains.content_month import ideas as ideas_mod
from app.domains.content_month import raster, slides, video
from app.domains.content_month.brief import SiteBrief, clean, from_analysis
from app.domains.content_month.models import (
    DECISION_KEPT,
    DECISION_PENDING,
    DECISIONS,
    RENDER_DONE,
    RENDER_QUEUED,
    ContentIdea,
    ContentPlan,
)
from app.domains.content_month.reel import reel_job
from app.domains.design import service as design_service
from app.domains.design.layouts import BrandStyle

try:
    from app.models.db.base import get_session

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - reported as a 503
    get_session = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

MAX_PLANS_LISTED = 50
MAX_URL = 2000
HOOK_MAX = 90
SLIDE_MAX = 150
CAPTION_MAX = 300

Analyze = Callable[[str], dict]


class MonthError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(message)


def _require_ready() -> None:
    if get_session is None:
        raise MonthError(f"content plans are unavailable: {_IMPORT_ERROR}", status_code=503)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def normalize_url(raw: str) -> str:
    url = " ".join(str(raw or "").split())
    if not url or len(url) > MAX_URL or " " in url:
        raise MonthError("enter your website address, like yourbrand.com")
    if not url.lower().startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _default_analyze(url: str) -> dict:
    from app.domains.brand_agent.site_analysis import SiteAnalysisError, analyze_site

    try:
        return analyze_site(url)
    except SiteAnalysisError as exc:
        status = int(getattr(exc, "status_code", 422) or 422)
        raise MonthError(getattr(exc, "message", str(exc)), status_code=422 if status >= 500 else status) from exc


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
def _style(plan: ContentPlan) -> BrandStyle:
    data = plan.style_json or {}
    fields = {k: v for k, v in data.items() if k in BrandStyle.__dataclass_fields__ and isinstance(v, str)}
    return BrandStyle(**fields)


def _preview(idea: ContentIdea, style: BrandStyle) -> dict:
    """The cover slide (carousel) or hook card (reel) for the swipe card."""
    canvas = slides.deck([idea.hook, *(idea.slides or [])[1:2]], style, slides.DEFAULT_SIZE)
    _, w, h = slides.SIZES[slides.DEFAULT_SIZE]
    return {"width": w, "height": h, "page": canvas["pages"][0]}


def _outputs(outputs: dict) -> dict:
    out = dict(outputs or {})
    out["png_urls"] = [design_service._presign(k) for k in out.get("png_keys") or []]
    out["pdf_url"] = design_service._presign(out.get("pdf_key") or "", "carousel.pdf")
    out["mp4_url"] = design_service._presign(out.get("mp4_key") or "", "carousel.mp4")
    out["video_status"] = video.effective_status(out)
    out.pop("stem", None)
    return out


def idea_view(idea: ContentIdea, style: BrandStyle, brief: dict | None = None) -> dict:
    fmt = fm.get(idea.format)
    view = {
        "id": idea.id, "plan_id": idea.plan_id, "position": idea.position, "format": idea.format,
        "format_name": fmt.name if fmt else idea.format, "why": fmt.why if fmt else "", "kind": idea.kind,
        "hook": idea.hook, "slides": list(idea.slides or []), "script": idea.script, "caption": idea.caption,
        "source": idea.source, "decision": idea.decision, "decided_at": _iso(idea.decided_at),
        "render_status": idea.render_status, "outputs": _outputs(idea.outputs or {}),
        "preview": _preview(idea, style),
    }
    if idea.kind == fm.KIND_REEL:
        view["reel_job"] = reel_job(idea.id, idea.hook, idea.script, (brief or {}).get("language") or "en",
                                    idea.position)
    return view


def _counts(session: Any, plan_id: str) -> dict:
    rows = session.execute(
        select(ContentIdea.decision, func.count()).where(ContentIdea.plan_id == plan_id)
        .group_by(ContentIdea.decision)).all()
    counts = {"pending": 0, "kept": 0, "skipped": 0}
    for decision, number in rows:
        counts[decision] = int(number)
    counts["total"] = sum(counts.values())
    return counts


def plan_view(session: Any, plan: ContentPlan, *, with_ideas: bool = True) -> dict:
    view = {
        "id": plan.id, "url": plan.url, "name": plan.name, "brief": plan.brief_json or {},
        "style": plan.style_json or {}, "created_at": _iso(plan.created_at), "counts": _counts(session, plan.id),
    }
    if with_ideas:
        style = _style(plan)
        rows = session.execute(select(ContentIdea).where(ContentIdea.plan_id == plan.id)
                               .order_by(ContentIdea.position)).scalars().all()
        view["ideas"] = [idea_view(r, style, plan.brief_json) for r in rows]
    return view


def _plan(session: Any, user_id: str, plan_id: str) -> ContentPlan:
    row = session.get(ContentPlan, plan_id)
    if row is None or row.user_id != user_id:
        raise MonthError("plan not found", status_code=404)
    return row


def _idea(session: Any, user_id: str, idea_id: str) -> ContentIdea:
    row = session.get(ContentIdea, idea_id)
    if row is None or row.user_id != user_id:
        raise MonthError("post not found", status_code=404)
    return row


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #
def style_for(session: Any, user_id: str, brief: SiteBrief) -> BrandStyle:
    logo_key = design_service._logo_key(session, user_id, brief.logo_url, design_service._fetch_remote)
    return design_service.style_from_brand(brief.brand(), logo_key)


def create_plan(user_id: str, url: str, *, count: int = ideas_mod.DEFAULT_COUNT, use_llm: bool = True,
                analyze: Analyze | None = None, generate: ideas_mod.Generate | None = None) -> dict:
    _require_ready()
    target = normalize_url(url)
    brief = from_analysis((analyze or _default_analyze)(target))
    if not brief.name:
        raise MonthError("could not find a brand name on that page; try your homepage", status_code=422)
    items = ideas_mod.month_ideas(brief, count=count, use_llm=use_llm, generate=generate)
    with get_session() as session:  # type: ignore[misc]
        style = style_for(session, user_id, brief)
        plan = ContentPlan(user_id=user_id, url=brief.url or target, name=brief.name[:120],
                           brief_json=brief.to_dict(), style_json=dict(style.__dict__))
        session.add(plan)
        session.flush()
        for position, item in enumerate(items):
            session.add(ContentIdea(
                plan_id=plan.id, user_id=user_id, position=position, format=item["format"], kind=item["kind"],
                hook=item["hook"], slides=item["slides"], script=item["script"], caption=item["caption"],
                source=item["source"], outputs={},
            ))
        session.flush()
        logger.info(f"content month: plan {plan.id} for {brief.domain}: {len(items)} ideas, "
                    f"{sum(1 for i in items if i['source'] == 'llm')} from the LLM")
        return plan_view(session, plan)


def list_plans(user_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        rows = session.execute(select(ContentPlan).where(ContentPlan.user_id == user_id)
                               .order_by(ContentPlan.created_at.desc()).limit(MAX_PLANS_LISTED)).scalars().all()
        return {"plans": [plan_view(session, r, with_ideas=False) for r in rows]}


def get_plan(user_id: str, plan_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        return plan_view(session, _plan(session, user_id, plan_id))


def delete_plan(user_id: str, plan_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        plan = _plan(session, user_id, plan_id)
        for row in session.execute(select(ContentIdea).where(ContentIdea.plan_id == plan.id)).scalars():
            session.delete(row)
        session.delete(plan)
        return {"deleted": True}


# --------------------------------------------------------------------------- #
# Ideas
# --------------------------------------------------------------------------- #
def _with_plan(session: Any, idea: ContentIdea) -> dict:
    plan = session.get(ContentPlan, idea.plan_id)
    return {"idea": idea_view(idea, _style(plan), plan.brief_json), "counts": _counts(session, plan.id)}


def decide(user_id: str, idea_id: str, decision: str) -> dict:
    _require_ready()
    if decision not in DECISIONS:
        raise MonthError("decision must be kept, skipped or pending")
    with get_session() as session:  # type: ignore[misc]
        idea = _idea(session, user_id, idea_id)
        idea.decision = decision
        idea.decided_at = None if decision == DECISION_PENDING else datetime.now(timezone.utc)
        session.flush()
        return _with_plan(session, idea)


def _clean_lines(values: list[Any]) -> list[str]:
    lines = [clean(v, SLIDE_MAX) for v in values if isinstance(v, str)]
    return [x for x in lines if x][:8]


def edit_idea(user_id: str, idea_id: str, *, hook: str | None = None, slides_in: list[Any] | None = None,
              caption: str | None = None) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        idea = _idea(session, user_id, idea_id)
        current = list(idea.slides or [])
        if slides_in is not None:
            new = _clean_lines(slides_in)
            if len(new) < 2:
                raise MonthError("a post needs at least two slides")
            current = new
        if hook is not None:
            text = clean(hook, HOOK_MAX)
            if not text:
                raise MonthError("the hook cannot be empty")
            idea.hook = text
            current = [text, *current[1:]] if current else [text]
        elif slides_in is not None:
            idea.hook = current[0][:HOOK_MAX]
        idea.slides = current
        if idea.kind == fm.KIND_REEL:
            from app.domains.content_month.rules import script_from

            idea.script = clean(script_from(current), ideas_mod.SCRIPT_MAX)
        if caption is not None:
            idea.caption = clean(caption, CAPTION_MAX)
        if idea.render_status == RENDER_DONE:
            idea.render_status = "none"  # the old render no longer matches the text
        session.flush()
        return _with_plan(session, idea)


def _store(session: Any, user_id: str, key: str, data: bytes, content_type: str, meta: dict) -> None:
    from app.models.db.repositories import AssetRepository

    design_service._upload(key, data, content_type)
    kind = "video" if content_type.startswith("video/") else "document"
    AssetRepository(session).create(user_id=user_id, kind=kind, r2_key=key, content_type=content_type,
                                    size_bytes=len(data), meta={**meta, "upload_state": "registered"})


def render_carousel(user_id: str, idea_id: str, *, size: str = slides.DEFAULT_SIZE, with_video: bool = True,
                    enqueue: Callable[[str, str], None] | None = None) -> dict:
    """Kept carousel -> Design Studio doc + PNG pages + PDF now; the slideshow MP4 is queued for the worker."""
    _require_ready()
    if size not in slides.SIZES:
        raise MonthError("size must be tiktok or instagram")
    preset, width, height = slides.SIZES[size]
    with get_session() as session:  # type: ignore[misc]
        idea = _idea(session, user_id, idea_id)
        if idea.kind != fm.KIND_CAROUSEL:
            raise MonthError("this post is a reel; make it with the reel button")
        if idea.decision != DECISION_KEPT:
            raise MonthError("swipe right on this post before making it")
        plan = session.get(ContentPlan, idea.plan_id)
        style, texts, title = _style(plan), list(idea.slides or [idea.hook]), idea.hook
    canvas = slides.deck(texts, style, size)
    doc = design_service.create_doc(user_id, title=title[:200], size_preset=preset, canvas=canvas,
                                    prompt=f"Content Month: {plan.name}")
    pngs = raster.render_pages(doc["canvas"], width, height, load_image=design_service._download)
    doc = design_service.export(user_id, doc["id"], [base64.b64encode(p).decode("ascii") for p in pngs])
    png_keys = list(doc.get("exported_keys") or [e["key"] for e in doc.get("exports") or []])
    outputs: dict[str, Any] = {"size": size, "design_id": doc["id"], "png_keys": png_keys,
                               "stem": f"uploads/month-{idea_id}-{uuid.uuid4().hex[:8]}"}
    meta = {"source": "content_month", "idea_id": idea_id, "design_id": doc["id"]}
    with get_session() as session:  # type: ignore[misc]
        try:
            _store(session, user_id, f"{outputs['stem']}.pdf", raster.to_pdf(pngs), "application/pdf",
                   {**meta, "filename": "carousel.pdf"})
            outputs["pdf_key"] = f"{outputs['stem']}.pdf"
        except Exception as exc:  # noqa: BLE001 - PNGs are saved; report the PDF that failed
            logger.error(f"content month: PDF failed for {idea_id}: {exc}")
            outputs["error"] = "the slides are ready, but the PDF could not be made"
        if with_video:
            outputs["video_status"] = video.QUEUED
        idea = _idea(session, user_id, idea_id)
        idea.outputs = outputs
        idea.render_status = RENDER_DONE
        session.flush()
    if with_video:
        video.enqueue(user_id, idea_id, run=enqueue)
    return get_idea(user_id, idea_id)


def retry_video(user_id: str, idea_id: str, *, enqueue: Callable[[str, str], None] | None = None) -> dict:
    """Queue the slideshow video again for a made carousel."""
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        idea = _idea(session, user_id, idea_id)
        if idea.kind != fm.KIND_CAROUSEL or not (idea.outputs or {}).get("png_keys"):
            raise MonthError("make the slides first")
        if (idea.outputs or {}).get("video_status") in (video.QUEUED, video.RENDERING):
            return _with_plan(session, idea)
        idea.outputs = {**(idea.outputs or {}), "video_status": video.QUEUED, "video_error": ""}
        session.flush()
    video.enqueue(user_id, idea_id, run=enqueue)
    return get_idea(user_id, idea_id)


def get_idea(user_id: str, idea_id: str) -> dict:
    _require_ready()
    with get_session() as session:  # type: ignore[misc]
        return _with_plan(session, _idea(session, user_id, idea_id))


def attach_job(user_id: str, idea_id: str, job_id: str) -> dict:
    """Link the reel job the client created from ``reel_job`` to this idea."""
    _require_ready()
    from app.models.db.models import Job

    with get_session() as session:  # type: ignore[misc]
        idea = _idea(session, user_id, idea_id)
        if idea.kind != fm.KIND_REEL:
            raise MonthError("only reels have a reel job")
        job = session.get(Job, job_id)
        if job is None or job.user_id != user_id:
            raise MonthError("reel job not found", status_code=404)
        idea.outputs = {**(idea.outputs or {}), "job_id": job_id}
        idea.render_status = RENDER_QUEUED
        if idea.decision != DECISION_KEPT:
            idea.decision = DECISION_KEPT
            idea.decided_at = datetime.now(timezone.utc)
        session.flush()
        return _with_plan(session, idea)


__all__ = ["MonthError", "attach_job", "create_plan", "decide", "delete_plan", "edit_idea", "get_idea", "get_plan",
           "list_plans", "normalize_url", "render_carousel", "retry_video"]
