"""Capture HTTP routes - URL -> recorded promo video -> reel-pipeline ads.

* ``GET    /capture/native``         whether native game capture is enabled here
* ``POST   /capture/detect``         classify a URL (no fetch)
* ``POST   /capture``                start a capture (website, native game, store listing)
* ``GET    /capture``                caller's captures
* ``GET    /capture/{id}``           status, outputs, screenshots, script draft
* ``POST   /capture/{id}/retry``     retry a failed/canceled capture
* ``POST   /capture/{id}/cancel``    cancel a queued/running capture
* ``DELETE /capture/{id}``           delete the capture record
* ``POST   /capture/{id}/ads``       build ``POST /jobs`` bodies from the capture

Every route is authenticated and owner-scoped. Store listings and every
browser request go through the shared SSRF guard.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from types import SimpleNamespace
from typing import Any, Literal, Optional

from fastapi import Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.capture import ads, service, views
from app.domains.capture.models import STATUS_SUCCEEDED
from app.domains.capture.worker import dispatch_capture
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

Kind = Literal["auto", "website", "native_game", "app_store", "play_store"]


class DetectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=4, max_length=2048)


class NativeBody(BaseModel):
    """A native game running in a simulator/emulator on the capture host."""

    model_config = ConfigDict(extra="forbid")

    platform: Literal["ios", "android"]
    #: Simulator UDID or ``booted`` (iOS), adb serial such as ``emulator-5554`` (Android).
    device: str = Field(default="", max_length=64)
    #: Bundle id / package name; launches the game when there is no deep link.
    app_id: str = Field(default="", max_length=150)
    #: Optional deep link that opens the game (e.g. into its demo mode).
    deep_link: str = Field(default="", max_length=512)
    #: Game name used in the drafted script.
    title: str = Field(default="", max_length=80)
    #: Seconds to wait after launch before recording.
    settle_s: int = Field(default=4, ge=0, le=30)


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Required for websites and store listings; unused for ``native_game``.
    url: str = Field(default="", max_length=2048)
    kind: Kind = "auto"
    native: Optional[NativeBody] = None
    formats: list[str] = Field(default_factory=lambda: ["9:16", "16:9"], min_length=1, max_length=3)
    duration_s: Optional[int] = Field(default=None, ge=5, le=60)
    cursor: bool = True


class AdsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["captions", "voiceover", "avatar"] = "captions"
    aspects: list[str] = Field(default_factory=list, max_length=3)
    script: str = Field(..., min_length=1, max_length=ads.MAX_SCRIPT_CHARS)
    language: Literal["en", "tr", "auto"] = "en"
    avatar_id: str = Field(default="", max_length=64)
    voice_id: str = Field(default="", max_length=128)
    voice_name: str = Field(default="", max_length=64)
    caption_style: str = Field(default="", max_length=64)
    platforms: list[str] = Field(default_factory=list, max_length=6)


def _error(request_id: str, status_code: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status_code, message=f"{request_id}: {message}")


def _user_id(request: Request, session: Any, request_id: str) -> str:
    return str(resolve_principal(request, session, request_id).id)


def _owned(session: Any, request: Request, request_id: str, capture_id: str) -> tuple[str, Any]:
    user_id = _user_id(request, session, request_id)
    job = service.get_owned(session, user_id, capture_id)
    if job is None:
        raise _error(request_id, 404, "capture not found")
    return user_id, job


@router.get("/capture/native", summary="Whether this server can record native games from a simulator")
def native_status(request: Request):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        _user_id(request, session, request_id)
    low, default, high = service.DURATION_LIMITS["native_game"]
    return utils.get_response(200, {
        "enabled": service.native_enabled(),
        "platforms": ["ios", "android"],
        "app_ids": list(service.native_allowed_app_ids()),
        "duration": {"min": low, "default": default, "max": high},
    })


@router.post("/capture/detect", summary="Classify a URL for capture (no fetch)")
def detect(request: Request, body: DetectBody):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        _user_id(request, session, request_id)
    try:
        source = service.resolve_source(body.url)
    except service.CaptureError as exc:
        raise _error(request_id, exc.status_code, exc.message) from exc
    limits = service.DURATION_LIMITS.get(source.kind)
    return utils.get_response(200, {
        "kind": source.kind,
        "url": source.url,
        "ref": source.ref,
        "duration": {"min": limits[0], "default": limits[1], "max": limits[2]} if limits else None,
    })


@router.post("/capture", summary="Start a capture of a website, native game or store listing")
def create_capture(request: Request, body: CreateBody):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        if body.kind == "native_game":
            if body.native is None:
                raise service.CaptureError(422, "native game captures need the platform and device")
            source, target = service.resolve_native(body.native.model_dump())
            options = service.build_options(source, body.formats, body.duration_s, False, native=target)
        else:
            if len(body.url.strip()) < 4:
                raise service.CaptureError(422, "paste the link to capture")
            source = service.resolve_source(body.url, body.kind)
            options = service.build_options(source, body.formats, body.duration_s, body.cursor)
        with get_session() as session:
            user_id = _user_id(request, session, request_id)
            enforce_rate_limit(request, f"capture:create:{user_id}", limit=20, window_s=3600)
            job = service.create_capture(session, user_id=user_id, source=source, options=options)
            capture_id = job.id
    except service.CaptureError as exc:
        raise _error(request_id, exc.status_code, exc.message) from exc
    task_id = dispatch_capture(capture_id)
    with get_session() as session:
        job = service.get_owned(session, user_id, capture_id)
        if job is not None and task_id:
            job.task_id = task_id
        data = views.capture_detail(job) if job is not None else {"id": capture_id}
    return utils.get_response(200, data)


@router.get("/capture", summary="List the caller's captures")
def list_captures(request: Request, limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id = _user_id(request, session, request_id)
        service.sweep_stale(session, user_id)
        rows, total = service.list_owned(session, user_id, limit=limit, offset=offset)
        r2 = views.r2_client()
        data = {
            "captures": [views.capture_summary(row, r2) for row in rows],
            "total": total,
            "has_more": offset + len(rows) < total,
        }
    return utils.get_response(200, data)


@router.get("/capture/{capture_id}", summary="Capture status, outputs and screenshots")
def get_capture(request: Request, capture_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id, job = _owned(session, request, request_id, capture_id)
        service.sweep_stale(session, user_id)
        data = views.capture_detail(job)
    return utils.get_response(200, data)


@router.post("/capture/{capture_id}/retry", summary="Retry a failed capture")
def retry_capture(request: Request, capture_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        with get_session() as session:
            _, job = _owned(session, request, request_id, capture_id)
            service.retry(session, job)
    except service.CaptureError as exc:
        raise _error(request_id, exc.status_code, exc.message) from exc
    dispatch_capture(capture_id)
    return utils.get_response(200, {"id": capture_id, "status": "queued"})


@router.post("/capture/{capture_id}/cancel", summary="Cancel a running capture")
def cancel_capture(request: Request, capture_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        with get_session() as session:
            _, job = _owned(session, request, request_id, capture_id)
            service.cancel(job)
    except service.CaptureError as exc:
        raise _error(request_id, exc.status_code, exc.message) from exc
    return utils.get_response(200, {"id": capture_id, "status": "canceled"})


@router.delete("/capture/{capture_id}", summary="Delete a capture record")
def delete_capture(request: Request, capture_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        _, job = _owned(session, request, request_id, capture_id)
        if job.status == "running":
            raise _error(request_id, 409, "cancel the capture before deleting it")
        session.delete(job)
    # Rendered files stay in the media library (registered assets).
    return utils.get_response(200, {"deleted": True})


def _voiceover_key(user_id: str, capture_id: str, script: str, voice_name: str) -> str:
    work = tempfile.mkdtemp(prefix=f"capture-vo-{capture_id[:8]}-")
    try:
        path = ads.synthesize_voiceover(script, voice_name, os.path.join(work, "narration.mp3"))
        from app.domains.capture.worker import _register_asset
        from app.platform.storage.r2 import get_r2_client

        key = f"uploads/{uuid.uuid4().hex}.mp3"
        get_r2_client().put_file(path, key, content_type="audio/mpeg")
        _register_asset(user_id, capture_id, key, "audio", "audio/mpeg", path)
        return key
    finally:
        shutil.rmtree(work, ignore_errors=True)


@router.post("/capture/{capture_id}/ads", summary="Build reel job requests from a finished capture")
def build_ads(request: Request, body: AdsBody, capture_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id, job = _owned(session, request, request_id, capture_id)
        if job.status != STATUS_SUCCEEDED:
            raise _error(request_id, 409, "the capture has not finished yet")
        snapshot = SimpleNamespace(
            id=job.id, source_url=job.source_url, source_kind=job.source_kind, meta=dict(job.meta or {}),
        )
    outputs = [dict(o) for o in snapshot.meta.get("outputs") or []]
    wanted = [o for o in outputs if not body.aspects or o.get("aspect") in body.aspects]
    if not wanted:
        raise _error(request_id, 422, "none of the requested formats were captured")
    enforce_rate_limit(request, f"capture:ads:{user_id}", limit=40, window_s=3600)
    try:
        voiceover = ""
        if body.mode == "voiceover":
            # Narration is generated outside the DB session (network TTS call).
            voiceover = _voiceover_key(user_id, capture_id, body.script, body.voice_name or ads.FREE_VOICES[0])
        requests_out = [
            {
                "aspect": output.get("aspect"),
                "job_request": ads.build_job_request(
                    snapshot, output, mode=body.mode, script=body.script, language=body.language,
                    avatar_id=body.avatar_id, voice_id=body.voice_id, caption_style=body.caption_style,
                    voiceover_key=voiceover, platforms=body.platforms,
                ),
            }
            for output in wanted
        ]
    except ads.AdRequestError as exc:
        raise _error(request_id, 422, str(exc)) from exc
    return utils.get_response(200, {"capture_id": capture_id, "mode": body.mode, "requests": requests_out})
