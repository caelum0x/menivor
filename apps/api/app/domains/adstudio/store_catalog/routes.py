"""Store catalog import HTTP adapter.

* ``POST   /ad-studio/catalog/imports``                   read a store's public product feed
* ``GET    /ad-studio/catalog/imports``                   caller's imports
* ``GET    /ad-studio/catalog/imports/{id}``              import + products
* ``DELETE /ad-studio/catalog/imports/{id}``              delete an import (projects stay)
* ``POST   /ad-studio/catalog/imports/{id}/projects``     turn picked products into Ad Studio projects

Every route is authenticated and owner-scoped. Store feeds and product images
are fetched through the Ad Studio SSRF guard with no DB session open.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.adstudio.catalog_models import MAX_PRODUCTS_PER_IMPORT
from app.domains.adstudio.service import AdStudioError
from app.domains.adstudio.store_catalog import service
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_ID = Path(..., pattern="^[a-f0-9]{32}$")


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_url: str = Field(..., min_length=3, max_length=2048)
    provider: str = Field(default="auto", pattern="^(auto|shopify|woocommerce)$")
    limit: int = Field(default=50, ge=1, le=MAX_PRODUCTS_PER_IMPORT)


class ProjectsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[str] = Field(..., min_length=1, max_length=service.MAX_PROJECTS_PER_CALL)
    language: Optional[str] = Field(default=None, max_length=5)
    use_llm: bool = False


def _error(request_id: str, exc: AdStudioError) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc.message}")


def _user(request: Request, request_id: str) -> str:
    require_database(request_id)
    with get_session() as session:
        return str(resolve_principal(request, session, request_id).id)


@router.post("/ad-studio/catalog/imports", summary="Import products from a Shopify or WooCommerce store")
def create_import(request: Request, body: ImportBody):
    request_id = base.get_task_id(request)
    user_id = _user(request, request_id)
    enforce_rate_limit(request, f"adstudio:catalog:import:{user_id}", limit=20, window_s=3600)
    feed, error, status = service.fetch_feed(body.store_url, body.provider, body.limit)
    with get_session() as session:
        row = service.record_import(session, user_id=user_id, store_url=body.store_url.strip(),
                                    provider=body.provider, limit=body.limit, feed=feed, error=error)
        data = service.import_detail(session, user_id, row.id)
    # A failed fetch is still recorded (so it shows in history) and reported with its status.
    if error:
        raise HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {error}")
    return utils.get_response(200, data)


@router.get("/ad-studio/catalog/imports", summary="The caller's store imports")
def list_imports(request: Request):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
        items = service.list_imports(session, user_id)
    return utils.get_response(200, {"imports": items, "total": len(items)})


@router.get("/ad-studio/catalog/imports/{import_id}", summary="A store import with its products")
def get_import(request: Request, import_id: str = _ID):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        with get_session() as session:
            user_id = str(resolve_principal(request, session, request_id).id)
            data = service.import_detail(session, user_id, import_id)
    except AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, data)


@router.delete("/ad-studio/catalog/imports/{import_id}", summary="Delete a store import")
def delete_import(request: Request, import_id: str = _ID):
    request_id = base.get_task_id(request)
    require_database(request_id)
    try:
        with get_session() as session:
            user_id = str(resolve_principal(request, session, request_id).id)
            service.delete_import(session, user_id, import_id)
    except AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, {"deleted": import_id})


@router.post("/ad-studio/catalog/imports/{import_id}/projects", summary="Create Ad Studio projects from products")
def create_projects(request: Request, body: ProjectsBody, import_id: str = _ID):
    request_id = base.get_task_id(request)
    user_id = _user(request, request_id)
    enforce_rate_limit(request, f"adstudio:catalog:projects:{user_id}", limit=30, window_s=3600)
    try:
        with get_session() as session:
            provider, products = service.products_for_projects(session, user_id, import_id, body.product_ids)
        prepared = service.prepare_projects(provider, products, language=body.language, use_llm=body.use_llm)
        with get_session() as session:
            results = service.persist_projects(session, user_id, prepared)
    except AdStudioError as exc:
        raise _error(request_id, exc) from exc
    return utils.get_response(200, {"results": results,
                                    "created": sum(1 for r in results if r["project_id"] and not r["error"])})


__all__ = ["router"]
