"""HTTP surface for the keyword tracker (Menivor Growth phase 2, owner-scoped).

    GET    /keyword-tracker?workspace_id=    the caller's tracked keywords + plan limit
    POST   /keyword-tracker                 track a new (app, term, country)
    DELETE /keyword-tracker/{id}            stop tracking one keyword
    POST   /keyword-tracker/{id}/refresh    check its rank right now (manual, rate-limited)

App Store only (see app.domains.keyword_tracker.models): the Google Play
Developer API has no public keyword-rank endpoint. A daily Celery beat tick
(app.domains.keyword_tracker.tasks) keeps every tracked keyword current
without the caller doing anything.

``GET /keyword-tracker``'s optional ``workspace_id`` resolves the same
personal-vs-workspace scope every Settings > Integrations-backed feature
uses (app.domains.integrations.scope): when that scope has a connected Apple
Search Ads account, each keyword also gets Apple's own Search Popularity
index; without one, ``popularity`` stays whatever was last cached (``None``
if never connected).
"""

from __future__ import annotations

from typing import Any

from fastapi import Path, Query, Request
from pydantic import BaseModel, Field

from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.domains._http import Call
from app.domains.integrations.connectors.base import RequestsTransport
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.scope import resolve as resolve_scope
from app.domains.keyword_tracker import models as _models  # noqa: F401  (registers tables)
from app.domains.keyword_tracker import service
from app.utils import utils

router = new_router()
_ERRORS = (service.KeywordTrackerError, IntegrationError)

#: Tests swap in a fake search function (mirrors competitors/router.py's
#: module-level ``TRANSPORT``); production leaves this ``None`` so the real
#: public iTunes Search API (app.domains.capture.store.fetch_app_store_search)
#: is used, via app.domains.appaudit.visibility's default.
SEARCH = None

#: Tests swap in a fake HTTP transport for the Apple Search Ads popularity
#: lookup (mirrors integrations/router.py's module-level ``_TRANSPORT``);
#: production leaves this unset so the real `requests`-backed transport is used.
TRANSPORT: Any = RequestsTransport()

_WORKSPACE_ID = Query(default="", max_length=32, pattern=r"^[a-f0-9]*$")


def _id():
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


def _call(request: Request, key: str = "", limit: int = 600) -> Call:
    return Call(request, _ERRORS, f"keyword_tracker:{key}" if key else "keyword_tracker", get_session, limit=limit)


class AddKeywordBody(BaseModel):
    app_id: str = Field(..., min_length=1, max_length=32)
    term: str = Field(..., min_length=1, max_length=100)
    app_name: str = Field("", max_length=300)
    country: str = Field("us", min_length=2, max_length=2)


@router.get("/keyword-tracker", summary="The caller's tracked keywords + plan limit")
def list_keywords(request: Request, workspace_id: str = _WORKSPACE_ID):
    """``workspace_id`` is optional (same personal-vs-workspace scope every
    other Settings > Integrations-backed feature already takes): when that
    scope has a connected Apple Search Ads account, every keyword is
    decorated with Apple's own Search Popularity index."""
    with _call(request, limit=60) as (session, user_id):
        scope = resolve_scope(session, user_id, workspace_id=workspace_id or None)
        return utils.get_response(200, service.list_keywords(session, user_id, scope=scope, transport=TRANSPORT))


@router.post("/keyword-tracker", summary="Track a new (app, keyword, country) triple")
def add_keyword(request: Request, body: AddKeywordBody):
    with _call(request, "write", limit=30) as (session, user_id):
        return utils.get_response(200, service.add_keyword(
            session, user_id, app_id=body.app_id, term=body.term, app_name=body.app_name, country=body.country,
            search=SEARCH,
        ))


@router.delete("/keyword-tracker/{keyword_id}", summary="Stop tracking a keyword")
def remove_keyword(request: Request, keyword_id: str = _id()):
    with _call(request, "write", limit=30) as (session, user_id):
        removed = service.remove_keyword(session, user_id, keyword_id)
        return utils.get_response(200, {"removed": removed})


@router.post("/keyword-tracker/{keyword_id}/refresh", summary="Check one keyword's rank right now")
def refresh_keyword(request: Request, keyword_id: str = _id()):
    with _call(request, "refresh", limit=30) as (session, user_id):
        return utils.get_response(200, service.refresh_one(session, user_id, keyword_id, search=SEARCH))


__all__ = ["router"]
