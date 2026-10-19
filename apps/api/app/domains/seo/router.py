"""SEO HTTP adapter (``/api/v1/seo/...``): connect OpenSEO, site audit, keyword
research, rank tracking. Every route is signed-in; workspace scope reuses
``app.domains.integrations.scope`` exactly like Settings > Integrations does.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.integrations.connectors.base import RequestsTransport
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.scope import Scope, resolve
from app.domains.seo import service
from app.domains.seo.errors import SeoError
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

#: ``resolve()`` (workspace/brand lookup) and ``Scope.require_manage()`` are reused
#: as-is from Settings > Integrations and raise its error type; SEO's own service
#: code raises :class:`SeoError`. Both carry the same ``status_code``/``message``
#: shape, so one handler maps either to the HTTP response.
_ScopeError = (SeoError, IntegrationError)

router = new_router()

_WS = Query(default="", max_length=32, pattern=r"^[a-f0-9]*$")
_TRANSPORT: Any = RequestsTransport()


def set_transport(transport: Any) -> None:
    global _TRANSPORT
    _TRANSPORT = transport


def _id():
    return Path(..., pattern="^[a-f0-9]{32}$")


def _fail(request_id: str, exc: SeoError | IntegrationError) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc.message}")


def _run(request: Request, workspace_id: str, fn: Callable[[Any, Scope], Any], *, bucket: str = "",
         limit: int = 0, window_s: int = 3600):
    request_id = base.get_task_id(request)
    require_database(request_id)
    error: SeoError | IntegrationError | None = None
    result: Any = None
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
        if bucket:
            enforce_rate_limit(request, f"seo:{bucket}:{user_id}", limit=limit, window_s=window_s)
        try:
            scope = resolve(session, user_id, workspace_id=workspace_id or None)
            result = fn(session, scope)
        except _ScopeError as exc:
            error = exc
    if error is not None:
        raise _fail(request_id, error)
    return utils.get_response(200, result)


class ConnectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(..., min_length=8, max_length=300)
    domain: str = Field(default="", max_length=300)


class ResearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seeds: list[str] = Field(..., min_length=1, max_length=service.MAX_RESEARCH_SEEDS)


class RankKeywordsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: list[str] = Field(..., min_length=1, max_length=service.MAX_TRACKED_KEYWORDS)
    country: str = Field(default="us", min_length=2, max_length=8, pattern=r"^[a-zA-Z]{2,8}$")


@router.get("/seo/overview", summary="SEO: OpenSEO connection, latest audit, tracked keywords")
def overview(request: Request, workspace_id: str = _WS):
    return _run(request, workspace_id, lambda s, sc: service.overview(s, sc))


@router.post("/seo/connect", summary="Connect your own OpenSEO account (API key)")
def connect(request: Request, body: ConnectBody, workspace_id: str = _WS):
    return _run(request, workspace_id,
               lambda s, sc: service.connect(s, sc, body.api_key, domain=body.domain, transport=_TRANSPORT),
               bucket="connect", limit=20)


@router.delete("/seo", summary="Disconnect OpenSEO")
def disconnect(request: Request, workspace_id: str = _WS):
    return _run(request, workspace_id, lambda s, sc: {"disconnected": service.disconnect(s, sc)})


@router.post("/seo/audit/run", summary="Run a site audit now (spends your OpenSEO credits)")
def run_audit(request: Request, workspace_id: str = _WS):
    return _run(request, workspace_id, lambda s, sc: service.run_audit(s, sc, transport=_TRANSPORT),
               bucket="audit", limit=10)


@router.get("/seo/audit/{audit_run_id}", summary="Read audit status/issues (free)")
def audit_status(request: Request, audit_run_id: str = _id(), workspace_id: str = _WS):
    return _run(request, workspace_id, lambda s, sc: service.refresh_audit(s, sc, audit_run_id, transport=_TRANSPORT))


@router.post("/seo/keywords/research", summary="Research keywords for your niche (spends OpenSEO credits)")
def research(request: Request, body: ResearchBody, workspace_id: str = _WS):
    return _run(request, workspace_id,
               lambda s, sc: {"keywords": service.research_keywords(s, sc, body.seeds, transport=_TRANSPORT)},
               bucket="research", limit=10)


@router.get("/seo/keywords/research", summary="Cached keyword research (free)")
def research_list(request: Request, workspace_id: str = _WS):
    return _run(request, workspace_id, lambda s, sc: {"keywords": service.list_research(s, sc)})


@router.post("/seo/rank-tracker/keywords", summary="Track up to 10 keywords' App Store/SERP rank")
def add_rank_keywords(request: Request, body: RankKeywordsBody, workspace_id: str = _WS):
    return _run(request, workspace_id,
               lambda s, sc: {"keywords": service.add_rank_keywords(s, sc, body.keywords, country=body.country,
                                                                    transport=_TRANSPORT)},
               bucket="rank_add", limit=20)


@router.delete("/seo/rank-tracker/keywords/{keyword_id}", summary="Stop tracking one keyword")
def remove_rank_keyword(request: Request, keyword_id: str = _id(), workspace_id: str = _WS):
    return _run(request, workspace_id, lambda s, sc: {"removed": service.remove_rank_keyword(s, sc, keyword_id)})


@router.post("/seo/rank-tracker/refresh", summary="Re-check every tracked keyword's rank (spends OpenSEO credits)")
def refresh_rank_tracker(request: Request, workspace_id: str = _WS):
    return _run(request, workspace_id, lambda s, sc: {"keywords": service.refresh_rank_tracker(s, sc,
                                                                                               transport=_TRANSPORT)},
               bucket="rank_refresh", limit=10)


__all__ = ["router", "set_transport"]
