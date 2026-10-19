"""A/B experiment HTTP surface (P7) — create, ingest retention, evaluate winner.

Drives the 1-body/N-hooks retention loop over the API:

    POST /experiments                         create an experiment with N hook variants
    GET  /experiments/{key}                   the experiment + its variants + verdict
    POST /experiments/{key}/variants/{id}/metrics  ingest a variant's retention snapshot
    POST /experiments/{key}/evaluate          run winner selection (persists the verdict)

Auth + owner-scoping + DB reuse the shared jobs-controller helpers. Import-safe.
"""

from __future__ import annotations

from fastapi import Path, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.api_dependencies import (
        get_session,
        require_database as _require_db,
        resolve_principal as _resolve_user,
    )
    from app.domains.publishing.experiment_repo import ExperimentError, ExperimentRepository

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = exc

router = new_router()


class CreateExperimentBody(BaseModel):
    experiment_key: str = Field(..., max_length=80)
    hook_refs: list[str] = Field(default_factory=list, min_length=2, max_length=20)
    body_ref: str = Field(default="", max_length=120)


class MetricsBody(BaseModel):
    views: int = Field(..., ge=0)
    # Omitted / null = not measured (stored as NULL, excluded from scoring).
    completion_rate: float | None = Field(default=None, ge=0, le=1)
    avg_watch_frac: float = Field(default=0.0, ge=0, le=1)
    rewatch_rate: float | None = Field(default=None, ge=0, le=1)
    engagement_rate: float = Field(default=0.0, ge=0, le=1)


def _guard(request_id: str) -> None:
    if _IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: experiments layer unavailable: {_IMPORT_ERROR}")


def _exp_view(exp, variants) -> dict:
    return {
        "id": exp.id, "experiment_key": exp.experiment_key, "status": exp.status,
        "body_ref": exp.body_ref, "winner_variant_id": exp.winner_variant_id,
        "winner_hook_ref": exp.winner_hook_ref,
        "variants": [
            {"id": v.id, "hook_ref": v.hook_ref, "views": v.views,
             "completion_rate": v.completion_rate, "avg_watch_frac": v.avg_watch_frac,
             "rewatch_rate": v.rewatch_rate, "engagement_rate": v.engagement_rate,
             "measured": {"completion_rate": v.completion_rate is not None,
                          "rewatch_rate": v.rewatch_rate is not None}}
            for v in variants
        ],
    }


@router.post("/experiments", summary="Create a 1-body/N-hooks experiment")
def create_experiment(request: Request, body: CreateExperimentBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = ExperimentRepository(session)
        try:
            exp = repo.create(
                user_id=user.id, experiment_key=body.experiment_key,
                hook_refs=body.hook_refs, body_ref=body.body_ref,
            )
        except ExperimentError as exc:
            raise HttpException(task_id=request_id, status_code=422, message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, _exp_view(exp, repo.variants(exp.id)))


@router.get("/experiments/{experiment_key}", summary="Get an experiment + its variants")
def get_experiment(request: Request, experiment_key: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = ExperimentRepository(session)
        exp = repo.get_by_key(experiment_key)
        if exp is None or str(exp.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: experiment not found")
        return utils.get_response(200, _exp_view(exp, repo.variants(exp.id)))


@router.post("/experiments/{experiment_key}/variants/{variant_id}/metrics",
             summary="Ingest a variant's retention metrics")
def ingest_metrics(request: Request, body: MetricsBody, experiment_key: str = Path(...),
                   variant_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = ExperimentRepository(session)
        exp = repo.get_by_key(experiment_key)
        if exp is None or str(exp.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: experiment not found")
        try:
            variant = repo.ingest_metrics(
                experiment_key=experiment_key, variant_id=variant_id, **body.model_dump()
            )
        except ExperimentError as exc:
            raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: {exc}") from exc
        return utils.get_response(200, {"id": variant.id, "hook_ref": variant.hook_ref, "views": variant.views})


@router.post("/experiments/{experiment_key}/evaluate", summary="Select the retention-weighted winner")
def evaluate(request: Request, experiment_key: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = ExperimentRepository(session)
        exp = repo.get_by_key(experiment_key)
        if exp is None or str(exp.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: experiment not found")
        exp = repo.evaluate(experiment_key)
        return utils.get_response(200, _exp_view(exp, repo.variants(exp.id)))
