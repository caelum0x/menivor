"""Motion HTTP domain — browse + detail + compile the camera-move catalog.

Routes under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`, MPT
envelope + :class:`HttpException` like the templates domain. The engine is pure
code (no DB), so browse/compile never 503; an unknown preset is a clean 422 via
:class:`MotionPresetError` (compile) or 404 (detail). Compile records a
best-effort history row that never fails the response.

* ``GET  /motion``                    list all camera-move presets
* ``GET  /motion/history``            caller's recent compiled/dispatched moves
* ``GET  /motion/{preset_id}``        one preset's detail
* ``POST /motion/{preset_id}/compile`` preset + intensity → MotionPlan view
"""

from __future__ import annotations

from fastapi import Path, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

from . import service
from .catalog import MotionPresetError
from .schemas import CompileMotionRequest, motion_detail, motion_summary

# Guarded persistence — best-effort motion-render history. The core catalog/
# compile endpoints stay DB-free; history degrades to 503 when the DB is absent.
try:
    from app.core.api_dependencies import (
        get_session,
        require_database as _require_db,
        resolve_principal as _resolve_user,
    )
    from app.domains.motion.repository import MotionRenderRepository

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _DB_IMPORT_ERROR = exc

router = new_router()


def _record_render_best_effort(request: Request, request_id: str, plan_view: dict) -> None:
    """Record a compiled motion for history (never fails the response)."""
    if _DB_IMPORT_ERROR is not None:
        return
    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            model = plan_view.get("model") or {}
            hints = model.get("provider_hints") or []
            MotionRenderRepository(session).create(
                user_id=user.id,
                preset_id=plan_view.get("preset_id", ""),
                motion_class=plan_view.get("motion_class", "filter"),
                intensity=int((plan_view.get("filter") or model or {}).get("intensity", 50) or 50),
                plan=plan_view,
                provider_key=str(hints[0]) if hints else "",
            )
    except Exception:  # noqa: BLE001 - history is best-effort, never fatal
        pass


@router.get("/motion", summary="List camera-move presets")
def list_motion(request: Request):
    """Browse the versioned motion catalog (filter / model / hybrid moves)."""
    _ = base.get_task_id(request)
    return utils.get_response(
        200, {"motions": [motion_summary(m) for m in service.list_motions()]}
    )


# NOTE: this literal route MUST precede ``/motion/{preset_id}`` so the path
# ``/motion/history`` isn't captured as preset_id="history".
@router.get("/motion/history", summary="Caller's recent compiled motions")
def motion_history(request: Request, limit: int = 50):
    """A creator's own motion-render history (reproducibility)."""
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: motion history unavailable")
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = MotionRenderRepository(session).list_for_user(
            user.id, limit=max(1, min(100, limit))
        )
        return utils.get_response(200, {
            "history": [
                {"id": r.id, "preset_id": r.preset_id, "motion_class": r.motion_class,
                 "intensity": r.intensity, "provider_key": r.provider_key,
                 "output_ref": r.output_ref}
                for r in rows
            ],
        })


@router.get("/motion/{preset_id}", summary="Get one motion preset")
def get_motion(request: Request, preset_id: str = Path(...)):
    """Full preset detail: resolved filter and/or model sub-specs."""
    request_id = base.get_task_id(request)
    entry = service.get_motion(preset_id)
    if entry is None:
        raise HttpException(task_id=request_id, status_code=404,
                            message=f"{request_id}: unknown motion preset {preset_id!r}")
    return utils.get_response(200, motion_detail(entry))


@router.post("/motion/{preset_id}/compile", summary="Compile a preset → MotionPlan")
def compile_motion(request: Request, body: CompileMotionRequest, preset_id: str = Path(...)):
    """Validate + compile the preset into a deterministic MotionPlan view."""
    request_id = base.get_task_id(request)
    try:
        view = service.resolve_for_render(preset_id, intensity=body.intensity)
    except MotionPresetError as exc:
        raise HttpException(task_id=request_id, status_code=422,
                            message=f"{request_id}: {exc}") from exc
    _record_render_best_effort(request, request_id, view)
    return utils.get_response(200, view)
