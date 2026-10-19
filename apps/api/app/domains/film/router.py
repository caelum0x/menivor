"""Film HTTP facade — plan, persist and render a character-consistent film (P9).

* ``POST /film/plan``                                   DB-free plan preview
* ``POST /film/projects``                               plan + persist a project
* ``GET  /film/projects``                               the caller's projects
* ``GET  /film/projects/{id}``                          project + shots (render state synced)
* ``POST /film/projects/{id}/shots/{shot_id}/render``   render one shot (wallet-metered)
* ``POST /film/projects/{id}/render``                   render every not-yet-rendered shot
* ``POST /film/projects/{id}/export``                   stitch every shot into the final MP4
* ``PATCH /film/projects/{id}``                         rename
* ``DELETE /film/projects/{id}``                        cancel in-flight shots (refund) + delete

Shot renders reuse the async-GPU render spine (``RenderExecutor`` + the wallet
hold); the render sweep advances them and folds the render job's terminal state
back onto its shot (``done`` / ``failed``), marking the project ``shots_ready``
once every shot is done. The export step then stitches the shot outputs into one
final video (``final_url`` on the project read).
"""

from __future__ import annotations

import uuid

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

# Guarded persistence — the create/get project endpoints degrade to 503 when the
# DB layer is absent (the /film/plan preview stays DB-free).
try:
    from app.core.api_dependencies import (
        get_session,
        require_database as _require_db,
        resolve_principal as _resolve_user,
    )
    from app.domains.film.repository import FilmRepository
    from app.domains.render.access import resolve_spend_workspace

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _DB_IMPORT_ERROR = exc

router = new_router()


def _build_plan(body):
    from app.domains.characters.consistency import CharacterProfile
    from app.domains.film.orchestrator import plan_film
    from app.domains.storyboard.shotlist import SceneBeat

    beats = [SceneBeat(b.scene_id, b.summary, b.weight, b.dialogue) for b in body.beats]
    c = body.character
    character = CharacterProfile(
        character_id=c.character_id, name=c.name, descriptors=tuple(c.descriptors),
        reference_images=tuple(c.reference_images), style=c.style, lora_ref=c.lora_ref,
        negative=tuple(c.negative),
    )
    return plan_film(beats, character, total_shots=body.total_shots, target_runtime_s=body.target_runtime_s), c


class BeatIn(BaseModel):
    scene_id: str
    summary: str
    weight: float = 1.0
    dialogue: str = ""


class CharacterIn(BaseModel):
    character_id: str
    name: str
    descriptors: list[str] = Field(default_factory=list)
    reference_images: list[str] = Field(default_factory=list)
    style: str = ""
    lora_ref: str = ""
    negative: list[str] = Field(default_factory=list)


class FilmPlanBody(BaseModel):
    beats: list[BeatIn] = Field(default_factory=list, max_length=100)
    character: CharacterIn
    total_shots: int = Field(default=22, ge=1, le=200)
    target_runtime_s: float | None = None


@router.post("/film/plan", summary="Plan a character-consistent multi-shot film")
def plan(request: Request, body: FilmPlanBody):
    """Decompose beats into an identity-locked shot list + execution DAG (preview)."""
    request_id = base.get_task_id(request)
    from app.domains.characters.consistency import CharacterProfile
    from app.domains.film.orchestrator import plan_film
    from app.domains.storyboard.shotlist import SceneBeat

    if not body.beats:
        raise HttpException(task_id=request_id, status_code=422, message=f"{request_id}: beats required")

    beats = [SceneBeat(b.scene_id, b.summary, b.weight, b.dialogue) for b in body.beats]
    c = body.character
    character = CharacterProfile(
        character_id=c.character_id, name=c.name, descriptors=tuple(c.descriptors),
        reference_images=tuple(c.reference_images), style=c.style, lora_ref=c.lora_ref,
        negative=tuple(c.negative),
    )
    fp = plan_film(beats, character, total_shots=body.total_shots, target_runtime_s=body.target_runtime_s)
    return utils.get_response(
        200,
        {
            "total_runtime_s": fp.total_runtime_s,
            "node_order": list(fp.node_order),
            "shots": [
                {
                    "shot_id": sp.shot.shot_id,
                    "scene_id": sp.shot.scene_id,
                    "order": sp.shot.order,
                    "role": sp.shot.role,
                    "camera_motion": sp.shot.camera_motion,
                    "duration_s": sp.shot.duration_s,
                    "prompt": sp.prompt.prompt,
                    "negative_prompt": sp.prompt.negative_prompt,
                    "seed": sp.prompt.seed,
                }
                for sp in fp.shots
            ],
        },
    )


class CreateProjectBody(FilmPlanBody):
    title: str = Field(default="", max_length=200)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _export_view(project) -> dict:
    """Export state + a presigned final video URL when the stitch is done."""
    view = {
        "export_state": getattr(project, "export_state", "") or None,
        "export_error": getattr(project, "export_error", "") or None,
        "exported_at": _iso(getattr(project, "exported_at", None)),
        "final_url": None,
        "final_download_url": None,
    }
    key = str(getattr(project, "final_key", "") or "")
    if key:
        try:
            from app.platform.storage.r2 import get_r2_client

            r2 = get_r2_client()
            view["final_url"] = r2.presign_result_get(key)
            safe = "".join(c for c in (project.title or "film") if c.isalnum() or c in " -_").strip()
            view["final_download_url"] = r2.presign_result_get(
                key, download_name=f"{(safe or 'film')[:60]}.mp4"
            )
        except Exception:  # noqa: BLE001 - a read never fails on presign
            view["final_url"] = None
    return view


@router.post("/film/projects", summary="Plan + persist a film project")
def create_project(request: Request, body: CreateProjectBody):
    """Plan the film and persist it (project + one locked shot row each)."""
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: film persistence unavailable")
    _require_db(request_id)
    if not body.beats:
        raise HttpException(task_id=request_id, status_code=422, message=f"{request_id}: beats required")
    fp, character = _build_plan(body)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        project = FilmRepository(session).create_from_plan(
            fp, user_id=user.id, title=body.title, character_id=character.character_id,
        )
        return utils.get_response(200, {
            "id": project.id, "title": project.title, "status": project.status,
            "shot_count": project.shot_count, "total_runtime_s": project.total_runtime_s,
        })


@router.get("/film/projects/{project_id}", summary="Get a film project + its shots")
def get_project(request: Request, project_id: str):
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: film persistence unavailable")
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = FilmRepository(session)
        project = repo.get(project_id)
        if project is None or str(project.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: project not found")
        shots = repo.shots(project_id)
        renders = _sync_shot_states(session, shots)
        session.refresh(project)
        return utils.get_response(200, {
            "id": project.id, "title": project.title, "status": _status(project.status),
            "total_runtime_s": project.total_runtime_s,
            "shot_count": project.shot_count,
            "created_at": _iso(project.created_at),
            "updated_at": _iso(project.updated_at),
            "can_export": bool(shots) and all(s.status == "done" for s in shots)
            and (project.export_state or "") not in ("queued", "running"),
            **_export_view(project),
            "shots": [
                {"shot_id": s.shot_key, "order": s.order, "role": s.role,
                 "camera_motion": s.camera_motion, "duration_ms": s.duration_ms,
                 "prompt": s.prompt, "seed": s.seed, "status": s.status,
                 "render_job_id": s.render_job_id or None,
                 **renders.get(s.id, {})}
                for s in shots
            ],
        })


# --------------------------------------------------------------------------- #
# Project list + server-side shot rendering
# --------------------------------------------------------------------------- #
DEFAULT_SHOT_MAX_COST_MICROS = 50_000
DEFAULT_SHOT_BACKEND = "runpod"


class RenderShotBody(BaseModel):
    backend: str = Field(default=DEFAULT_SHOT_BACKEND, description="runpod | local_comfyui | rocketride")
    max_cost_micros: int = Field(default=DEFAULT_SHOT_MAX_COST_MICROS, gt=0, le=5_000_000)
    workspace_id: str | None = None
    # Re-render a shot that already finished (e.g. to get a different take).
    rerender: bool = False


def _status(status: str) -> str:
    """Legacy rows said ``assembled`` for "every shot done" — expose the truth."""
    return "shots_ready" if status == "assembled" else status


def _require_film_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: film persistence unavailable")
    _require_db(request_id)


def _owned_project(session, project_id: str, user_id: str, request_id: str):
    project = FilmRepository(session).get(project_id)
    if project is None or str(project.user_id) != str(user_id):
        raise HttpException(task_id=request_id, status_code=404,
                            message=f"{request_id}: project not found")
    return project


def _sync_shot_states(session, shots) -> dict:
    """Fold each shot's render-job terminal state onto the shot; return outputs."""
    from app.models.db.render_repo import RenderJobRepository, row_to_envelope

    from app.services.render.outputs import output_urls

    repo = FilmRepository(session)
    renders = RenderJobRepository(session)
    outputs: dict = {}
    for shot in shots:
        if not shot.render_job_id:
            continue
        row = renders.get(shot.render_job_id)
        if row is None:
            continue
        state = str(row.state or "")
        refs = list(row_to_envelope(row).output_refs)
        outputs[shot.id] = {
            "render_state": state,
            "render_error": row.error or None,
            "output_refs": refs,
            **output_urls(refs),
        }
        if state == "COMPLETED" and shot.status != "done":
            repo.mark_shot(shot.id, status="done")
        elif state in ("FAILED", "CANCELLED") and shot.status != "failed":
            repo.mark_shot(shot.id, status="failed")
    return outputs


def _start_shot_render(
    session, user, project, shot, body: RenderShotBody, request_id: str,
    workspace_id: str | None = None,
) -> dict:
    from app.domains.wallet.service import WalletError, WalletService
    from app.models.db.render_repo import RenderJobRepository
    from app.services.render.execution import ExecutionError, RenderExecutor
    from app.services.render.wallet_gateway import WalletServiceGateway

    # Unique per attempt so a re-render never collides with the previous job id.
    spec = {
        "job_id": f"film-{project.id[:12]}-{str(shot.shot_key)[:32]}-{uuid.uuid4().hex[:8]}",
        "prompt": shot.prompt,
        "negative_prompt": shot.negative_prompt,
        "seed": shot.seed,
        "duration_s": round((shot.duration_ms or 0) / 1000.0, 2),
        "camera_motion": shot.camera_motion,
    }
    wallet = WalletServiceGateway(
        WalletService(session), user_id=user.id, workspace_id=workspace_id,
        correlation_id=request_id,
    )
    try:
        env = RenderExecutor(wallet).start(body.backend, spec, max_cost_micros=body.max_cost_micros)
    except WalletError as exc:
        raise HttpException(task_id=request_id, status_code=exc.status_code,
                            message=f"{request_id}: {exc.message}") from exc
    except ExecutionError as exc:
        raise HttpException(task_id=request_id, status_code=502,
                            message=f"{request_id}: {exc}") from exc
    RenderJobRepository(session).create(
        env, user_id=user.id, workspace_id=workspace_id or "",
        held_cost_micros=body.max_cost_micros, source="film",
        label=f"{project.title or 'Film'} - shot {shot.order + 1}",
    )
    FilmRepository(session).mark_shot(shot.id, status="rendering", render_job_id=env.id)
    if project.status in ("planned", "failed"):
        project.status = "rendering"
        session.flush()
    return {"shot_id": shot.shot_key, "render_job_id": env.id, "state": env.state}


@router.get("/film/projects", summary="List the caller's film projects")
def list_projects(request: Request, limit: int = 50, offset: int = 0):
    request_id = base.get_task_id(request)
    _require_film_db(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = FilmRepository(session).list_for_user(
            user.id, limit=max(1, min(200, int(limit or 50))), offset=max(0, int(offset or 0)),
        )
        return utils.get_response(200, {"projects": [
            {
                "id": p.id, "title": p.title, "status": _status(p.status),
                "shot_count": p.shot_count, "total_runtime_s": p.total_runtime_s,
                "created_at": _iso(p.created_at),
                "export_state": p.export_state or None,
                "has_final": bool(p.final_key),
            }
            for p in rows
        ]})


@router.post("/film/projects/{project_id}/shots/{shot_id}/render", summary="Render one film shot")
def render_shot(request: Request, body: RenderShotBody, project_id: str, shot_id: str):
    request_id = base.get_task_id(request)
    _require_film_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        project = _owned_project(session, project_id, user.id, request_id)
        shots = FilmRepository(session).shots(project_id)
        _sync_shot_states(session, shots)
        shot = next((s for s in shots if s.shot_key == shot_id or s.id == shot_id), None)
        if shot is None:
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: shot not found")
        if shot.status == "rendering":
            raise HttpException(task_id=request_id, status_code=409,
                                message=f"{request_id}: shot is already rendering")
        if shot.status == "done" and not body.rerender:
            raise HttpException(task_id=request_id, status_code=409,
                                message=f"{request_id}: shot is already done; pass rerender=true for a new take")
        if (project.export_state or "") in ("queued", "running"):
            raise HttpException(task_id=request_id, status_code=409,
                                message=f"{request_id}: the film is exporting; wait for it to finish")
        workspace_id = resolve_spend_workspace(session, user.id, body.workspace_id, request_id)
        data = _start_shot_render(session, user, project, shot, body, request_id, workspace_id)
        return utils.get_response(200, data)


@router.post("/film/projects/{project_id}/render", summary="Render every pending shot of a film")
def render_project(request: Request, body: RenderShotBody, project_id: str):
    """Start a render for each shot not yet rendering/done (each wallet-metered).

    Stops at the first wallet/backend error and reports what was started, so a
    partially funded film can be topped up and resumed with the same call.
    """
    request_id = base.get_task_id(request)
    _require_film_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        project = _owned_project(session, project_id, user.id, request_id)
        if (project.export_state or "") in ("queued", "running"):
            raise HttpException(task_id=request_id, status_code=409,
                                message=f"{request_id}: the film is exporting; wait for it to finish")
        # Membership gate once, before any hold against a shared workspace pool.
        workspace_id = resolve_spend_workspace(session, user.id, body.workspace_id, request_id)
        shots = FilmRepository(session).shots(project_id)
        _sync_shot_states(session, shots)
        pending = [s for s in shots if s.status not in ("rendering", "done")]
        started: list[dict] = []
        error = ""
        error_status = 0
        for shot in pending:
            try:
                started.append(
                    _start_shot_render(session, user, project, shot, body, request_id, workspace_id)
                )
            except HttpException as exc:
                error = str(getattr(exc, "message", "") or exc)
                error_status = int(getattr(exc, "status_code", 0) or 0)
                break
        if pending and not started and error:
            # Nothing could start (e.g. 402 insufficient wallet) — a real error,
            # not a 200 with an error string.
            raise HttpException(task_id=request_id, status_code=error_status or 402,
                                message=error)
        return utils.get_response(200, {
            "started": started,
            "remaining": max(0, len(pending) - len(started)),
            "error": error or None,
        })


class RenameProjectBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


@router.patch("/film/projects/{project_id}", summary="Rename a film project")
def rename_project(request: Request, body: RenameProjectBody, project_id: str):
    request_id = base.get_task_id(request)
    _require_film_db(request_id)
    title = body.title.strip()
    if not title:
        raise HttpException(task_id=request_id, status_code=422,
                            message=f"{request_id}: title must not be blank")
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _owned_project(session, project_id, user.id, request_id)
        project = FilmRepository(session).rename(project_id, title)
        return utils.get_response(200, {
            "id": project.id, "title": project.title, "status": _status(project.status),
        })


def _cancel_shot_render(session, row, request_id: str) -> bool:
    """Cancel an in-flight shot render and release its wallet hold."""
    from app.domains.wallet.service import WalletError, WalletService
    from app.models.db.render_repo import RenderJobRepository, row_to_envelope
    from app.services.render.execution import ExecutionError, RenderExecutor
    from app.services.render.wallet_gateway import WalletServiceGateway

    wallet = WalletServiceGateway(
        WalletService(session), user_id=row.user_id,
        workspace_id=row.workspace_id or None, correlation_id=request_id,
    )
    try:
        cancelled = RenderExecutor(wallet).cancel(
            row_to_envelope(row), held_micros=row.held_cost_micros
        )
    except (WalletError, ExecutionError) as exc:
        logger.warning(f"film shot render cancel failed for {row.id}: {exc}")
        return False
    RenderJobRepository(session).save_envelope(cancelled)
    return True


@router.delete("/film/projects/{project_id}", summary="Delete a film project")
def delete_project(request: Request, project_id: str):
    """Cancel + refund every in-flight shot render, then delete the project.

    Finished shot renders stay in the caller's render history; the stitched
    final video (if any) is removed from storage best-effort.
    """
    request_id = base.get_task_id(request)
    _require_film_db(request_id)
    from app.models.db.render_repo import RenderJobRepository

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        project = _owned_project(session, project_id, user.id, request_id)
        if (project.export_state or "") == "running":
            raise HttpException(task_id=request_id, status_code=409,
                                message=f"{request_id}: the film is exporting; try again when it finishes")
        renders = RenderJobRepository(session)
        cancelled = 0
        for shot in FilmRepository(session).shots(project_id):
            if not shot.render_job_id:
                continue
            row = renders.get(shot.render_job_id)
            if row is not None and str(row.state) in ("IN_QUEUE", "IN_PROGRESS"):
                if not _cancel_shot_render(session, row, request_id):
                    raise HttpException(
                        task_id=request_id, status_code=502,
                        message=f"{request_id}: could not cancel shot {shot.shot_key}; try again",
                    )
                cancelled += 1
        final_key = str(project.final_key or "")
        FilmRepository(session).delete(project_id)
    if final_key:
        try:
            from app.platform.storage.r2 import get_r2_client

            get_r2_client().delete_object(final_key)
        except Exception as exc:  # noqa: BLE001 - storage cleanup is best-effort
            logger.warning(f"film final cleanup failed for {project_id}: {exc}")
    return utils.get_response(200, {"deleted": True, "id": project_id, "cancelled_renders": cancelled})


_STALE_EXPORT_S = 30 * 60


@router.post("/film/projects/{project_id}/export", summary="Stitch every shot into the final film")
def export_project(request: Request, project_id: str):
    """Queue the final stitch (free: FFmpeg work on already-paid shot renders).

    409 when a shot is not rendered / has no usable output, or an export is
    already in flight (a stuck export older than 30 minutes may be re-queued).
    """
    from datetime import datetime, timezone

    from app.domains.film.export import FilmExportError, shot_sources

    request_id = base.get_task_id(request)
    _require_film_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        project = _owned_project(session, project_id, user.id, request_id)
        shots = FilmRepository(session).shots(project_id)
        _sync_shot_states(session, shots)
        state = project.export_state or ""
        if state in ("queued", "running"):
            updated = project.updated_at
            age = (
                (datetime.now(timezone.utc) - (updated if updated.tzinfo else updated.replace(tzinfo=timezone.utc))).total_seconds()
                if updated is not None else _STALE_EXPORT_S + 1
            )
            if age < _STALE_EXPORT_S:
                raise HttpException(task_id=request_id, status_code=409,
                                    message=f"{request_id}: an export is already in progress")
        try:
            shot_sources(session, project_id)
        except FilmExportError as exc:
            raise HttpException(task_id=request_id, status_code=409,
                                message=f"{request_id}: {exc}") from exc
        FilmRepository(session).set_export(project_id, state="queued")
    try:
        from app.workers.tasks_film import export_film_task

        export_film_task.delay(project_id)
    except Exception as exc:  # noqa: BLE001 - broker down: record + surface
        logger.error(f"film export enqueue failed for {project_id}: {exc}")
        with get_session() as session:
            FilmRepository(session).set_export(
                project_id, state="failed", error="export queue unavailable; try again",
            )
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: export queue unavailable") from exc
    return utils.get_response(200, {
        "id": project_id, "status": "exporting", "export_state": "queued",
    })
