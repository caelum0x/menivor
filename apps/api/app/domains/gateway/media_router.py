"""Unified media gateway HTTP surface — OpenRouter-style, namespaced under /media.

    GET  /media/models              list image + video + audio models (one catalog)
    POST /media/images              generate an image synchronously → {url}
    POST /media/videos              submit a video job → {id, status} (poll it)
    GET  /media/videos/{id}         poll a video job → {status, url}
    POST /media/audio               submit a music job → {id, status} (poll it)
    GET  /media/audio/{id}          poll an audio job → {status, url}
    GET  /media/credits             spendable credits + lifetime gateway spend
    GET  /media/usage               spend + counts by model
    GET  /media/generations         durable owner-scoped generation timeline
    GET  /media/generation/{id}     per-generation cost/status detail
    GET  /media/identities          locked passports owned by the payer
    GET  /media/generation/{id}/provenance owner-scoped proof export
    GET  /media/generation/{id}/evidence owner-scoped settlement evidence

One key + one wallet balance for every model, like OpenRouter — namespaced under
``/media`` so it never collides with MPT's legacy ``/videos``/``/audio``. Auth +
owner-scoping + DB reuse the shared jobs-controller helpers. Import-safe.
"""

from __future__ import annotations

from fastapi import Path, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.db.media_jobs import MediaJob
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.api_dependencies import (
        get_session,
        require_database as _require_db,
        resolve_principal as _resolve_user,
    )
    from app.domains.gateway import media_gateway as gw
    from app.domains.gateway import media_usage
    from app.domains.gateway.media_catalog import audio_models, image_models, video_models

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = exc

router = new_router()


class ImageBody(BaseModel):
    model: str = Field(..., max_length=120)
    prompt: str = Field(..., max_length=4000)


class VideoReference(BaseModel):
    """One role-tagged reference image: a public https URL or your own uploaded file key."""

    url: str = Field(..., max_length=1000)
    role: str = Field(..., max_length=20, description="first_frame | identity | style")


class VideoBrief(BaseModel):
    """Structured shot brief; when sent, it replaces the free-text prompt."""

    format: str = Field(..., max_length=600, description="for example: 9:16, 5 s, 720p")
    action: str = Field(..., max_length=600)
    camera: str = Field(default="", max_length=600)
    continuity: str = Field(default="", max_length=600)
    audio: str = Field(default="", max_length=600)
    constraints: str = Field(default="", max_length=600)


class VideoBody(BaseModel):
    model: str = Field(..., max_length=120)
    prompt: str = Field(default="", max_length=4000)
    duration: int = Field(default=5, ge=1, le=60)
    aspect_ratio: str = Field(default="9:16", max_length=10)
    image_url: str = Field(default="", max_length=1000)
    identity_passport_id: str = Field(default="", max_length=160)
    identity_version: int | None = Field(default=None, ge=1)
    references: list[VideoReference] | None = Field(default=None, max_length=4)
    brief: VideoBrief | None = None


class AudioBody(BaseModel):
    model: str = Field(..., max_length=120)
    prompt: str = Field(..., max_length=4000)
    instrumental: bool = Field(default=False)


def _guard(request_id: str) -> None:
    if _IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: media gateway unavailable: {_IMPORT_ERROR}")


def _model_view(m) -> dict:
    # MO1: every row stays listed; ``sellable`` is False for non-commercial,
    # research-only or unrecorded weights, and a create call on it answers 403.
    from app.domains.routing.license_class import is_model_sellable, model_license

    lic = model_license(m.id)
    return {
        "id": m.id, "modality": m.modality, "provider": m.provider,
        "price_micros": m.price_micros, "unit": m.unit, "max_seconds": m.max_seconds,
        "description": m.description,
        "license_class": lic.license_class if lic else "unreviewed",
        "sellable": is_model_sellable(m.id),
    }


def _video_view(row) -> dict:
    return media_usage.generation_view(row)


@router.get("/media/models", summary="List image + video + audio models (unified catalog)")
def list_media_models(request: Request, modality: str = ""):
    request_id = base.get_task_id(request)
    _guard(request_id)
    models = (video_models() if modality == "video"
              else image_models() if modality == "image"
              else audio_models() if modality == "audio"
              else [*image_models(), *video_models(), *audio_models()])
    return utils.get_response(200, {"models": [_model_view(m) for m in models]})


@router.post("/media/images", summary="Generate an image (synchronous)")
def create_image(request: Request, body: ImageBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            result = gw.create_image(session, user_id=user.id, model=body.model, prompt=body.prompt)
        except gw.GatewayError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, result)


_REFERENCE_PRESIGN_TTL_S = 3600


def _resolve_references(session, user_id: str, body: VideoBody, request_id: str):
    """Validate references, presign owned storage keys, and build the brief prompt.

    Returns ``(prompt, references)``. Storage keys must belong to the caller
    (403 otherwise) and are swapped for short-lived signed GETs on our own bucket.
    """
    from app.domains.gateway import video_brief as vb

    try:
        refs = vb.parse_references([r.model_dump() for r in body.references or []])
        prompt = body.prompt
        if body.brief is not None:
            prompt = vb.brief_from_mapping(body.brief.model_dump(), refs)
    except vb.BriefError as exc:
        raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: {exc}") from exc
    resolved = []
    for ref in refs:
        if not ref.is_key:
            resolved.append(ref)
            continue
        from app.domains.media.service import MediaDomainError, require_owned_asset

        try:
            require_owned_asset(session, user_id=user_id, key=ref.url)
        except MediaDomainError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc.message}") from exc
        from app.platform.storage.r2 import get_r2_client

        url = get_r2_client().presign_get(ref.url, expires=_REFERENCE_PRESIGN_TTL_S)
        resolved.append(vb.Reference(url=url, role=ref.role))
    return prompt, tuple(resolved)


@router.post("/media/videos", summary="Submit a video generation (poll for the result)")
def create_video(request: Request, body: VideoBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        prompt, references = _resolve_references(session, user.id, body, request_id)
        try:
            row = gw.create_video(
                session, user_id=user.id, model=body.model, prompt=prompt,
                duration=body.duration, aspect_ratio=body.aspect_ratio, image_url=body.image_url,
                identity_passport_id=body.identity_passport_id,
                identity_version=body.identity_version,
                references=references,
            )
        except gw.GatewayError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, _video_view(row))


@router.get("/media/videos/{job_id}", summary="Poll a video generation job")
def get_video(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = gw.poll_video(session, user_id=user.id, job_id=job_id)
        except gw.GatewayError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, _video_view(row))


@router.post("/media/videos/{job_id}/cancel", summary="Cancel a running video job (best-effort provider cancel + release hold)")
def cancel_video(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = gw.cancel_video(session, user_id=user.id, job_id=job_id)
        except gw.GatewayError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, _video_view(row))


@router.post("/media/audio/{job_id}/cancel", summary="Cancel a running audio job (best-effort provider cancel + release hold)")
def cancel_audio(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = gw.cancel_video(session, user_id=user.id, job_id=job_id)  # provider-generic cancel
        except gw.GatewayError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, _video_view(row))


@router.post("/media/audio", summary="Submit a music/audio generation (poll for the result)")
def create_audio(request: Request, body: AudioBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = gw.create_audio(session, user_id=user.id, model=body.model, prompt=body.prompt,
                                  instrumental=body.instrumental)
        except gw.GatewayError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, _video_view(row))


@router.get("/media/audio/{job_id}", summary="Poll a music/audio generation job")
def get_audio(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = gw.poll_video(session, user_id=user.id, job_id=job_id)  # provider-generic poll
        except gw.GatewayError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, _video_view(row))


@router.get("/media/credits", summary="Spendable credits + lifetime gateway spend")
def get_credits(request: Request):
    """OpenRouter-style credits: wallet balance + total gateway spend."""
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        return utils.get_response(200, media_usage.credits(session, user.id))


@router.get("/media/usage", summary="Gateway spend + job counts by model")
def get_usage(request: Request, limit: int = 50):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        return utils.get_response(200, {"usage": media_usage.usage_by_model(session, user.id, limit=max(1, min(200, limit)))})


@router.get("/media/generations", summary="Durable generation timeline")
def list_generations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status: str = "",
    modality: str = "",
    refresh_pending: bool = True,
):
    """List owned jobs and opportunistically reconcile a bounded pending set."""
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    normalized_status = status.strip().lower()
    normalized_modality = modality.strip().lower()
    if normalized_status and normalized_status not in {
        "queued", "in_progress", "completed", "failed", "cancelled"
    }:
        raise HttpException(
            task_id=request_id, status_code=422,
            message=f"{request_id}: invalid generation status",
        )
    if normalized_modality and normalized_modality not in {"image", "video", "audio"}:
        raise HttpException(
            task_id=request_id, status_code=422,
            message=f"{request_id}: invalid generation modality",
        )
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if refresh_pending:
            for job_id in media_usage.pending_generation_ids(
                session, user.id, limit=min(max(1, limit), 10)
            ):
                try:
                    gw.poll_video(session, user_id=user.id, job_id=job_id)
                except gw.GatewayError:
                    # A transient provider/configuration failure must not hide
                    # durable history. The hold and non-terminal state remain
                    # available for the next recovery pass.
                    continue
        page = media_usage.generations(
            session, user.id, limit=limit, offset=offset,
            status=normalized_status, modality=normalized_modality,
        )
        return utils.get_response(200, page)


@router.get("/media/generation/{job_id}", summary="Per-generation cost/status detail")
def get_generation(request: Request, job_id: str = Path(...)):
    """OpenRouter-style ``/generation?id=`` — one job's cost + status."""
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row = session.get(MediaJob, job_id)
        if row is None or str(row.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: generation not found")
        if str(row.status) not in media_usage.TERMINAL_STATUSES:
            try:
                row = gw.poll_video(session, user_id=user.id, job_id=job_id)
            except gw.GatewayError:
                # The durable non-terminal record remains inspectable; a
                # transient provider/replica failure must not erase resume state.
                pass
        return utils.get_response(200, media_usage.generation_view(row))


@router.get("/media/identities", summary="Locked Identity Lock passports owned by this payer")
def list_identities(request: Request):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            identities = gw.list_identity_options(session, user_id=user.id)
        except gw.GatewayError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=exc.status_code,
                message=f"{request_id}: {exc}",
            ) from exc
        return utils.get_response(200, {"identities": identities})


@router.get(
    "/media/generation/{job_id}/provenance",
    summary="Export immutable identity and signed settlement provenance",
)
def get_generation_provenance(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        proof = media_usage.provenance_export(session, user.id, job_id)
        if proof is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: provenance not found",
            )
        return utils.get_response(200, proof)


@router.get(
    "/media/generation/{job_id}/evidence",
    summary="Read signed settlement evidence for downstream enforcement and margin projection",
)
def get_generation_evidence(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        evidence = media_usage.settlement_evidence(session, user.id, job_id)
        if evidence is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: signed settlement evidence not found",
            )
        return utils.get_response(200, evidence)
