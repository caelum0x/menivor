"""HTTP routes for Ad Clone (three steps: winning ad -> your product -> clone).

Signed in and behind ``ADCLONE_ENABLED`` (default off). Nothing here spends: the brief is local
analysis, plans are priced per engine, and render is a dry run unless the owner switches paid
rendering on for a worker.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.utils import utils

from . import elevenlabs, midjourney, presets, service
from .ipguard import IPGuardError
from .linkresolve import LinkError
from .rewrite import CloneOptions
from .schemas import CloneBrief

router = new_router()


class BriefRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=500)
    # The ad's spoken language when known; "original" lets Whisper detect it.
    language: str = Field("original", max_length=12, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$|^original$")


class PlanRequest(BaseModel):
    brief: CloneBrief
    product: str = Field("oxhan", max_length=24)
    aspect: Literal["9:16", "16:9"] = "9:16"
    variations: int = Field(1, ge=1, le=3)
    language: str = Field("original", max_length=12, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$|^original$")
    engine: str | None = Field(default=None, max_length=24)
    set_key: str = Field("", max_length=24)


class RenderRequest(BaseModel):
    plan: dict[str, Any]
    engine: str | None = Field(default=None, max_length=24)
    dry_run: bool = True


class VoiceDesignRequest(BaseModel):
    product: str = Field("oxhan", max_length=24)
    character: str = Field(..., max_length=4)
    description: str = Field("", max_length=1000)


class VoiceLockRequest(BaseModel):
    product: str = Field("oxhan", max_length=24)
    character: str = Field(..., max_length=4)
    generated_voice_id: str = Field(..., min_length=4, max_length=80)


class MjTagRequest(BaseModel):
    product: str = Field("oxhan", max_length=24)
    key: str = Field(..., max_length=300)
    tag: str = Field(..., max_length=8)


def _fail(request_id: str, status: int, message: str, data: dict | None = None) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}", data=data or {})


def _guard(request: Request) -> str:
    request_id = base.get_task_id(request)
    if not service.enabled():
        raise _fail(request_id, 403, "Ad Clone is not switched on")
    _require_db(request_id)
    with get_session() as session:
        _resolve_user(request, session, request_id)
    return request_id


def _typed(request_id: str, exc: Exception) -> HttpException:
    if isinstance(exc, IPGuardError):
        return _fail(request_id, 422, str(exc), {"code": "ip_guard", "problems": exc.problems})
    status = int(getattr(exc, "status_code", 400) or 400)
    return _fail(request_id, status, getattr(exc, "message", None) or str(exc))


_KNOWN = (LinkError, service.AdCloneError, presets.PresetError, IPGuardError, elevenlabs.ElevenLabsError,
          midjourney.ImportError_, ValueError)


@router.get("/ad-clone/products", summary="Products (brand presets) you can clone an ad for")
def list_products(request: Request):
    _guard(request)
    return utils.get_response(200, {"products": [presets.public_view(presets.load(n)) for n in presets.PRESETS]})


@router.post("/ad-clone/brief", summary="Step 1: analyse a winning ad link into a clone brief ($0, local)")
def make_brief(request: Request, body: BriefRequest):
    request_id = _guard(request)
    try:
        brief = service.analyze_link(body.url, llm=service.default_llm(), language=body.language)
    except _KNOWN as exc:
        raise _typed(request_id, exc) from exc
    return utils.get_response(200, {"brief": brief.model_dump()})


@router.post("/ad-clone/plan", summary="Step 3: clone plans for your product, priced per engine")
def make_plan(request: Request, body: PlanRequest):
    request_id = _guard(request)
    try:
        options = CloneOptions(variations=body.variations, aspect=body.aspect, language=body.language,
                               set_key=body.set_key)
        result = service.clone(body.brief, preset_name=body.product, options=options, engine=body.engine,
                               llm=service.default_llm())
    except _KNOWN as exc:
        raise _typed(request_id, exc) from exc
    return utils.get_response(200, result)


@router.post("/ad-clone/render", summary="Dry run a clone plan on the chosen engine (paid runs are owner-gated)")
def render_plan(request: Request, body: RenderRequest):
    request_id = _guard(request)
    try:
        result = service.render(body.plan, engine=body.engine, dry_run=body.dry_run)
    except _KNOWN as exc:
        raise _typed(request_id, exc) from exc
    return utils.get_response(200, result)


class ApproveRequest(BaseModel):
    plan: dict[str, Any]
    engine: str | None = Field(default=None, max_length=24)
    quoted_credits: int = Field(..., ge=0, le=1_000_000)


@router.post("/ad-clone/render/approve", summary="Approve a paid render: credits held, job queued (Idempotency-Key)")
def approve_render(request: Request, body: ApproveRequest):
    from app.core.idempotency import hash_request_payload, read_idempotency_key, reserve_idempotency_key

    from . import render_job

    request_id = _guard(request)
    key = read_idempotency_key(request, request_id)
    if not key:
        raise _fail(request_id, 400, "send an Idempotency-Key header so a retried approval never pays twice")
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row, replay = reserve_idempotency_key(session, str(user.id), key, hash_request_payload(body), request_id)
        if replay:
            return utils.get_response(200, {**replay, "replayed": True})
        try:
            job = render_job.approve(session, str(user.id), plan=body.plan, engine=body.engine,
                                     quoted_credits=body.quoted_credits, request_id=request_id)
        except (*_KNOWN, render_job.EngineNotReady) as exc:
            session.rollback()
            raise _typed(request_id, exc) from exc
        response = {"job_id": job.id, "state": job.state, "project_id": job.params.get("project_id"),
                    "ai_video_credits": job.params.get("ai_video_credits")}
        row.response_data = response
        job_id = job.id
    try:
        render_job.enqueue(job_id)
    except Exception as exc:  # noqa: BLE001 - the queue is down: give everything back
        from .render_tasks import _fail as fail_job

        fail_job(job_id, "could not start; nothing was charged")
        raise _fail(request_id, 502, "could not start the render; your credits are back", {"code": "enqueue_failed"}) from exc
    return utils.get_response(200, response)


@router.get("/ad-clone/render/{job_id}", summary="Paid render progress, spend and the finished video")
def render_status(request: Request, job_id: str):
    from app.models.db.models import Job

    from . import render_job

    request_id = _guard(request)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = session.get(Job, job_id[:32])
        if job is None or job.kind != render_job.JOB_KIND or str(job.user_id) != str(user.id):
            raise _fail(request_id, 404, "render not found")
        view = render_job.view(job)
    return utils.get_response(200, view)


@router.post("/ad-clone/voices/design", summary="Design voice previews for a character (ElevenLabs, original voices)")
def design_voice(request: Request, body: VoiceDesignRequest):
    request_id = _guard(request)
    try:
        preset = presets.load(body.product)
        char = preset["characters"].get(body.character)
        if char is None:
            raise presets.PresetError("unknown character")
        previews = elevenlabs.ElevenLabs.from_env().design(body.description or char["voice"]["voice_design"])
    except _KNOWN as exc:
        raise _typed(request_id, exc) from exc
    return utils.get_response(200, {"character": body.character, "previews": previews})


@router.post("/ad-clone/voices/lock", summary="Save a designed preview as the character's locked voice id")
def lock_voice(request: Request, body: VoiceLockRequest):
    request_id = _guard(request)
    try:
        preset = presets.load(body.product)
        updated = elevenlabs.lock_character_voice(elevenlabs.ElevenLabs.from_env(), preset, body.character,
                                                  body.generated_voice_id)
        presets.save(updated)
    except _KNOWN as exc:
        raise _typed(request_id, exc) from exc
    return utils.get_response(200, {"character": body.character,
                                    "voice_id": updated["characters"][body.character]["voice"]["elevenlabs_voice_id"]})


def _library(product: str) -> str:
    return os.getenv("ADCLONE_MJ_LIBRARY") or presets.project_root(presets.load(product))


@router.post("/ad-clone/characters/scan", summary="Import Midjourney renders dropped into the watched inbox")
def scan_inbox(request: Request, product: str = "oxhan"):
    request_id = _guard(request)
    inbox = os.getenv("ADCLONE_MJ_INBOX") or os.path.join(_library(product), "mj-inbox")
    try:
        result = midjourney.import_inbox(inbox, _library(product))
    except _KNOWN as exc:
        raise _typed(request_id, exc) from exc
    return utils.get_response(200, result)


@router.post("/ad-clone/characters/tag", summary="Tag an uploaded Midjourney image to a character or still")
def tag_image(request: Request, body: MjTagRequest):
    request_id = _guard(request)
    try:
        root = _library(body.product)
        manifest = midjourney.tag_upload(midjourney.load_manifest(root), key=body.key, tag=body.tag)
        midjourney.save_manifest(root, manifest)
    except _KNOWN as exc:
        raise _typed(request_id, exc) from exc
    return utils.get_response(200, {"tagged": manifest[-1], "total": len(manifest)})


__all__ = ["router"]
