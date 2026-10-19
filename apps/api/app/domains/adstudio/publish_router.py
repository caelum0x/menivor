"""HTTP adapter for Ad Studio "Publish and test".

* ``GET  /ad-studio/projects/{id}/tests``                  readiness + eligible ads + every test's results
* ``POST /ad-studio/projects/{id}/tests``                  start a test (publish directly, or track manually)
* ``POST /ad-studio/projects/{id}/tests/{batch}/check``    read the numbers now
* ``POST /ad-studio/projects/{id}/tests/{batch}/stop``     cancel unposted posts and stop the loop
* ``POST /ad-studio/projects/{id}/tests/{batch}/remake``   render new hooks of the winning ad (free)

Authenticated and owner-scoped; a foreign or unknown project/test reads as 404.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.adstudio import publish_gate, publish_results, publish_test
from app.domains.adstudio.repository import AdStudioRepository
from app.domains.adstudio.service import AdStudioError, sync_jobs
from app.domains.adstudio.views import _presign, _r2
from app.domains.adstudio.worker import dispatch_render
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_BATCH = r"^[a-f0-9]{32}$"


class StartTestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["publish", "manual"] = "publish"
    platforms: list[str] = Field(default_factory=list, max_length=3)
    variant_ids: list[str] = Field(default_factory=list, max_length=publish_test.MAX_TEST_ADS)


class RemakeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accept_low_confidence: bool = False


def _error(request_id: str, exc: AdStudioError) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc.message}")


def _user(request: Request, request_id: str) -> str:
    require_database(request_id)
    with get_session() as session:
        return str(resolve_principal(request, session, request_id).id)


def _tests_payload(session: Any, user_id: str, project: Any) -> dict[str, Any]:
    variants = AdStudioRepository(session).variants(project.id)
    jobs = sync_jobs(session, variants)
    eligible = publish_test.eligible_variants(variants, jobs)
    r2 = _r2()
    return {
        "readiness": publish_gate.readiness(session, user_id, ad_count=min(len(eligible), publish_test.MAX_TEST_ADS)),
        "eligible_variant_ids": [v.id for v in eligible],
        "min_ads": publish_test.MIN_TEST_ADS,
        "max_ads": publish_test.MAX_TEST_ADS,
        "tests": publish_results.project_tests(session, user_id, variants, lambda key: _presign(r2, key)),
    }


def _payload(request: Request, request_id: str, project_id: str) -> dict[str, Any]:
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
        project = AdStudioRepository(session).get_owned_project(user_id, project_id)
        if project is None:
            raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: project not found")
        return _tests_payload(session, user_id, project)


@router.get("/ad-studio/projects/{project_id}/tests", summary="Publish-and-test readiness and results")
def get_tests(request: Request, project_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    require_database(request_id)
    return utils.get_response(200, _payload(request, request_id, project_id))


@router.post("/ad-studio/projects/{project_id}/tests", summary="Publish finished ads and test them")
def start_test(request: Request, body: StartTestBody, project_id: str = Path(..., max_length=32)):
    request_id = base.get_task_id(request)
    user_id = _user(request, request_id)
    enforce_rate_limit(request, f"adstudio:test:{user_id}", limit=10, window_s=3600)
    try:
        started = publish_test.start_test(
            user_id, project_id, variant_ids=[str(v)[:32] for v in body.variant_ids],
            mode=body.mode, platforms=body.platforms,
        )
    except AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, {**started, **_payload(request, request_id, project_id)})


@router.post("/ad-studio/projects/{project_id}/tests/{batch_id}/check", summary="Read a test's numbers now")
def check_test(request: Request, project_id: str = Path(..., max_length=32), batch_id: str = Path(..., pattern=_BATCH)):
    request_id = base.get_task_id(request)
    user_id = _user(request, request_id)
    enforce_rate_limit(request, f"adstudio:test-check:{user_id}", limit=30, window_s=3600)
    try:
        publish_test.check_now(user_id, project_id, batch_id)
    except AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, _payload(request, request_id, project_id))


@router.post("/ad-studio/projects/{project_id}/tests/{batch_id}/stop", summary="Stop a test")
def stop_test(request: Request, project_id: str = Path(..., max_length=32), batch_id: str = Path(..., pattern=_BATCH)):
    request_id = base.get_task_id(request)
    user_id = _user(request, request_id)
    try:
        canceled = publish_test.stop_test(user_id, project_id, batch_id)
    except AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, {"canceled_posts": canceled, **_payload(request, request_id, project_id)})


@router.post("/ad-studio/projects/{project_id}/tests/{batch_id}/remake", summary="Remake the winning ad")
def remake_test_winner(
    request: Request, body: RemakeBody,
    project_id: str = Path(..., max_length=32), batch_id: str = Path(..., pattern=_BATCH),
):
    request_id = base.get_task_id(request)
    user_id = _user(request, request_id)
    enforce_rate_limit(request, f"adstudio:test-remake:{user_id}", limit=10, window_s=3600)
    try:
        result = publish_test.remake_winner(
            user_id, project_id, batch_id, accept_low_confidence=body.accept_low_confidence,
        )
    except AdStudioError as exc:
        raise _error(request_id, exc) from exc
    if not result["replayed"]:
        for variant_id in result["variant_ids"]:
            dispatch_render(variant_id)
    return utils.get_response(200, result)


__all__ = ["router"]
