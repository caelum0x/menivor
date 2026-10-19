"""HTTP surface for one-flow run experiments.

    POST /experiments/runs              register 2-3 reels as one 1-body/N-hooks run
    GET  /experiments/runs/{batch_id}   the run's experiment, synced with the loop

Topic runs are registered by ``POST /jobs`` itself when it fans a generated
script out into hook-styled variants. Link runs create one job per hook (each
with its own typed script), so the client registers them here once they have
all started. Owner-scoped; unknown and foreign ids both read as 404.

A plain ``APIRouter`` without its own ``/api/v1`` prefix: it is mounted into the
reels router, which carries the prefix.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.api_dependencies import (
        get_session,
        require_database as _require_db,
        resolve_principal as _resolve_user,
    )

    from .registration import (
        MAX_RUN_VARIANTS,
        MIN_RUN_VARIANTS,
        RunRegistrationError,
        RunVariant,
        open_winner_loop,
        register_run,
        sync_run,
    )

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - persistence layer absent
    _IMPORT_ERROR = exc

router = APIRouter()

_BATCH_ID_PATTERN = r"^[A-Za-z0-9_-]{6,64}$"
_JOB_ID_PATTERN = r"^[A-Za-z0-9_-]{6,64}$"


class RunVariantBody(BaseModel):
    job_id: str = Field(..., pattern=_JOB_ID_PATTERN)
    hook_style: str = Field(default="", max_length=32)


class RegisterRunBody(BaseModel):
    variants: list[RunVariantBody] = Field(..., min_length=2, max_length=3)
    body_ref: str = Field(default="", max_length=120)


def _guard(request_id: str) -> None:
    if _IMPORT_ERROR is not None:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: experiments layer unavailable: {_IMPORT_ERROR}",
        )


def _loop_summary(state: dict) -> dict:
    if not state:
        return {"status": "", "mode": ""}
    return {
        "status": str(state.get("status") or ""),
        "mode": str(state.get("mode") or ""),
        "note": str(state.get("note") or ""),
        "winner_job_id": str(state.get("winner_job_id") or ""),
        "conclusive": bool(state.get("conclusive")),
    }


def _run_view(batch_id: str, experiment, variants, state: dict) -> dict:
    return {
        "batch_id": batch_id,
        "experiment_key": experiment.experiment_key,
        "status": experiment.status,
        "winner_hook_ref": experiment.winner_hook_ref,
        "variants": [
            {
                "id": v.id,
                "hook_ref": v.hook_ref,
                "job_id": v.hook_ref.rsplit(":", 1)[-1],
                "hook_style": v.hook_ref.rsplit(":", 1)[0] if ":" in v.hook_ref else "",
                "views": v.views,
                "avg_watch_frac": v.avg_watch_frac,
                "engagement_rate": v.engagement_rate,
                # null = not measured by any platform yet (not 0%).
                "completion_rate": v.completion_rate,
                "rewatch_rate": v.rewatch_rate,
            }
            for v in variants
        ],
        "loop": _loop_summary(state),
    }


def _http_error(request_id: str, exc: "RunRegistrationError") -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}")


@router.post("/experiments/runs", summary="Register a multi-hook run as an experiment")
def register_experiment_run(request: Request, body: RegisterRunBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    if not MIN_RUN_VARIANTS <= len(body.variants) <= MAX_RUN_VARIANTS:
        raise HttpException(task_id=request_id, status_code=422,
                            message=f"{request_id}: a run needs {MIN_RUN_VARIANTS}-{MAX_RUN_VARIANTS} variants")
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        user_id = str(user.id)
        try:
            registration = register_run(
                session,
                user_id=user_id,
                variants=[RunVariant(job_id=v.job_id, hook_style=v.hook_style) for v in body.variants],
                body_ref=body.body_ref,
            )
        except RunRegistrationError as exc:
            raise _http_error(request_id, exc) from exc
    # The batch link is committed; the loop reads it in its own transaction.
    loop_state: dict = {}
    loop_error = ""
    try:
        loop_state = open_winner_loop(user_id, registration.batch_id)
    except Exception as exc:  # noqa: BLE001 - the experiment stands; report the loop problem
        loop_error = str(exc)
    return utils.get_response(200, {
        "batch_id": registration.batch_id,
        "experiment_key": registration.experiment_key,
        "created": registration.created,
        "loop": _loop_summary(loop_state),
        **({"loop_error": loop_error} if loop_error else {}),
    })


@router.get("/experiments/runs/{batch_id}", summary="A run's experiment, synced with its winner loop")
def get_experiment_run(request: Request, batch_id: str = Path(..., pattern=_BATCH_ID_PATTERN)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            experiment, variants, state = sync_run(session, user_id=str(user.id), batch_id=batch_id)
        except RunRegistrationError as exc:
            raise _http_error(request_id, exc) from exc
        return utils.get_response(200, _run_view(batch_id, experiment, variants, state))


__all__ = ["router"]
