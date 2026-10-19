"""Reddit thread → story reel HTTP domain.

* ``POST /stories/reddit`` — turn a Reddit thread URL into a submittable reel draft.

Mirrors ``ingest/router.py``: a guarded top-level DB/auth import degrades to 503
when the persistence layer is unavailable; auth is enforced via ``resolve_principal``
but the flow is stateless (no job is created here — the client submits the returned
draft to the reel-create path).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

try:
    from dataclasses import asdict

    from app.core.auth import resolve_principal
    from app.domains.stories.service import RedditStoryService, StoryIngestError
    from app.domains.templates.validation import TemplateError
    from app.models.db.base import get_session

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    resolve_principal = None  # type: ignore[assignment]
    RedditStoryService = None  # type: ignore[assignment]
    StoryIngestError = Exception  # type: ignore[assignment,misc]
    TemplateError = Exception  # type: ignore[assignment,misc]
    get_session = None  # type: ignore[assignment]
    asdict = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


router = new_router()


class RedditIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., description="Reddit thread URL to turn into a story reel")
    subject: Optional[str] = Field(default=None, description="Override the reel subject/title")
    voice_id: Optional[str] = Field(default=None, description="ElevenLabs narration voice id")


def _resolve_user(request: Request, session: Any, request_id: str):
    return resolve_principal(request, session, request_id)


@router.post("/stories/reddit", summary="Turn a Reddit thread into a story reel draft")
def reddit_story(request: Request, body: RedditIngestRequest):
    """Fetch a Reddit thread, narrate it, and return a template-bound reel draft.

    Authenticated (the reel it feeds is caller-owned) but stateless — no job is
    created here; the client submits the returned draft to the reel-create path.
    """
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None or get_session is None or RedditStoryService is None:
        logger.error(f"stories unavailable ({request_id}): {_DB_IMPORT_ERROR}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: persistence layer is not available",
        )
    with get_session() as session:
        _resolve_user(request, session, request_id)
    try:
        result = RedditStoryService().thread_to_reel(
            body.url, subject=body.subject, voice_id=body.voice_id
        )
    except StoryIngestError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc.message}",
        ) from exc
    except TemplateError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=422,
            message=f"{request_id}: {exc}",
        ) from exc

    data = {
        "url": result.url,
        "thread": asdict(result.thread),
        "reel_draft": result.reel_draft,
    }
    return utils.get_response(200, data)
