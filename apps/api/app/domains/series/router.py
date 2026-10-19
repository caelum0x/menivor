"""Clipfarm HTTP domain — read + trigger the unattended channel runner.

The series runner (``domains.series.runner``) is otherwise worker-only (driven
by the Celery beat in ``workers.tasks_series``). This additive router exposes a
thin, authenticated HTTP surface over the SAME pure runner + session-injected
repositories so first-party clients (the mobile Clipfarm console) can read run
history / pacing and manually trigger a render or publish-pacing pass — without
duplicating any orchestration logic.

Routes served under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`.
Every response uses the MPT envelope; every error is raised as
:class:`HttpException`. The persistence + runner layer is imported behind a
guarded block so importing this module never crashes startup (clean ``503`` when
the DB/runner layer is unavailable).

Endpoints:
* ``POST   /series/channels``                     create a named channel
* ``GET    /series/channels``                     the caller's channels
* ``GET    /series/channels/{channel_id}``        one channel
* ``PATCH  /series/channels/{channel_id}``        update config / sources / autorun
* ``DELETE /series/channels/{channel_id}``        archive a channel
* ``GET  /series/channels/{channel_id}/runs``     run bookkeeping, newest first
* ``GET  /series/runs/{run_id}``                  one run's persisted view
* ``GET  /series/channels/{channel_id}/pending``  pending-publish clips + pacing
* ``POST /series/channels/{channel_id}/run``      one render pass (Idempotency-Key)
* ``POST /series/channels/{channel_id}/schedule`` one publish-pacing pass (keyed)

Both POST paths mirror the runner exactly (``run_channel`` / ``schedule_due``)
and return ``RunResult.summary()`` / ``ScheduleResult.summary()``. They are
gated on an ``Idempotency-Key`` header: the render pass is already idempotent via
``fanout.spec_hash`` dedupe and the schedule pass via the ``pending`` filter, so
requiring the key keeps ambiguous transport retries from double-triggering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.idempotency import read_idempotency_key
from app.models.exception import HttpException
from app.utils import utils

from . import channels as channel_store
from .schemas import (
    ChannelCreateRequest,
    ChannelUpdateRequest,
    RunChannelRequest,
    ScheduleChannelRequest,
    clip_view,
    run_view,
)

# --------------------------------------------------------------------------- #
# Guarded persistence + runner import.
# --------------------------------------------------------------------------- #
try:
    from app.core.auth import resolve_principal
    from app.domains.series import runner as series_runner
    from app.domains.series.repository import (
        ChannelClipRepository,
        ChannelRunRepository,
    )
    from app.models.db.base import get_session
    from app.models.db.repositories import JobRepository
    from app.services import scheduler as scheduler_service
    from app.workers.pipeline import start_pipeline

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    series_runner = None  # type: ignore[assignment]
    ChannelClipRepository = None  # type: ignore[assignment]
    ChannelRunRepository = None  # type: ignore[assignment]
    get_session = None  # type: ignore[assignment]
    JobRepository = None  # type: ignore[assignment]
    scheduler_service = None  # type: ignore[assignment]
    start_pipeline = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


def _require_db(request_id: str) -> None:
    if _DB_IMPORT_ERROR is not None or get_session is None or series_runner is None:
        logger.error(
            f"series persistence unavailable, request_id: {request_id}, "
            f"error: {_DB_IMPORT_ERROR}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


def _require_channel_id(channel_id: str, request_id: str) -> str:
    normalized = (channel_id or "").strip()
    if not normalized:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: a non-empty channel_id is required",
        )
    return normalized


def _make_deps(session: Any) -> Any:
    """Assemble the real :class:`RunnerDeps` for a live session.

    Mirrors ``workers.tasks_series._make_deps`` exactly so the HTTP trigger and
    the beat tick drive the runner through the identical seams (same job repo,
    clip repo, render enqueue and publish scheduler).
    """
    return series_runner.RunnerDeps(
        job_repo=JobRepository(session),
        clip_repo=ChannelClipRepository(session),
        start_pipeline=start_pipeline,
        schedule_publish=scheduler_service.schedule_publish,
        session=session,
    )


def _build_config(channel_id: str, user_id: str, body: RunChannelRequest) -> Any:
    """Build a :class:`ChannelRunConfig` from a validated request body.

    Only supplies overrides the caller set; blank collections fall back to the
    config defaults (``("",)`` hooks/accounts, ``("9:16",)`` aspects, the
    Minecraft template slug, 130 max words) so a minimal request still runs.
    """
    kwargs: dict[str, Any] = {"channel_id": channel_id, "user_id": user_id}
    if body.hooks:
        kwargs["hooks"] = tuple(body.hooks)
    if body.aspects:
        kwargs["aspects"] = tuple(body.aspects)
    if body.accounts:
        kwargs["accounts"] = tuple(body.accounts)
    if body.platforms:
        kwargs["platforms"] = tuple(body.platforms)
    if body.subject:
        kwargs["subject"] = body.subject
    if body.voice_id is not None:
        kwargs["voice_id"] = body.voice_id
    if body.template_slug:
        kwargs["template_slug"] = body.template_slug
    if body.max_words is not None:
        kwargs["max_words"] = int(body.max_words)
    if body.max_per_account is not None:
        kwargs["max_per_account"] = int(body.max_per_account)
    return series_runner.ChannelRunConfig(**kwargs)


def _channel_error(exc: Exception, request_id: str) -> HttpException:
    return HttpException(
        task_id=request_id,
        status_code=int(getattr(exc, "status_code", 400) or 400),
        message=f"{request_id}: {getattr(exc, 'message', str(exc))}",
    )


def _assert_access(session: Any, channel_id: str, user_id: str, request_id: str) -> None:
    try:
        channel_store.assert_channel_access(session, channel_id, user_id)
    except channel_store.ChannelError as exc:
        raise _channel_error(exc, request_id) from exc


_CONFIG_FIELDS = (
    "hooks", "aspects", "accounts", "platforms", "subject", "voice_id",
    "template_slug", "max_words", "max_per_account",
)


def _stored_body(row: Any, body: RunChannelRequest) -> RunChannelRequest:
    """Fill an empty trigger body from the channel's stored config + sources."""
    params = dict(getattr(row, "params", None) or {})
    stored = dict(params.get("config") or {})
    merged: dict[str, Any] = {}
    for field in _CONFIG_FIELDS:
        value = getattr(body, field)
        merged[field] = value if value not in (None, "", []) else stored.get(field)
    merged = {k: v for k, v in merged.items() if v is not None}
    source_items = (
        [item.model_dump() for item in body.source_items]
        if body.source_items
        else list(params.get("source_items") or [])
    )
    return RunChannelRequest(source_items=source_items, **merged)


# --------------------------------------------------------------------------- #
# Channel definitions (create / list / get / update / archive)
# --------------------------------------------------------------------------- #
@router.post("/series/channels", summary="Create a channel")
def create_channel(request: Request, body: ChannelCreateRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    payload = body.model_dump()
    config = {k: payload.get(k) for k in _CONFIG_FIELDS}
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = channel_store.create_channel(
                session,
                user_id=user.id,
                name=body.name,
                config=config,
                source_items=payload.get("source_items") or [],
                autorun=body.autorun,
            )
        except channel_store.ChannelError as exc:
            raise _channel_error(exc, request_id) from exc
        data = channel_store.channel_view(row)
    return utils.get_response(200, data)


@router.get("/series/channels", summary="List the caller's channels")
def list_channels(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = channel_store.list_owned(session, user.id)
        data = [channel_store.channel_view(row) for row in rows]
    return utils.get_response(200, {"channels": data})


@router.get("/series/channels/{channel_id}", summary="Get one channel")
def get_channel(request: Request, channel_id: str):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = channel_store.get_owned(session, channel_id, user.id)
        except channel_store.ChannelError as exc:
            raise _channel_error(exc, request_id) from exc
        data = channel_store.channel_view(row)
    return utils.get_response(200, data)


@router.patch("/series/channels/{channel_id}", summary="Update a channel")
def update_channel(request: Request, channel_id: str, body: ChannelUpdateRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    payload = body.model_dump(exclude_unset=True)
    config = {k: payload[k] for k in _CONFIG_FIELDS if k in payload}
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = channel_store.get_owned(session, channel_id, user.id)
            row = channel_store.update_channel(
                session,
                row,
                name=payload.get("name"),
                config=config or None,
                source_items=payload.get("source_items"),
                autorun=payload.get("autorun"),
            )
        except channel_store.ChannelError as exc:
            raise _channel_error(exc, request_id) from exc
        data = channel_store.channel_view(row)
    return utils.get_response(200, data)


@router.delete("/series/channels/{channel_id}", summary="Archive a channel")
def archive_channel(request: Request, channel_id: str):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            row = channel_store.get_owned(session, channel_id, user.id)
        except channel_store.ChannelError as exc:
            raise _channel_error(exc, request_id) from exc
        channel_store.archive_channel(session, row)
    return utils.get_response(200, {"archived": True, "channel_id": channel_id})


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get(
    "/series/channels/{channel_id}/runs", summary="List a channel's runner passes"
)
def list_channel_runs(request: Request, channel_id: str, limit: int = 50):
    """Return the channel's persisted runner passes, newest first."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    normalized = _require_channel_id(channel_id, request_id)
    bounded = max(1, min(200, int(limit) if limit else 50))
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _assert_access(session, normalized, user.id, request_id)
        rows = ChannelRunRepository(session).list_for_channel(
            normalized, limit=bounded + 1
        )
        runs = [
            run_view(row) for row in rows if not channel_store.is_definition(row)
        ][:bounded]
    return utils.get_response(200, {"runs": runs})


@router.get("/series/runs/{run_id}", summary="Get one runner pass")
def get_channel_run(request: Request, run_id: str):
    """Return one persisted runner pass by id (404 when unknown)."""
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row = ChannelRunRepository(session).get((run_id or "").strip())
        if (
            row is None
            or str(row.user_id) != str(user.id)
            or channel_store.is_definition(row)
        ):
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: run '{run_id}' was not found",
            )
        data = run_view(row)
    return utils.get_response(200, data)


@router.get(
    "/series/channels/{channel_id}/pending",
    summary="Pending-publish clips + per-account render pacing",
)
def channel_pending(request: Request, channel_id: str):
    """Return the channel's COMPLETE-but-unpublished clips + today's render counts.

    ``pending`` is the exact set the publish-scheduler would pace onto the
    calendar (``ChannelClipRepository.list_pending_publish``); ``rendered_today``
    is the per-account count of non-failed clips rendered today (UTC) —
    the per-day budget the render pace-cap subtracts against.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    normalized = _require_channel_id(channel_id, request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _assert_access(session, normalized, user.id, request_id)
        repo = ChannelClipRepository(session)
        pending = [clip_view(clip) for clip in repo.list_pending_publish(normalized)]
        rendered_today = repo.rendered_today_counts(normalized)
    return utils.get_response(
        200, {"pending": pending, "rendered_today": rendered_today}
    )


# --------------------------------------------------------------------------- #
# Triggers (Idempotency-Key gated)
# --------------------------------------------------------------------------- #
@router.post(
    "/series/channels/{channel_id}/run", summary="Trigger one render pass"
)
def trigger_run(request: Request, channel_id: str, body: RunChannelRequest):
    """Render one unattended pass over the supplied inline source list.

    Requires an ``Idempotency-Key`` header. Persists a ``channel_runs`` row
    capturing the config + the ``RunResult.summary()`` so the run shows up in the
    channel's history, and returns that summary (planned / skipped_duplicates /
    paced_out / rendered / enqueue_failures) plus the runner's ``run_id``.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    normalized = _require_channel_id(channel_id, request_id)
    idempotency_key = read_idempotency_key(request, request_id)
    if not idempotency_key:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: Idempotency-Key header is required",
        )
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _assert_access(session, normalized, user.id, request_id)
        definition = channel_store.get_definition(session, normalized)
        if definition is not None:
            body = _stored_body(definition, body)
        if not body.source_items:
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"{request_id}: add source items to the channel before running it",
            )
        config = _build_config(normalized, user.id, body)
        source_items = series_runner.items_from_list(
            [item.model_dump() for item in body.source_items]
        )
        deps = _make_deps(session)
        result = series_runner.run_channel(
            config, source_items=source_items, deps=deps
        )
        summary = result.summary()
        # Persist run bookkeeping so GET /runs reflects real triggered history.
        ChannelRunRepository(session).create(
            user_id=user.id,
            channel_id=normalized,
            params={
                "config": config.as_dict(),
                "summary": summary,
                "run_id": result.run_id,
                "idempotency_key": idempotency_key,
            },
        )
    return utils.get_response(200, {"run_id": result.run_id, "summary": summary})


@router.post(
    "/series/channels/{channel_id}/schedule",
    summary="Trigger one publish-pacing pass",
)
def trigger_schedule(
    request: Request, channel_id: str, body: ScheduleChannelRequest
):
    """Pace every COMPLETE-but-unpublished clip onto the publish calendar.

    Requires an ``Idempotency-Key`` header. Mirrors ``runner.schedule_due`` and
    returns ``ScheduleResult.summary()`` (considered / scheduled). ``platforms``
    seeds cross-post targets for clips whose stored platform is blank.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    normalized = _require_channel_id(channel_id, request_id)
    idempotency_key = read_idempotency_key(request, request_id)
    if not idempotency_key:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: Idempotency-Key header is required",
        )
    now = datetime.now(timezone.utc)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        _assert_access(session, normalized, user.id, request_id)
        run_body = RunChannelRequest(
            platforms=body.platforms, accounts=body.accounts
        )
        definition = channel_store.get_definition(session, normalized)
        if definition is not None:
            run_body = _stored_body(definition, run_body)
        config = _build_config(normalized, user.id, run_body)
        deps = _make_deps(session)
        result = series_runner.schedule_due(config, now=now, deps=deps)
        summary = result.summary()
    return utils.get_response(200, {"summary": summary})


__all__ = ["router"]
