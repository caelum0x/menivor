"""Ad Studio HTTP adapter — product URL -> ad angles -> rendered ad variants.

* ``POST   /ad-studio/analyze``                                  preview: product + angles
* ``POST   /ad-studio/projects``                                 save a project (imports images)
* ``GET    /ad-studio/projects``                                 caller's projects
* ``GET    /ad-studio/projects/{id}``                            project + variants (state synced)
* ``PATCH  /ad-studio/projects/{id}``                            rename / edit angle copy
* ``POST   /ad-studio/projects/{id}/angles/regenerate``          rewrite angles
* ``DELETE /ad-studio/projects/{id}``                            delete project + variants
* ``POST   /ad-studio/projects/{id}/variants``                   batch: angles x formats x aspects
* ``POST   /ad-studio/projects/{id}/variants/{vid}/job``         link the reel job of a UGC ad
* ``POST   /ad-studio/projects/{id}/variants/{vid}/retry``       retry a failed ad
* ``DELETE /ad-studio/projects/{id}/variants/{vid}``             remove one ad
* ``GET    /ad-studio/projects/{id}/export``                     batch export manifest

Every route is authenticated and owner-scoped. Product pages and images are
fetched through the SSRF guard in :mod:`app.domains.adstudio.fetch`.

Every rendered ad costs one credit (MN1). A batch is all-or-nothing: a short
balance is a 402 and nothing is queued. A render that fails before producing
its video is refunded exactly once (by the worker, and again idempotently when
the project is read after a stale-render sweep or when the ad is deleted).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.adstudio import service, views
from app.domains.adstudio.repository import AdStudioRepository
from app.domains.adstudio.worker import RenderQueueUnavailable, dispatch_render, fail_and_refund
from app.domains.reels import charge
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()


class ManualProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    brand: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=2000)
    price: Optional[float] = Field(default=None, ge=0)
    original_price: Optional[float] = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=3)
    images: list[str] = Field(default_factory=list, max_length=10)
    bullets: list[str] = Field(default_factory=list, max_length=8)
    reviews: list[str] = Field(default_factory=list, max_length=6)
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    review_count: Optional[int] = Field(default=None, ge=0)
    language: str = Field(default="", max_length=5)
    # Store label of an already-analyzed product being saved without a re-fetch.
    source: str = Field(default="", max_length=20)


class AnalyzeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: Optional[str] = Field(default=None, max_length=2048)
    product: Optional[ManualProduct] = None
    language: Optional[str] = Field(default=None, max_length=5)
    angle_count: int = Field(default=5, ge=3, le=5)
    use_llm: bool = True


class AngleIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str = Field(default="", max_length=32)
    hook: str = Field(default="", max_length=400)
    pain: str = Field(default="", max_length=400)
    proof: str = Field(default="", max_length=400)
    offer: str = Field(default="", max_length=400)
    cta: str = Field(default="", max_length=400)
    source: str = Field(default="", max_length=12)


class CreateProjectBody(AnalyzeBody):
    title: str = Field(default="", max_length=200)
    angles: Optional[list[AngleIn]] = Field(default=None, max_length=5)
    image_keys: list[str] = Field(default_factory=list, max_length=8)


class UpdateProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, max_length=200)
    angles: Optional[list[AngleIn]] = Field(default=None, max_length=5)


class RegenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_llm: bool = True
    angle_count: int = Field(default=5, ge=3, le=5)


class VariantsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle_ids: list[str] = Field(..., min_length=1, max_length=5)
    formats: list[str] = Field(..., min_length=1, max_length=3)
    aspects: list[str] = Field(..., min_length=1, max_length=3)
    avatar_id: str = Field(default="", max_length=64)
    voice_id: str = Field(default="", max_length=128)
    caption_style: str = Field(default="", max_length=64)


class AttachJobBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., min_length=1, max_length=32)


def _error(request_id: str, exc: service.AdStudioError) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc.message}")


def _not_found(request_id: str, what: str = "project") -> HttpException:
    return HttpException(task_id=request_id, status_code=404, message=f"{request_id}: {what} not found")


def _authenticate(request: Request, request_id: str) -> str:
    require_database(request_id)
    with get_session() as session:
        return str(resolve_principal(request, session, request_id).id)


def _owned_project(session: Any, request: Request, request_id: str, project_id: str) -> tuple[str, Any]:
    user_id = str(resolve_principal(request, session, request_id).id)
    project = AdStudioRepository(session).get_owned_project(user_id, project_id)
    if project is None:
        raise _not_found(request_id)
    return user_id, project


def _refund_unrendered(session: Any, variants: list[Any]) -> None:
    """Return the credit of each failed or never-started ad that has no video.

    Idempotent per debit (see :func:`charge.refund_ref_once`), so reading a
    project twice never refunds twice. A UGC ad whose montage rendered keeps
    its charge even if the linked reel later fails (that reel refunds itself).
    """
    for variant in variants:
        if variant.status in ("failed", "queued") and not variant.output_key:
            charge.refund_ref_once(
                session, user_id=str(variant.user_id), kind=charge.ADSTUDIO_KIND, ref=variant.id,
            )


def _dispatch_all(request_id: str, variant_ids: list[str]) -> list[str]:
    """Queue each render; a queue outage fails and refunds that ad. Returns queued ids."""
    queued: list[str] = []
    for variant_id in variant_ids:
        try:
            dispatch_render(variant_id)
            queued.append(variant_id)
        except RenderQueueUnavailable:
            fail_and_refund(variant_id, "the render queue is unavailable; your credit was returned, retry shortly")
    if variant_ids and not queued:
        raise HttpException(
            task_id=request_id, status_code=503,
            message=f"{request_id}: the render queue is unavailable; your credits were returned",
        )
    return queued


def _manual(body: AnalyzeBody) -> dict[str, Any] | None:
    return body.product.model_dump() if body.product is not None else None


@router.post("/ad-studio/analyze", summary="Extract a product and draft ad angles")
def analyze(request: Request, body: AnalyzeBody):
    request_id = base.get_task_id(request)
    user_id = _authenticate(request, request_id)
    enforce_rate_limit(request, f"adstudio:analyze:{user_id}", limit=40, window_s=3600)
    try:
        data = service.analyze(body.url, _manual(body), body.language, body.angle_count, body.use_llm)
    except service.AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, data)


@router.post("/ad-studio/projects", summary="Save an Ad Studio project")
def create_project(request: Request, body: CreateProjectBody):
    request_id = base.get_task_id(request)
    user_id = _authenticate(request, request_id)
    enforce_rate_limit(request, f"adstudio:create:{user_id}", limit=30, window_s=3600)
    try:
        prepared = service.prepare_project(
            url=body.url, manual=_manual(body), language=body.language,
            angles=[a.model_dump() for a in body.angles] if body.angles else None,
            count=body.angle_count, use_llm=body.use_llm,
        )
        with get_session() as session:
            project = service.persist_project(
                session, user_id=user_id, prepared=prepared, title=body.title, image_keys=body.image_keys,
            )
            data = views.project_detail(project, [], {})
    except service.AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, data)


@router.get("/ad-studio/projects", summary="List the caller's Ad Studio projects")
def list_projects(request: Request, limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
        repo = AdStudioRepository(session)
        rows, total = repo.list_projects(user_id, limit=limit, offset=offset)
        counts = repo.variant_counts([p.id for p in rows])
        r2 = views._r2()
        items = [views.project_summary(p, counts.get(p.id), r2) for p in rows]
    return utils.get_response(200, {"projects": items, "total": total, "limit": limit, "offset": offset, "has_more": offset + len(items) < total})


@router.get("/ad-studio/projects/{project_id}", summary="Get a project with its ads")
def get_project(request: Request, project_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        _, project = _owned_project(session, request, request_id, project_id)
        service.sweep(session, project.id)
        repo = AdStudioRepository(session)
        variants = repo.variants(project.id)
        jobs = service.sync_jobs(session, variants)
        _refund_unrendered(session, [v for v in variants if v.status == "failed"])
        data = views.project_detail(project, variants, jobs)
    return utils.get_response(200, data)


@router.patch("/ad-studio/projects/{project_id}", summary="Rename a project or edit its angles")
def update_project(request: Request, body: UpdateProjectBody, project_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        with get_session() as session:
            _, project = _owned_project(session, request, request_id, project_id)
            if body.title is not None and body.title.strip():
                project.title = body.title.strip()[:200]
            if body.angles is not None:
                project.angles = service.sanitize_angles(
                    [a.model_dump() for a in body.angles], dict(project.product or {}), project.language,
                )
            session.flush()
            data = views.project_summary(project)
    except service.AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, data)


@router.post("/ad-studio/projects/{project_id}/angles/regenerate", summary="Rewrite the ad angles")
def regenerate_angles(request: Request, body: RegenerateBody, project_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    user_id = _authenticate(request, request_id)
    enforce_rate_limit(request, f"adstudio:angles:{user_id}", limit=40, window_s=3600)
    with get_session() as session:
        project = AdStudioRepository(session).get_owned_project(user_id, project_id)
        if project is None:
            raise _not_found(request_id)
        product, language = dict(project.product or {}), project.language
    fresh = service.make_angles(product, language, body.angle_count, body.use_llm)
    with get_session() as session:
        project = AdStudioRepository(session).get_owned_project(user_id, project_id)
        if project is None:
            raise _not_found(request_id)
        project.angles = fresh
    return utils.get_response(200, {"angles": fresh})


@router.delete("/ad-studio/projects/{project_id}", summary="Delete a project and its ads")
def delete_project(request: Request, project_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        _, project = _owned_project(session, request, request_id, project_id)
        repo = AdStudioRepository(session)
        _refund_unrendered(session, repo.variants(project.id))
        repo.delete_project(project)
    return utils.get_response(200, {"deleted": True, "id": project_id})


@router.post("/ad-studio/projects/{project_id}/variants", summary="Render a batch of ad variants")
def create_variants(request: Request, body: VariantsBody, project_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        with get_session() as session:
            user_id, project = _owned_project(session, request, request_id, project_id)
            enforce_rate_limit(request, f"adstudio:variants:{user_id}", limit=30, window_s=3600)
            ids = service.queue_variants(
                session, user_id=user_id, project=project, angle_ids=body.angle_ids,
                formats=body.formats, aspects=body.aspects,
                options={"avatar_id": body.avatar_id, "voice_id": body.voice_id, "caption_style": body.caption_style},
            )
            # One credit per ad, all or nothing: a 402 rolls the rows back.
            charge.debit_refs_or_402(
                session, user_id=user_id, kind=charge.ADSTUDIO_KIND, refs=ids,
                request_id=request_id, what="ad batch",
            )
    except service.AdStudioError as exc:
        raise _error(request_id, exc) from exc
    queued = _dispatch_all(request_id, ids)
    return utils.get_response(200, {"variant_ids": ids, "queued": len(queued)})


def _owned_variant(session: Any, request: Request, request_id: str, project_id: str, variant_id: str) -> tuple[str, Any]:
    user_id = str(resolve_principal(request, session, request_id).id)
    variant = AdStudioRepository(session).get_owned_variant(user_id, project_id, variant_id)
    if variant is None:
        raise _not_found(request_id, "ad")
    return user_id, variant


@router.post("/ad-studio/projects/{project_id}/variants/{variant_id}/job", summary="Link a UGC ad's reel job")
def attach_job(
    request: Request, body: AttachJobBody,
    project_id: str = Path(..., max_length=32), variant_id: str = Path(..., max_length=32),
):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        with get_session() as session:
            user_id, variant = _owned_variant(session, request, request_id, project_id, variant_id)
            service.attach_job(session, user_id=user_id, variant=variant, job_id=body.job_id)
            data = {"id": variant.id, "status": variant.status, "job_id": variant.job_id}
    except service.AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, data)


@router.post("/ad-studio/projects/{project_id}/variants/{variant_id}/retry", summary="Retry a failed ad")
def retry_variant(
    request: Request, project_id: str = Path(..., max_length=32), variant_id: str = Path(..., max_length=32),
):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        with get_session() as session:
            user_id, variant = _owned_variant(session, request, request_id, project_id, variant_id)
            # Settle the failed attempt first so the retry is charged once, net.
            _refund_unrendered(session, [variant])
            needs_render = service.retry_variant(variant)
            if needs_render:
                charge.debit_ref_or_402(
                    session, user_id=user_id, kind=charge.ADSTUDIO_KIND, ref=variant.id,
                    request_id=request_id, what="ad",
                )
            data = {"id": variant.id, "status": variant.status}
    except service.AdStudioError as exc:
        raise _error(request_id, exc) from exc
    if needs_render:
        _dispatch_all(request_id, [variant_id])
    return utils.get_response(200, data)


@router.delete("/ad-studio/projects/{project_id}/variants/{variant_id}", summary="Remove one ad")
def delete_variant(
    request: Request, project_id: str = Path(..., max_length=32), variant_id: str = Path(..., max_length=32),
):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        _, variant = _owned_variant(session, request, request_id, project_id, variant_id)
        if variant.status == "rendering":
            raise HttpException(task_id=request_id, status_code=409, message=f"{request_id}: this ad is still rendering")
        _refund_unrendered(session, [variant])
        session.delete(variant)
    return utils.get_response(200, {"deleted": True, "id": variant_id})


@router.get("/ad-studio/projects/{project_id}/export", summary="Batch export manifest of finished ads")
def export_project(request: Request, project_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        _, project = _owned_project(session, request, request_id, project_id)
        variants = AdStudioRepository(session).variants(project.id)
        jobs = service.sync_jobs(session, variants)
        data = views.export_manifest(project, variants, jobs)
    return utils.get_response(200, data)
