"""Brand-kit import HTTP routes.

* ``POST /me/brand-kits/import`` — read a brand from a website URL
  (``source="website"``) or a Rally brand-kit share link/token
  (``source="rally"``). With ``save=true`` (default) the brand is written into
  the caller's brand kit (the existing ``UserPreset`` row the reel wizard
  applies); with ``save=false`` it is only previewed.

Authenticated, owner-scoped and rate limited. All outbound fetches go through
the Ad Studio SSRF guard; Rally is only ever contacted at ``RALLY_WEB_URL``.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.brand import service
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()


class BrandImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["website", "rally"]
    #: Website URL (``source=website``) or Rally share link/token (``source=rally``).
    value: str = Field(..., min_length=1, max_length=2048)
    save: bool = True
    #: Update this existing kit instead of the one previously imported from the same source.
    preset_id: Optional[str] = Field(default=None, max_length=32)
    #: Kit name; defaults to "<brand> brand kit" on create and is kept on update.
    name: Optional[str] = Field(default=None, max_length=200)


def _error(request_id: str, status_code: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status_code, message=f"{request_id}: {message}")


@router.post("/me/brand-kits/import", summary="Import a brand kit from a website or a Rally share")
def import_brand_kit(request: Request, body: BrandImportBody):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
    enforce_rate_limit(request, f"brand:import:{user_id}", limit=30, window_s=3600)

    try:
        source_key, brand = service.extract(body.source, body.value.strip())
    except service.BrandImportError as exc:
        raise _error(request_id, exc.status_code, exc.message) from exc

    preset = None
    if body.save:
        try:
            with get_session() as session:
                saved = service.save_to_kit(
                    session,
                    user_id=user_id,
                    brand=brand,
                    source=body.source,
                    source_key=source_key,
                    preset_id=(body.preset_id or "").strip() or None,
                    name=body.name,
                )
                preset = service.preset_view(saved)
        except service.BrandImportError as exc:
            raise _error(request_id, exc.status_code, exc.message) from exc
        except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
            logger.error(f"brand kit import save failed, request_id: {request_id}: {exc}")
            raise _error(request_id, 502, "failed to save the brand kit") from exc

    return utils.get_response(
        200,
        {"source": body.source, "source_key": source_key, "brand": brand, "preset": preset},
    )
