"""Apps shelf routes (MH8) and talking scenes (MH6, behind PRESENTER_LIVE).

Public:
* ``GET  /api/v1/apps``                      apps with a live preview loop, price first

Signed in:
* ``POST /api/v1/apps/{app_id}/quote``       the price for these inputs
* ``POST /api/v1/apps/{app_id}/plan``        the create call for create-flow apps
* ``POST /api/v1/apps/{app_id}/runs``        start it with the price you saw
* ``GET  /api/v1/apps/runs/{job_id}``        progress and the result
* ``GET  /api/v1/scenes``, ``POST /api/v1/scenes/{scene_id}/quote``,
  ``POST /api/v1/scenes/{scene_id}/runs``, ``GET /api/v1/scenes/runs/{job_id}``:
  404 until ``PRESENTER_LIVE`` is on.
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Request, Response
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.services.avatar import scenes
from app.utils import utils

from . import service

router = new_router()
CACHE_CONTROL = "public, max-age=60, s-maxage=300"


class Inputs(BaseModel):
    image_key: str = Field("", max_length=512)
    image_key_2: str = Field("", max_length=512)
    video_key: str = Field("", max_length=512)
    music_id: str = Field("", max_length=120)
    text: str = Field("", max_length=600)
    choice: str = Field("", max_length=60)


class RunRequest(BaseModel):
    inputs: Inputs
    quoted_credits: int = Field(..., ge=0)


class SceneRequest(BaseModel):
    character_id: str = Field(..., min_length=1, max_length=32)
    script: str = Field(..., min_length=1, max_length=900)
    product_key: str = Field("", max_length=512)
    quoted_credits: int = Field(..., ge=0)


def _raise(exc: Any, request_id: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}",
                         data={"code": exc.code})


def enqueue(job_id: str) -> str:
    from .tasks import enqueue as _enqueue

    return _enqueue(job_id)


def enqueue_scene(job_id: str) -> str:
    from .tasks import enqueue_scene as _enqueue

    return _enqueue(job_id)


@router.get("/apps", summary="Apps shelf: one-input tools with a live preview (public)")
def list_apps(response: Response):
    response.headers["Cache-Control"] = CACHE_CONTROL
    return utils.get_response(200, {"apps": service.shelf()})


@router.post("/apps/{app_id}/quote", summary="Price an app run for these inputs")
def quote_app(request: Request, body: Inputs, app_id: str = Path(..., max_length=64)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            price = service.quote(session, str(user.id), app_id, body.model_dump())
        except service.AppError as exc:
            raise _raise(exc, request_id) from exc
    return utils.get_response(200, price)


@router.post("/apps/{app_id}/plan", summary="The create call for a create-flow app")
def plan_app(request: Request, body: Inputs, app_id: str = Path(..., max_length=64)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            plan = service.plan(session, str(user.id), app_id, body.model_dump())
        except service.AppError as exc:
            raise _raise(exc, request_id) from exc
    return utils.get_response(200, plan)


@router.post("/apps/{app_id}/runs", summary="Run an app with the quoted price")
def run_app(request: Request, body: RunRequest, app_id: str = Path(..., max_length=64)):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            job = service.start(session, str(user.id), app_id, body.inputs.model_dump(), body.quoted_credits)
        except service.AppError as exc:
            raise _raise(exc, request_id) from exc
        job_id = job.id
    try:
        enqueue(job_id)
    except Exception as exc:  # noqa: BLE001 - an enqueue failure refunds
        logger.error(f"app run {job_id} enqueue failed: {exc}")
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            job.state, job.error = service.TASK_STATE_FAILED, "could not start"
            service.refund(session, job)
        raise HttpException(task_id=request_id, status_code=502, message=f"{request_id}: could not start",
                            data={"code": "enqueue_failed"}) from exc
    return utils.get_response(200, {"job_id": job_id, "state": service.TASK_STATE_PROCESSING})


@router.get("/apps/runs/{job_id}", summary="App run progress and result")
def get_run(request: Request, job_id: str = Path(..., max_length=32)):
    from app.models.db.models import Job

    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = session.get(Job, job_id)
        if job is None or job.kind != service.JOB_KIND or str(job.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: not found")
        view = service.job_view(job)
    return utils.get_response(200, view)


def _scenes_live(request_id: str) -> None:
    if not scenes.presenter_live():
        raise HttpException(task_id=request_id, status_code=404, message="Not Found")


@router.get("/scenes", summary="Talking scenes (only while presenters are live)")
def list_scenes(request: Request):
    request_id = base.get_task_id(request)
    _scenes_live(request_id)
    return utils.get_response(200, {"scenes": [scenes.scene_view(s) for s in scenes.scenes()]})


@router.post("/scenes/{scene_id}/quote", summary="Price a talking scene")
def quote_scene(request: Request, scene_id: str = Path(..., max_length=40)):
    request_id = base.get_task_id(request)
    _scenes_live(request_id)
    if scenes.get(scene_id) is None:
        raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: scene not found")
    try:
        price = scenes.quote()
    except scenes.SceneError as exc:
        raise _raise(exc, request_id) from exc
    return utils.get_response(200, {k: v for k, v in price.items() if k != "provider"})


@router.post("/scenes/{scene_id}/runs", summary="Make a talking scene with the quoted price")
def run_scene(request: Request, body: SceneRequest, scene_id: str = Path(..., max_length=40)):
    request_id = base.get_task_id(request)
    _scenes_live(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            job = scenes.start(session, str(user.id), scene_id, character_id=body.character_id, script=body.script,
                               quoted_credits=body.quoted_credits, product_key=body.product_key)
        except scenes.SceneError as exc:
            raise _raise(exc, request_id) from exc
        job_id = job.id
    try:
        enqueue_scene(job_id)
    except Exception as exc:  # noqa: BLE001 - an enqueue failure refunds
        logger.error(f"scene {job_id} enqueue failed: {exc}")
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            job.state, job.error = scenes.TASK_STATE_FAILED, "could not start"
            scenes.refund(session, job)
        raise HttpException(task_id=request_id, status_code=502, message=f"{request_id}: could not start",
                            data={"code": "enqueue_failed"}) from exc
    return utils.get_response(200, {"job_id": job_id, "state": scenes.TASK_STATE_PROCESSING})


@router.get("/scenes/runs/{job_id}", summary="Talking scene progress, checks and result")
def get_scene(request: Request, job_id: str = Path(..., max_length=32)):
    from app.models.db.models import Job

    request_id = base.get_task_id(request)
    _scenes_live(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = session.get(Job, job_id)
        if job is None or job.kind != scenes.JOB_KIND or str(job.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: not found")
        view = scenes.job_view(job)
    return utils.get_response(200, view)
