"""Integrations HTTP adapter (``/api/v1/integrations/...``).

Signed-in routes take optional ``workspace_id`` / ``brand_space_id`` query params;
the scope (membership, role, Brand space) is resolved on every call. The three
``/integrations/slack/{commands,events,interactions}`` routes are called by Slack
and authenticated only by the Slack request signature; they answer at once and
do the work in a background task (Slack's 3-second limit).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import BackgroundTasks, Body, Path, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session, require_database, resolve_principal
from app.domains.integrations import actions, agent, onboarding, product_sources, service, slack
from app.domains.integrations.connectors import AD_PROVIDERS
from app.domains.integrations.connectors.base import RequestsTransport
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import IntegrationOAuthState
from app.domains.integrations.scope import Scope, resolve
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

router = new_router()



def _id():
    """A fresh Path() per route: FastAPI binds a Path object to the first parameter name it serves."""
    return Path(..., pattern="^[a-f0-9]{32}$")


_PROVIDER = Path(..., pattern="^(" + "|".join(AD_PROVIDERS) + ")$")
_SOURCE = Path(..., pattern="^(shopify|medusa)$")
_WS = Query(default="", max_length=32, pattern=r"^[a-f0-9]*$")
_BRAND = Query(default="", max_length=32, pattern=r"^[a-f0-9]*$")
_TRANSPORT: Any = RequestsTransport()


def set_transport(transport: Any) -> None:
    global _TRANSPORT
    _TRANSPORT = transport


def _fail(request_id: str, exc: IntegrationError) -> HttpException:
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc.message}")


def _run(request: Request, workspace_id: str, brand_space_id: str, fn: Callable[[Any, Scope], Any], *,
         bucket: str = "", limit: int = 0, window_s: int = 3600):
    """Resolve the caller + scope, run ``fn`` in one transaction, map errors after commit."""
    request_id = base.get_task_id(request)
    require_database(request_id)
    error: IntegrationError | None = None
    result: Any = None
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
        if bucket:
            enforce_rate_limit(request, f"integrations:{bucket}:{user_id}", limit=limit, window_s=window_s)
        try:
            scope = resolve(session, user_id, workspace_id=workspace_id or None, brand_space_id=brand_space_id or None)
            result = fn(session, scope)
        except IntegrationError as exc:
            error = exc  # committed work (a consumed state, a reauth mark) stays committed
    if error is not None:
        raise _fail(request_id, error)
    return utils.get_response(200, result)


def _brand_spaces(session: Any, scope: Scope) -> list[dict]:
    from sqlalchemy import select

    from app.models.db.models import UserPreset

    stmt = select(UserPreset.id, UserPreset.name)
    stmt = stmt.where(UserPreset.workspace_id == scope.workspace_id) if scope.workspace_id else stmt.where(
        UserPreset.user_id == scope.user_id, UserPreset.workspace_id.is_(None))
    return [{"id": i, "name": n} for i, n in session.execute(stmt.order_by(UserPreset.created_at)).all()]


# --------------------------------------------------------------------------- overview
@router.get("/integrations", summary="Integrations: ad accounts, Ads agent, Slack, social accounts, products")
def overview(request: Request, workspace_id: str = _WS, brand_space_id: str = _BRAND):
    def fn(session, scope):
        return {
            "ads": service.overview(session, scope),
            "agent": {"name": agent.AGENT_NAME, "plan_allows": agent.plan_allows(session, scope),
                      "plan_message": agent.PLAN_MESSAGE, "onboarding": onboarding.checklist(session, scope)},
            "slack": slack.status(session, scope),
            "social": service.social_overview(session, scope),
            "products": {"sources": product_sources.list_sources(session, scope)},
            "brand_spaces": _brand_spaces(session, scope),
        }
    return _run(request, workspace_id, brand_space_id, fn)


# --------------------------------------------------------------------------- ad accounts
class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(..., min_length=8, max_length=4096)


class CallbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=1, max_length=4096)
    state: str = Field(..., min_length=10, max_length=200)


class BrandSpacesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_space_ids: list[str] = Field(default_factory=list, max_length=50)


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ad_account_id: Optional[str] = Field(default=None, pattern="^[a-f0-9]{32}$")
    days: int = Field(default=7, ge=1, le=90)


@router.post("/integrations/ads/{provider}/connect", summary="Start connecting an ad platform (sign-in)")
def connect(request: Request, provider: str = _PROVIDER, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: service.start_connect(s, sc, provider),
                bucket="connect", limit=30)


@router.post("/integrations/ads/{provider}/key", summary="Connect an ad platform with an API key")
def connect_key(request: Request, body: KeyBody, provider: str = _PROVIDER, workspace_id: str = _WS):
    return _run(request, workspace_id, "",
                lambda s, sc: service.connect_api_key(s, sc, provider, body.api_key, transport=_TRANSPORT),
                bucket="connect", limit=30)


@router.post("/integrations/callback", summary="Finish a sign-in (ad platform or Slack)")
def callback(request: Request, body: CallbackBody):
    def fn(session, scope):
        import hashlib

        row = session.get(IntegrationOAuthState, hashlib.sha256(body.state.encode()).hexdigest())
        if row is not None and row.provider == slack.PROVIDER:
            return slack.finish_install(session, scope.user_id, code=body.code, state=body.state,
                                        transport=_TRANSPORT)
        return service.finish_connect(session, scope.user_id, code=body.code, state=body.state, transport=_TRANSPORT)
    return _run(request, "", "", fn, bucket="callback", limit=30)


@router.delete("/integrations/ads/{provider}", summary="Disconnect an ad platform")
def disconnect(request: Request, provider: str = _PROVIDER, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: {"disconnected": service.disconnect(s, sc, provider)})


@router.put("/integrations/ad-accounts/{ad_account_id}/brand-spaces", summary="Choose which Brand spaces see an account")
def brand_spaces(request: Request, body: BrandSpacesBody, ad_account_id: str = _id(), workspace_id: str = _WS):
    return _run(request, workspace_id, "",
                lambda s, sc: service.assign_brand_spaces(s, sc, ad_account_id, body.brand_space_ids))


@router.post("/integrations/ads/refresh", summary="Pull reporting from the connected ad accounts (read only)")
def refresh(request: Request, body: RefreshBody = Body(default_factory=RefreshBody), workspace_id: str = _WS,
            brand_space_id: str = _BRAND):
    return _run(request, workspace_id, brand_space_id,
                lambda s, sc: service.pull_metrics(s, sc, transport=_TRANSPORT, ad_account_id=body.ad_account_id,
                                                   days=body.days), bucket="refresh", limit=30)


class DraftCampaignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=200)
    daily_budget_minor: int = Field(..., gt=0, le=1_000_000_00)
    countries: list[str] = Field(default_factory=list, max_length=25)
    adam_id: str = Field(default="", max_length=32, pattern=r"^[0-9]*$")


@router.post("/integrations/ad-accounts/{ad_account_id}/campaigns/draft",
            summary="Create a new campaign on the platform, left PAUSED")
def draft_campaign(request: Request, body: DraftCampaignBody, ad_account_id: str = _id(), workspace_id: str = _WS):
    return _run(request, workspace_id, "",
                lambda s, sc: service.draft_campaign(s, sc, ad_account_id, name=body.name,
                                                      daily_budget_minor=body.daily_budget_minor,
                                                      countries=body.countries, adam_id=body.adam_id,
                                                      transport=_TRANSPORT),
                bucket="draft_campaign", limit=20)


@router.get("/integrations/ads/report", summary="Spend, CTR, CPA and ROAS per account and creative")
def report(request: Request, workspace_id: str = _WS, brand_space_id: str = _BRAND,
           ad_account_id: str = Query(default="", max_length=32, pattern=r"^[a-f0-9]*$"),
           days: int = Query(default=7, ge=1, le=90)):
    return _run(request, workspace_id, brand_space_id,
                lambda s, sc: agent.pull_report(s, sc, ad_account_id=ad_account_id or None, days=days))


# --------------------------------------------------------------------------- the Ads agent
class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(..., min_length=1, max_length=agent.MAX_QUESTION)
    ad_account_id: Optional[str] = Field(default=None, pattern="^[a-f0-9]{32}$")
    days: int = Field(default=7, ge=1, le=90)


class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ad_account_id: Optional[str] = Field(default=None, pattern="^[a-f0-9]{32}$")
    days: int = Field(default=7, ge=1, le=90)


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=1000)


@router.post("/integrations/agent/ask", summary="Ask the Ads agent about your campaigns")
def ask(request: Request, body: AskBody, workspace_id: str = _WS, brand_space_id: str = _BRAND):
    return _run(request, workspace_id, brand_space_id,
                lambda s, sc: agent.ask_campaign_question(s, sc, body.question, ad_account_id=body.ad_account_id,
                                                          days=body.days), bucket="ask", limit=60)


@router.post("/integrations/agent/propose", summary="Ads agent: propose changes (each needs approval)")
def propose(request: Request, body: ProposeBody = Body(default_factory=ProposeBody), workspace_id: str = _WS):
    return _run(request, workspace_id, "",
                lambda s, sc: agent.propose_optimization(s, sc, ad_account_id=body.ad_account_id, days=body.days),
                bucket="propose", limit=30)


@router.get("/integrations/agent/proposals", summary="Ads agent proposals waiting for approval")
def proposals(request: Request, workspace_id: str = _WS,
              status: str = Query(default="pending", pattern="^(pending|executed|rejected|failed|)$")):
    return _run(request, workspace_id, "", lambda s, sc: {"items": actions.list_proposals(s, sc, status=status)})


def _decide(request: Request, item_id: str, workspace_id: str, decision: str, note: str):
    request_id = base.get_task_id(request)
    require_database(request_id)
    with get_session() as session:
        user_id = str(resolve_principal(request, session, request_id).id)
        try:
            scope = resolve(session, user_id, workspace_id=workspace_id or None)
        except IntegrationError as exc:
            raise _fail(request_id, exc) from exc
    try:
        out = actions.decide(scope, item_id, decision, via="web", note=note)
    except IntegrationError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, out)


@router.post("/integrations/agent/proposals/{item_id}/approve", summary="Approve one proposed ad change")
def approve(request: Request, item_id: str = _id(), workspace_id: str = _WS,
            body: DecisionBody = Body(default_factory=DecisionBody)):
    return _decide(request, item_id, workspace_id, "approve", body.note)


@router.post("/integrations/agent/proposals/{item_id}/reject", summary="Reject one proposed ad change")
def reject(request: Request, item_id: str = _id(), workspace_id: str = _WS,
           body: DecisionBody = Body(default_factory=DecisionBody)):
    return _decide(request, item_id, workspace_id, "reject", body.note)


# --------------------------------------------------------------------------- Slack (settings)
class ApproversBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slack_user_ids: list[str] = Field(default_factory=list, max_length=50)


@router.post("/integrations/slack/install", summary="Start installing the Slack app (Pro and above)")
def slack_install(request: Request, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: slack.start_install(s, sc), bucket="connect", limit=30)


@router.put("/integrations/slack/approvers", summary="Slack users who may approve ad changes")
def slack_approvers(request: Request, body: ApproversBody, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: slack.set_approvers(s, sc, body.slack_user_ids))


@router.delete("/integrations/slack", summary="Disconnect Slack")
def slack_disconnect(request: Request, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: {"disconnected": slack.disconnect(s, sc)})


# --------------------------------------------------------------------------- Slack (called by Slack)
async def _verified_body(request: Request) -> bytes | None:
    body = await request.body()
    ok = slack.verify_signature(body, request.headers.get("X-Slack-Request-Timestamp", ""),
                                request.headers.get("X-Slack-Signature", ""))
    return body if ok else None


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"ok": False})


def _command_job(form: dict) -> None:
    try:
        slack.post_response(_TRANSPORT, str(form.get("response_url") or ""), slack.command_message(form))
    except Exception as exc:  # noqa: BLE001 - background work never raises into the server
        logger.warning(f"slack command failed: {exc.__class__.__name__}")


def _interaction_job(payload: dict) -> None:
    try:
        slack.post_response(_TRANSPORT, str(payload.get("response_url") or ""), slack.interaction_message(payload))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"slack interaction failed: {exc.__class__.__name__}")


def _event_job(payload: dict) -> None:
    try:
        slack.handle_event(payload, transport=_TRANSPORT)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"slack event failed: {exc.__class__.__name__}")


@router.post("/integrations/slack/commands", summary="Slack slash command (signed by Slack)", include_in_schema=False)
async def slack_commands(request: Request, background: BackgroundTasks):
    body = await _verified_body(request)
    if body is None:
        return _unauthorized()
    from urllib.parse import parse_qs

    form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", errors="replace")).items()}
    background.add_task(_command_job, form)
    return JSONResponse({"response_type": "ephemeral", "text": "Working on it..."})


@router.post("/integrations/slack/events", summary="Slack Events API (signed by Slack)", include_in_schema=False)
async def slack_events(request: Request, background: BackgroundTasks):
    body = await _verified_body(request)
    if body is None:
        return _unauthorized()
    import json

    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return JSONResponse(status_code=400, content={"ok": False})
    if payload.get("type") == "url_verification":
        return JSONResponse(slack.handle_event(payload))
    if request.headers.get("X-Slack-Retry-Num"):
        return JSONResponse({"ok": True})  # first delivery is already being handled
    background.add_task(_event_job, payload)
    return JSONResponse({"ok": True})


@router.post("/integrations/slack/interactions", summary="Slack buttons (signed by Slack)", include_in_schema=False)
async def slack_interactions(request: Request, background: BackgroundTasks):
    body = await _verified_body(request)
    if body is None:
        return _unauthorized()
    background.add_task(_interaction_job, slack.parse_interaction_body(body))
    return JSONResponse({})


# --------------------------------------------------------------------------- social + products
@router.get("/integrations/social", summary="Social accounts shared by the workspace (one per platform)")
def social(request: Request, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: service.social_overview(s, sc))


class ShopifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop: str = Field(..., min_length=3, max_length=200)
    token: str = Field(..., min_length=10, max_length=200)
    limit: int = Field(default=50, ge=1, le=250)


class MedusaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(..., min_length=8, max_length=500)
    publishable_key: str = Field(..., min_length=8, max_length=300)
    storefront_url: str = Field(default="", max_length=500)
    limit: int = Field(default=50, ge=1, le=250)


class CsvBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = Field(default=None, max_length=2_000_000)
    url: Optional[str] = Field(default=None, max_length=2048)
    store_name: str = Field(default="", max_length=200)
    currency: str = Field(default="USD", pattern="^[A-Za-z]{3}$")
    limit: int = Field(default=250, ge=1, le=250)


@router.post("/integrations/products/shopify", summary="Import products with a Shopify Admin API token")
def import_shopify(request: Request, body: ShopifyBody, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: product_sources.import_shopify_admin(
        s, sc, shop=body.shop, token=body.token, limit=body.limit, transport=_TRANSPORT), bucket="products", limit=20)


@router.post("/integrations/products/medusa", summary="Import products from a Medusa store")
def import_medusa(request: Request, body: MedusaBody, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: product_sources.import_medusa(
        s, sc, base_url=body.base_url, publishable_key=body.publishable_key, storefront_url=body.storefront_url,
        limit=body.limit), bucket="products", limit=20)


@router.post("/integrations/products/csv", summary="Import products from CSV text or a CSV link (Shopier)")
def import_csv(request: Request, body: CsvBody, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: product_sources.import_csv(
        s, sc, text=body.text, url=body.url, store_name=body.store_name, default_currency=body.currency.upper(),
        limit=body.limit), bucket="products", limit=20)


@router.post("/integrations/products/{provider}/resync", summary="Re-import from a saved product source")
def resync(request: Request, provider: str = _SOURCE, workspace_id: str = _WS):
    transport = _TRANSPORT if provider == "shopify" else None
    return _run(request, workspace_id, "", lambda s, sc: product_sources.resync(s, sc, provider, transport=transport),
                bucket="products", limit=20)


@router.delete("/integrations/products/{provider}", summary="Forget a saved product source")
def remove_source(request: Request, provider: str = _SOURCE, workspace_id: str = _WS):
    return _run(request, workspace_id, "", lambda s, sc: {"removed": product_sources.remove_source(s, sc, provider)})


__all__ = ["router", "set_transport"]
