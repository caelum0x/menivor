"""App Store / Play audit HTTP route — public, no sign-in required.

    POST /audit     score a public App Store or Google Play listing

A free lead magnet (Menivor Growth phase 1): the same paste-link box on the
landing page and the standalone `/tools/app-store-audit` /
`/tools/aso-keyword-checker` pages all call this one endpoint. Rate-limited
per caller IP since there is no account to scope it to.
"""

from __future__ import annotations

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.domains.appaudit.service import AuditError, run_audit
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()

_RATE_LIMIT = 20
_RATE_WINDOW_S = 3600


class AuditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=4, max_length=2048)


def _error(request_id: str, status_code: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status_code, message=f"{request_id}: {message}")


@router.post("/audit", summary="Free App Store / Play audit (public, no sign-in)")
def audit(request: Request, body: AuditBody):
    request_id = base.get_task_id(request)
    enforce_rate_limit(request, "appaudit:run", limit=_RATE_LIMIT, window_s=_RATE_WINDOW_S)
    try:
        data = run_audit(body.url.strip())
    except AuditError as exc:
        raise _error(request_id, exc.status_code, exc.message) from exc
    return utils.get_response(200, data)


__all__ = ["router"]
