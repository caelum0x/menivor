"""Audiobook export API (opt-in; requires the Kokoro sidecar via ``KOKORO_URL``).

* ``GET  /api/v1/audiobook/status`` — whether export is enabled + the voice list.
* ``POST /api/v1/audiobook/chapter`` — chapter text -> ``audio/mpeg`` bytes.

Order: enabled check (503) -> auth -> per-user rate limit -> validation ->
synthesis. Chapter text is processed in memory and never stored.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.audiobook import service
from app.domains.routing.base import ProviderError
from app.domains.routing.providers.kokoro import MAX_SPEED, MIN_SPEED, KokoroClient
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_HOUR = 3600
_CHAPTERS_PER_HOUR = 60


class ChapterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=service.MAX_CHAPTER_CHARS * 2)
    voice: str = Field("af_heart", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_+.\-]+$")
    speed: float = Field(1.0, ge=MIN_SPEED, le=MAX_SPEED)


def _err(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}")


def _enabled_base(request_id: str) -> str:
    try:
        return service.require_enabled()
    except service.AudiobookError as exc:
        raise _err(request_id, exc.status_code, str(exc)) from exc


def _authenticate(request: Request, request_id: str) -> str:
    require_database(request_id)
    with get_session() as session:
        return str(resolve_principal(request, session, request_id).id)


@router.get("/audiobook/status", summary="Whether audiobook export is enabled")
def audiobook_status(request: Request):
    request_id = base.get_task_id(request)
    kokoro_base = service.kokoro_url()
    if not kokoro_base:
        return utils.get_response(200, {"enabled": False, "voices": []})
    _authenticate(request, request_id)
    try:
        voices = KokoroClient(kokoro_base, timeout_s=10).list_voices()
    except ProviderError as exc:
        logger.warning(f"audiobook voice list failed, request_id: {request_id}: {exc}")
        voices = []
    return utils.get_response(200, {"enabled": True, "voices": voices})


@router.post("/audiobook/chapter", summary="Synthesize one chapter to MP3")
def audiobook_chapter(request: Request, body: ChapterBody):
    request_id = base.get_task_id(request)
    kokoro_base = _enabled_base(request_id)
    user_id = _authenticate(request, request_id)
    enforce_rate_limit(
        request, f"audiobook:chapter:{user_id}", limit=_CHAPTERS_PER_HOUR, window_s=_HOUR
    )
    try:
        chapter = service.synthesize_chapter(
            KokoroClient(kokoro_base), body.text, voice=body.voice, speed=body.speed
        )
    except service.AudiobookError as exc:
        raise _err(request_id, exc.status_code, str(exc)) from exc
    except ProviderError as exc:
        logger.error(f"audiobook synthesis failed, request_id: {request_id}: {exc}")
        status = 503 if exc.retryable else 502
        raise _err(request_id, status, "the speech service could not synthesize this chapter") from exc
    return Response(
        content=chapter.audio,
        media_type=chapter.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Audiobook-Characters": str(chapter.characters),
            "X-Audiobook-Chunks": str(chapter.chunks),
        },
    )
