"""Preset shelf routes (MH2).

* ``GET  /api/v1/presets/shelf``                 public, edge-cached tiles
* ``GET  /api/v1/presets/shelf/{id}``            public, one visible tile
* ``POST /api/v1/presets/shelf/{id}/plan``       signed in: the Create body
* ``POST /api/v1/presets/shelf/{id}/runs``       signed in: stamp the tap time on the caller's job
* ``GET  /api/v1/presets/runs/{job_id}``         signed in: tap-to-first-result timing
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Path, Request, Response
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.utils import utils

from . import service

router = new_router()
CACHE_CONTROL = "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
MAX_RUN_AGE = timedelta(hours=2)
CLOCK_SKEW = timedelta(seconds=60)


class PlanRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=600)
    image_key: str | None = Field(default=None, max_length=512)
    brand_kit_id: str | None = Field(default=None, max_length=32)
    character_id: str | None = Field(default=None, max_length=32)


class RunRequest(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=32)
    opened_at: str = Field(..., min_length=10, max_length=40)


def _not_found(request_id: str, what: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=404, message=f"{request_id}: {what} not found")


def _visible(preset_id: str, request_id: str):
    try:
        return service.visible_preset(preset_id)
    except service.PresetNotFound as exc:
        raise _not_found(request_id, "preset") from exc


@router.get("/presets/shelf", summary="Preset shelf (public)")
def list_shelf(request: Request, response: Response):
    response.headers["Cache-Control"] = CACHE_CONTROL
    return utils.get_response(200, {"presets": service.shelf()})


@router.get("/presets/shelf/{preset_id}", summary="One preset tile (public)")
def get_tile(request: Request, response: Response, preset_id: str = Path(..., max_length=64)):
    request_id = base.get_task_id(request)
    _visible(preset_id, request_id)
    tile = next(t for t in service.shelf() if t["id"] == preset_id)
    response.headers["Cache-Control"] = CACHE_CONTROL
    return utils.get_response(200, tile)


@router.post("/presets/shelf/{preset_id}/plan", summary="The Create call for a preset tile")
def plan_preset(request: Request, body: PlanRequest, preset_id: str = Path(..., max_length=64)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    from app.domains.characters import hub

    brand = character = None
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            if body.brand_kit_id:
                brand = hub.brand_for_user(session, str(user.id), body.brand_kit_id)
            if body.character_id:
                character = hub.character_for_user(session, str(user.id), body.character_id)
        except hub.HubError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}",
                                data={"code": exc.code}) from exc
    _visible(preset_id, request_id)
    try:
        plan = service.resolve(preset_id, subject=body.subject, image_key=body.image_key, brand=brand,
                               character=character)
    except service.PresetInputError as exc:
        raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: {exc}",
                            data={"code": "preset_input"}) from exc
    return utils.get_response(200, plan)


def _parse_opened(value: str, request_id: str) -> datetime:
    try:
        opened = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HttpException(task_id=request_id, status_code=400, message=f"{request_id}: bad opened_at") from exc
    opened = opened if opened.tzinfo else opened.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if opened > now + CLOCK_SKEW or opened < now - MAX_RUN_AGE:
        raise HttpException(task_id=request_id, status_code=400,
                            message=f"{request_id}: opened_at must be within the last two hours")
    return opened


@router.post("/presets/shelf/{preset_id}/runs", summary="Record when a preset tile was tapped")
def record_run(request: Request, body: RunRequest, preset_id: str = Path(..., max_length=64)):
    from app.models.db.models import Job

    request_id = base.get_task_id(request)
    _require_db(request_id)
    preset = _visible(preset_id, request_id)
    opened = _parse_opened(body.opened_at, request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = session.get(Job, body.job_id)
        if job is None or str(job.user_id) != str(user.id):
            raise _not_found(request_id, "job")
        run = {"preset_id": preset.id, "opened_at": opened.isoformat()}
        job.params = {**dict(job.params or {}), "preset_run": run}
        session.flush()
    return utils.get_response(200, {"job_id": body.job_id, **run})


@router.get("/presets/runs/{job_id}", summary="Tap-to-first-result timing for a preset run")
def get_run(request: Request, job_id: str = Path(..., max_length=32)):
    from app.models.db.models import Job

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = session.get(Job, job_id)
        if job is None or str(job.user_id) != str(user.id):
            raise _not_found(request_id, "run")
        view = service.run_view({"state": job.state, "updated_at": job.updated_at, "params": job.params})
    if view is None:
        raise _not_found(request_id, "run")
    return utils.get_response(200, {"job_id": job_id, **view})
