"""Async-GPU render HTTP surface — start / status a wallet-metered render job.

Ties the whole P6 spine into one product endpoint:

    POST /render/jobs            reserve max cost → submit to backend → persist → return envelope
    GET  /render/jobs/{id}       owner-scoped status
    GET  /render/jobs            owner-scoped render history (newest first)
    POST /render/jobs/{id}/advance   poll once → settle/refund on terminal → persist
    POST /render/jobs/{id}/cancel    cancel + fully refund the hold

Auth + owner-scoping + DB reuse the shared jobs-controller helpers; the wallet is
the real ledger-backed ``WalletService`` bound via ``WalletServiceGateway``, so a
failed render refunds the full hold (success-only billing). Import-safe: the
persistence/wallet layer is behind a guarded block (clean 503 when absent).
"""

from __future__ import annotations

from fastapi import Path, Query, Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.idempotency import (
    hash_request_payload,
    read_idempotency_key,
    reserve_idempotency_key,
)
from app.models.exception import HttpException
from app.utils import utils

try:
    from app.core.api_dependencies import (
        get_session,
        require_database as _require_db,
        resolve_principal as _resolve_user,
    )
    from app.domains.render.access import resolve_spend_workspace
    from app.domains.wallet.service import WalletError, WalletService
    from app.models.db.render_repo import RenderJobRepository, row_to_envelope
    from app.services.render.outputs import output_urls
    from app.services.render.execution import ExecutionError, RenderExecutor
    from app.services.render.wallet_gateway import WalletServiceGateway

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - before the layer exists
    _IMPORT_ERROR = exc

router = new_router()


class StartRenderBody(BaseModel):
    backend: str = Field(..., description="runpod | local_comfyui | rocketride")
    spec: dict = Field(default_factory=dict, description="backend input payload (job_id auto-set)")
    max_cost_micros: int = Field(..., gt=0, description="reserved max cost (micro-USD)")
    workflow_version: str = ""
    workspace_id: str | None = None
    label: str = Field(default="", max_length=200, description="short title for history")


def _guard(request_id: str) -> None:
    if _IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: render layer unavailable: {_IMPORT_ERROR}")


_RENDER_STATES = frozenset({"IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED"})


def _envelope_view(env, row=None) -> dict:
    view = {
        "id": env.id, "backend": env.backend, "state": env.state,
        "progress": env.progress,
        "output_refs": list(env.output_refs), "cost_micros": env.cost_micros,
        "error": env.error,
    }
    # Browser-usable URLs: bare R2 keys presigned, public URLs passed through,
    # LAN/garbage refs dropped (counted so the UI can explain a missing preview).
    view.update(output_urls(env.output_refs))
    if row is not None:
        created = getattr(row, "created_at", None)
        updated = getattr(row, "updated_at", None)
        view.update({
            "created_at": created.isoformat() if created else None,
            "updated_at": updated.isoformat() if updated else None,
            "workflow_version": row.workflow_version or "",
            "held_cost_micros": int(row.held_cost_micros or 0),
            "actual_cost_micros": int(row.actual_cost_micros or 0),
            "workspace_id": row.workspace_id or None,
            "source": getattr(row, "source", "") or "render",
            "label": getattr(row, "label", "") or "",
        })
    if env.backend != "rocketride":
        view["provider_ref"] = env.provider_ref
    if env.backend == "rocketride":
        target = str(env.meta.get("rocketride_target") or env.poll_cursor or "")
        if target in {"local", "managed"}:
            view["target"] = target
        if env.state == "COMPLETED":
            view["output_receipt"] = {
                "version": "reelforge.render.receipt.v1",
                "target": target,
                "output_refs": list(env.output_refs),
                "actual_cost_micros": env.cost_micros,
            }
    return view


@router.post("/render/jobs", summary="Start a wallet-metered async-GPU render")
def start_render(request: Request, body: StartRenderBody):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    idempotency_key = read_idempotency_key(request, request_id)
    request_hash = hash_request_payload(
        {"operation": "render_start", **body.model_dump(mode="json")}
    )

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        reservation = None
        if idempotency_key is not None:
            reservation, replay = reserve_idempotency_key(
                session,
                str(user.id),
                idempotency_key,
                request_hash,
                request_id,
            )
            if replay is not None:
                return utils.get_response(200, replay)
        spec = dict(body.spec)
        spec.setdefault("job_id", request_id)
        if body.workflow_version:
            spec["workflow_version"] = body.workflow_version

        # Membership gate BEFORE any wallet hold: a caller may only spend a
        # workspace's shared pool when they belong to it (403 otherwise).
        workspace_id = resolve_spend_workspace(session, user.id, body.workspace_id, request_id)
        wallet = WalletServiceGateway(
            WalletService(session), user_id=user.id, workspace_id=workspace_id,
            correlation_id=request_id,
        )
        executor = RenderExecutor(wallet)
        try:
            env = executor.start(body.backend, spec, max_cost_micros=body.max_cost_micros)
        except WalletError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc.message}") from exc
        except ExecutionError as exc:
            raise HttpException(task_id=request_id, status_code=502,
                                message=f"{request_id}: {exc}") from exc

        label = (body.label or str(spec.get("prompt") or "")).strip()[:200]
        row = RenderJobRepository(session).create(
            env, user_id=user.id, workspace_id=workspace_id or "",
            held_cost_micros=body.max_cost_micros, source="render", label=label,
        )
        response = _envelope_view(env, row)
        if reservation is not None:
            reservation.response_data = response
            session.flush()
        return utils.get_response(200, response)


@router.get("/render/jobs/{job_id}", summary="Async-GPU render job status")
def get_render(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row = RenderJobRepository(session).get(job_id)
        if row is None or str(row.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: render job not found")
        return utils.get_response(200, _envelope_view(row_to_envelope(row), row))


@router.get("/render/jobs", summary="List the caller's render jobs (history)")
def list_renders(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    state: str | None = Query(default=None, description="filter by envelope state"),
    source: str | None = Query(default=None, description="render | film"),
):
    """Owner-scoped render history, newest first, with presigned output URLs."""
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    state_filter = (state or "").strip().upper() or None
    if state_filter is not None and state_filter not in _RENDER_STATES:
        raise HttpException(task_id=request_id, status_code=422,
                            message=f"{request_id}: unknown render state '{state}'")
    source_filter = (source or "").strip().lower() or None
    if source_filter is not None and source_filter not in {"render", "film"}:
        raise HttpException(task_id=request_id, status_code=422,
                            message=f"{request_id}: source must be 'render' or 'film'")
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = RenderJobRepository(session)
        rows = repo.list_for_user(
            user.id, limit=limit, offset=offset, state=state_filter, source=source_filter,
        )
        total = repo.count_for_user(user.id, state=state_filter, source=source_filter)
        jobs = [_envelope_view(row_to_envelope(row), row) for row in rows]
    return utils.get_response(200, {
        "jobs": jobs, "total": total, "limit": limit, "offset": offset,
        "has_more": offset + len(jobs) < total,
    })


@router.post("/render/jobs/{job_id}/advance", summary="Poll + settle a render job")
def advance_render(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = RenderJobRepository(session)
        row = repo.get(job_id)
        if row is None or str(row.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: render job not found")

        wallet = WalletServiceGateway(
            WalletService(session), user_id=user.id,
            workspace_id=row.workspace_id or None, correlation_id=request_id,
        )
        executor = RenderExecutor(wallet)
        env = row_to_envelope(row)
        try:
            advanced = executor.advance(env, held_micros=row.held_cost_micros)
        except WalletError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc.message}") from exc
        except ExecutionError as exc:
            raise HttpException(task_id=request_id, status_code=502,
                                message=f"{request_id}: {exc}") from exc
        saved = repo.save_envelope(advanced)
        return utils.get_response(200, _envelope_view(advanced, saved))


@router.post("/render/jobs/{job_id}/cancel", summary="Cancel + fully refund a render job")
def cancel_render(request: Request, job_id: str = Path(...)):
    request_id = base.get_task_id(request)
    _guard(request_id)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        repo = RenderJobRepository(session)
        row = repo.get(job_id)
        if row is None or str(row.user_id) != str(user.id):
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: render job not found")

        wallet = WalletServiceGateway(
            WalletService(session), user_id=user.id,
            workspace_id=row.workspace_id or None, correlation_id=request_id,
        )
        executor = RenderExecutor(wallet)
        try:
            cancelled = executor.cancel(
                row_to_envelope(row), held_micros=row.held_cost_micros
            )
        except WalletError as exc:
            raise HttpException(task_id=request_id, status_code=exc.status_code,
                                message=f"{request_id}: {exc.message}") from exc
        except ExecutionError as exc:
            raise HttpException(task_id=request_id, status_code=502,
                                message=f"{request_id}: {exc}") from exc
        saved = repo.save_envelope(cancelled)
        return utils.get_response(200, _envelope_view(cancelled, saved))
