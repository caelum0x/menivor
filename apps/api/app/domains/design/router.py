"""Design Studio HTTP surface (owner-scoped).

    GET    /design/templates                 size presets + built-in and saved templates
    GET    /design/brand-kits                the caller's kits with the colours/fonts each produces
    POST   /design/generate                  prompt + size + kit -> 3-4 layout options (not stored)
    GET    /design/docs                      list designs
    POST   /design/docs                      create from a chosen option / template
    GET    /design/docs/{id}                 one design with its canvas
    PATCH  /design/docs/{id}                 save title / canvas
    DELETE /design/docs/{id}                 delete
    POST   /design/docs/{id}/duplicate       copy
    POST   /design/docs/{id}/export          store browser-rendered PNG pages in R2 (owned assets)
    POST   /design/docs/{id}/ai-image        generate an image (charged to the wallet) for the canvas
    POST   /design/docs/{id}/schedule        queue exported images in the approvals feed
    POST   /design/docs/{id}/save-template   save the canvas as a reusable template
    DELETE /design/templates/{id}            remove a saved template
    POST   /design/images                    upload an image for the canvas
    GET    /design/media?key=                bytes of an owned image (keeps the export canvas untainted)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import Path, Query, Request
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.design import service
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

def _id() -> Any:
    """A fresh ``Path`` per parameter: one shared instance pins its alias to the first name used."""
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
_HOUR = 3600


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=3, max_length=2000)
    size_preset: str = Field(default="square", max_length=20)
    brand_kit_id: Optional[str] = Field(default=None, max_length=32)
    use_llm: bool = True


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    size_preset: str = Field(default="square", max_length=20)
    canvas: Optional[dict[str, Any]] = None
    template: str = Field(default="", max_length=80)
    template_id: Optional[str] = Field(default=None, max_length=32)
    brand_kit_id: Optional[str] = Field(default=None, max_length=32)
    prompt: str = Field(default="", max_length=2000)


class UpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, max_length=200)
    canvas: Optional[dict[str, Any]] = None


class ExportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: One PNG per page, as a data URL or bare base64.
    pages: list[str] = Field(..., min_length=1, max_length=10)


class AiImageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=3, max_length=2000)
    model: str = Field(default="", max_length=120)


class ScheduleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platforms: list[str] = Field(..., min_length=1, max_length=12)
    caption: str = Field(default="", max_length=2200)
    scheduled_at: Optional[datetime] = None
    # Telegram / Discord / Mastodon channel ids to post to when you have several of one kind.
    channel_ids: list[str] = Field(default_factory=list, max_length=12)


class TemplateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)


class ImageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: str = Field(..., min_length=16, max_length=14_000_000)


def _err(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}")


def _caller(request: Request, *, bucket: str = "", limit: int = 0) -> tuple[str, str]:
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
    if bucket:
        enforce_rate_limit(request, f"design:{bucket}:{user_id}", limit=limit, window_s=_HOUR)
    return request_id, user_id


def _run(request_id: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.DesignError as exc:
        raise _err(request_id, exc.status_code, str(exc)) from exc
    except HttpException:
        raise
    except Exception as exc:  # noqa: BLE001 - unexpected failure -> 500 with a stable message
        logger.error(f"design request failed, request_id: {request_id}: {exc}")
        raise _err(request_id, 500, "the design request failed") from exc


@router.get("/design/templates", summary="Design sizes and templates")
def templates(request: Request):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.list_templates, user_id))


@router.get("/design/brand-kits", summary="Brand kits with the colours and fonts designs will use")
def brand_kits(request: Request):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.brand_kits, user_id))


@router.post("/design/generate", summary="Prompt + brand kit -> layout options")
def generate(request: Request, body: GenerateBody):
    request_id, user_id = _caller(request, bucket="generate", limit=120)
    return utils.get_response(200, _run(request_id, service.generate, user_id, prompt=body.prompt,
                                        size_preset=body.size_preset, brand_kit_id=body.brand_kit_id,
                                        use_llm=body.use_llm))


@router.get("/design/docs", summary="List designs")
def list_docs(request: Request, limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.list_docs, user_id, limit=limit, offset=offset))


@router.post("/design/docs", summary="Create a design")
def create_doc(request: Request, body: CreateBody):
    request_id, user_id = _caller(request, bucket="create", limit=300)
    return utils.get_response(200, _run(request_id, service.create_doc, user_id, title=body.title,
                                        size_preset=body.size_preset, canvas=body.canvas, template=body.template,
                                        template_id=body.template_id, brand_kit_id=body.brand_kit_id,
                                        prompt=body.prompt))


@router.get("/design/docs/{doc_id}", summary="One design")
def get_doc(request: Request, doc_id: str = _id()):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.get_doc, user_id, doc_id))


@router.patch("/design/docs/{doc_id}", summary="Save a design")
def update_doc(request: Request, body: UpdateBody, doc_id: str = _id()):
    request_id, user_id = _caller(request, bucket="save", limit=2000)
    return utils.get_response(200, _run(request_id, service.update_doc, user_id, doc_id, title=body.title,
                                        canvas=body.canvas))


@router.delete("/design/docs/{doc_id}", summary="Delete a design")
def delete_doc(request: Request, doc_id: str = _id()):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.delete_doc, user_id, doc_id))


@router.post("/design/docs/{doc_id}/duplicate", summary="Duplicate a design")
def duplicate_doc(request: Request, doc_id: str = _id()):
    request_id, user_id = _caller(request, bucket="create", limit=300)
    return utils.get_response(200, _run(request_id, service.duplicate_doc, user_id, doc_id))


@router.post("/design/docs/{doc_id}/export", summary="Store rendered PNG pages")
def export(request: Request, body: ExportBody, doc_id: str = _id()):
    request_id, user_id = _caller(request, bucket="export", limit=200)
    return utils.get_response(200, _run(request_id, service.export, user_id, doc_id, body.pages))


@router.post("/design/docs/{doc_id}/ai-image", summary="Generate an AI image (charged to the wallet)")
def ai_image(request: Request, body: AiImageBody, doc_id: str = _id()):
    request_id, user_id = _caller(request, bucket="ai-image", limit=60)
    return utils.get_response(200, _run(request_id, service.ai_image, user_id, doc_id, prompt=body.prompt,
                                        model=body.model))


@router.post("/design/docs/{doc_id}/schedule", summary="Queue the exported design for approval and posting")
def schedule(request: Request, body: ScheduleBody, doc_id: str = _id()):
    request_id, user_id = _caller(request, bucket="schedule", limit=200)
    return utils.get_response(200, _run(request_id, service.schedule, user_id, doc_id, platforms=body.platforms,
                                        caption=body.caption, scheduled_at=body.scheduled_at,
                                        channel_ids=body.channel_ids))


@router.post("/design/docs/{doc_id}/save-template", summary="Save the design as a template")
def save_template(request: Request, body: TemplateBody, doc_id: str = _id()):
    request_id, user_id = _caller(request, bucket="create", limit=300)
    return utils.get_response(200, _run(request_id, service.save_template, user_id, doc_id, name=body.name))


@router.delete("/design/templates/{template_id}", summary="Remove a saved template")
def delete_template(request: Request, template_id: str = _id()):
    request_id, user_id = _caller(request)
    return utils.get_response(200, _run(request_id, service.delete_template, user_id, template_id))


@router.post("/design/images", summary="Upload an image for the canvas")
def upload_image(request: Request, body: ImageBody):
    request_id, user_id = _caller(request, bucket="upload", limit=300)
    return utils.get_response(200, _run(request_id, service.upload_image, user_id, body.data))


@router.get("/design/media", summary="Bytes of an owned image")
def media(request: Request, key: str = Query(..., min_length=8, max_length=220)):
    request_id, user_id = _caller(request)
    data, content_type = _run(request_id, service.media, user_id, key)
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
