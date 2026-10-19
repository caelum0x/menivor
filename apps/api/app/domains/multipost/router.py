"""HTTP surface for multi-account publishing (owner-scoped, token-free).

    GET    /multipost/providers                       server state per platform (honest "not set up" state)
    GET    /multipost/accounts                        connected accounts visible to the caller
    GET    /multipost/connect/{provider}/authorize    begin OAuth (single-use state bound to the caller)
    POST   /multipost/connect/callback                finish OAuth ({code, state}; provider from the state)
    PATCH  /multipost/accounts/{account_id}           pacing: daily cap, gap, posting hours, time zone, pause
    DELETE /multipost/accounts/{account_id}           disconnect (cancels its posts that have not gone out)
    GET    /multipost/accounts/{account_id}/creator-info   TikTok posting options the composer must show
    POST   /multipost/campaigns/preview               planned schedule, nothing written
    POST   /multipost/campaigns                       create a batch and queue its posts
    GET    /multipost/campaigns                       the caller's batches with status counts
    GET    /multipost/campaigns/{campaign_id}         one batch with every post
    POST   /multipost/campaigns/{campaign_id}/cancel  cancel posts that have not started
    GET    /multipost/posts                           the caller's queue (optional ?status=)
    POST   /multipost/posts/{post_id}/cancel          cancel one post that has not started
    POST   /multipost/posts/{post_id}/retry           retry a failed or held post
    POST   /multipost/webhooks/tiktok                 TikTok post status deliveries (signed, no auth)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Path, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.api_dependencies import get_session
from app.core.api_dependencies import require_database as _require_db
from app.core.api_dependencies import resolve_principal as _resolve_user
from app.core.launch import require_publishing_enabled
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

from . import accounts as acct_service
from . import campaigns as campaign_service
from . import oauth, settings, webhooks
from .clients import ClientError
from .clients import tiktok as tt
from .clients.base import RequestsTransport
from .models import PROVIDERS, TIKTOK
from .oauth import ConnectError

router = new_router()

_CONNECT_LIMIT = 30
_WRITE_LIMIT = 120
_WINDOW_S = 3600
_WEBHOOK_LIMIT = 600  # per sender per minute; TikTok batches far below this


def _id():
    """A fresh Path() per route (FastAPI binds a Path object to one parameter name)."""
    return Path(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")

_PROVIDER = Path(..., min_length=1, max_length=16, pattern=r"^[a-z]+$")


def _error(request_id: str, status: int, message: str) -> HttpException:
    return HttpException(task_id=request_id, status_code=status, message=f"{request_id}: {message}")


def _caller(request: Request, request_id: str, *, bucket: str = "", limit: int = 0) -> str:
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        if bucket:
            enforce_rate_limit(request, f"{bucket}:{user.id}", limit=limit, window_s=_WINDOW_S)
        return str(user.id)


def _known(provider: str, request_id: str) -> str:
    value = str(provider or "").strip().lower()
    if value not in PROVIDERS:
        raise _error(request_id, 404, "unknown platform")
    return value


def _fail(request_id: str, exc: ConnectError) -> HttpException:
    return _error(request_id, exc.status_code, str(exc))


# --------------------------------------------------------------------------- #
# Providers + accounts
# --------------------------------------------------------------------------- #
@router.get("/multipost/providers", summary="Multi-account publishing: server state per platform")
def providers(request: Request):
    request_id = base.get_task_id(request)
    _caller(request, request_id)
    return utils.get_response(200, {"providers": [settings.provider_overview(p) for p in PROVIDERS]})


@router.get("/multipost/accounts", summary="Connected accounts visible to the caller")
def list_accounts(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    with get_session() as session:
        rows = acct_service.visible(session, user_id)
        data = [acct_service.public(r, user_id=user_id, session=session) for r in rows]
    return utils.get_response(200, {"accounts": data})


@router.get("/multipost/connect/{provider}/authorize", summary="Begin connecting an account")
def authorize(request: Request, provider: str = _PROVIDER,
              workspace_id: str = Query(default="", max_length=32, pattern=r"^[A-Za-z0-9]*$")):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    plat = _known(provider, request_id)
    user_id = _caller(request, request_id, bucket="multipost_connect", limit=_CONNECT_LIMIT)
    try:
        with get_session() as session:
            data = acct_service.start_connect(session, user_id, plat, workspace_id=workspace_id or None)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, data)


class CallbackBody(BaseModel):
    code: str = Field(..., min_length=1, max_length=2000)
    state: str = Field(..., min_length=10, max_length=200)


@router.post("/multipost/connect/callback", summary="Finish connecting an account")
def callback(request: Request, body: CallbackBody):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    user_id = _caller(request, request_id, bucket="multipost_connect", limit=_CONNECT_LIMIT)
    try:
        # 1) consume the single-use state (committed even if the exchange then fails)
        with get_session() as session:
            claimed = acct_service.claim_state(session, user_id, body.state)
        # 2) exchange the code with no DB connection held
        grant, identity = oauth.exchange(claimed.provider, body.code, verifier=claimed.verifier,
                                         transport=RequestsTransport(timeout_s=20))
        # 3) store the encrypted tokens
        with get_session() as session:
            data = acct_service.store_connection(session, user_id, claimed, grant, identity)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    except Exception as exc:  # noqa: BLE001 - provider down / storage failure
        logger.error(f"multipost connect callback failed, request_id: {request_id}: {exc}")
        raise _error(request_id, 502, "the platform could not be reached; try connecting again") from exc
    return utils.get_response(200, data)


class AccountBody(BaseModel):
    daily_cap: int | None = Field(default=None, ge=1, le=100)
    min_gap_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    posting_hours: list[int] | None = Field(default=None, max_length=24)
    timezone: str | None = Field(default=None, max_length=64)
    paused: bool | None = None


@router.patch("/multipost/accounts/{account_id}", summary="Change an account's posting pace")
def update_account(request: Request, body: AccountBody, account_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="multipost_write", limit=_WRITE_LIMIT)
    change = acct_service.AccountUpdate(**body.model_dump())
    try:
        with get_session() as session:
            data = acct_service.update(session, user_id, account_id, change)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, data)


@router.delete("/multipost/accounts/{account_id}", summary="Disconnect an account")
def delete_account(request: Request, account_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="multipost_write", limit=_WRITE_LIMIT)
    try:
        with get_session() as session:
            canceled = acct_service.disconnect(session, user_id, account_id)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, {"id": account_id, "disconnected": True, "posts_canceled": canceled})


@router.get("/multipost/accounts/{account_id}/creator-info", summary="TikTok posting options for an account")
def creator_info(request: Request, account_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="multipost_write", limit=_WRITE_LIMIT)
    transport = RequestsTransport(timeout_s=20)
    failure: ConnectError | None = None
    token = ""
    try:
        with get_session() as session:
            row = acct_service.get_for(session, user_id, account_id)
            if row.provider != TIKTOK:
                raise ConnectError("creator info is only for TikTok accounts", status_code=400)
            try:
                token = acct_service.valid_token(session, row, transport=transport)
            except ConnectError as exc:
                failure = exc  # commit the "needs reconnect" flag, then report it
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    if failure is not None:
        raise _fail(request_id, failure)
    try:
        info = tt.creator_info(token, transport=transport)
    except ClientError as exc:
        raise _error(request_id, 502, str(exc)) from exc
    return utils.get_response(200, {**info, "audited": settings.tiktok_audited()})


# --------------------------------------------------------------------------- #
# Campaigns + queue
# --------------------------------------------------------------------------- #
class CampaignBody(BaseModel):
    job_ids: list[str] = Field(..., min_length=1, max_length=campaign_service.MAX_VIDEOS)
    account_ids: list[str] = Field(..., min_length=1, max_length=campaign_service.MAX_ACCOUNTS)
    visibility: str = Field(..., pattern=r"^(public|friends|private)$")
    name: str = Field(default="", max_length=200)
    mode: str = Field(default="spread", pattern=r"^(spread|every)$")
    start_at: datetime | None = None
    caption: str = Field(default="", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    tiktok_mode: str = Field(default="direct", pattern=r"^(direct|draft)$")
    allow_comments: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    brand_content: bool = False
    brand_organic: bool = False
    # The creator ticks TikTok's consent line (Music Usage / Branded Content Policy).
    consent: bool = False

    def to_input(self) -> campaign_service.CampaignInput:
        return campaign_service.CampaignInput(
            job_ids=tuple(self.job_ids), account_ids=tuple(self.account_ids), visibility=self.visibility,
            name=self.name, mode=self.mode, start_at=self.start_at, caption=self.caption,
            hashtags=tuple(self.hashtags), tiktok_mode=self.tiktok_mode, allow_comments=self.allow_comments,
            allow_duet=self.allow_duet, allow_stitch=self.allow_stitch, brand_content=self.brand_content,
            brand_organic=self.brand_organic,
        )


@router.post("/multipost/campaigns/preview", summary="Preview a batch schedule")
def preview_campaign(request: Request, body: CampaignBody):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="multipost_write", limit=_WRITE_LIMIT)
    try:
        with get_session() as session:
            data = campaign_service.preview(session, user_id, body.to_input())
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, data)


@router.post("/multipost/campaigns", summary="Queue a batch of videos across accounts")
def create_campaign(request: Request, body: CampaignBody):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    if not body.consent:
        raise _error(request_id, 400, "confirm you agree to each platform's music and branded content rules")
    user_id = _caller(request, request_id, bucket="multipost_write", limit=_WRITE_LIMIT)
    try:
        with get_session() as session:
            data = campaign_service.create(session, user_id, body.to_input())
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, data)


@router.get("/multipost/campaigns", summary="The caller's batches")
def list_campaigns(request: Request):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    with get_session() as session:
        data = campaign_service.list_campaigns(session, user_id)
    return utils.get_response(200, {"campaigns": data})


@router.get("/multipost/campaigns/{campaign_id}", summary="One batch with its posts")
def get_campaign(request: Request, campaign_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        with get_session() as session:
            data = campaign_service.detail(session, user_id, campaign_id)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, data)


@router.post("/multipost/campaigns/{campaign_id}/cancel", summary="Cancel a batch's posts that have not started")
def cancel_campaign(request: Request, campaign_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="multipost_write", limit=_WRITE_LIMIT)
    try:
        with get_session() as session:
            data = campaign_service.cancel_campaign(session, user_id, campaign_id)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, data)


@router.get("/multipost/posts", summary="The caller's publish queue")
def list_posts(request: Request, status: str = Query(default="", max_length=16, pattern=r"^[a-z]*$")):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id)
    try:
        with get_session() as session:
            data = campaign_service.list_posts(session, user_id, status=status)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, {"posts": data})


@router.post("/multipost/posts/{post_id}/cancel", summary="Cancel a post that has not started")
def cancel_post(request: Request, post_id: str = _id()):
    request_id = base.get_task_id(request)
    user_id = _caller(request, request_id, bucket="multipost_write", limit=_WRITE_LIMIT)
    try:
        with get_session() as session:
            data = campaign_service.cancel_post(session, user_id, post_id)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, data)


@router.post("/multipost/posts/{post_id}/retry", summary="Retry a failed or held post")
def retry_post(request: Request, post_id: str = _id()):
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    user_id = _caller(request, request_id, bucket="multipost_write", limit=_WRITE_LIMIT)
    try:
        with get_session() as session:
            data = campaign_service.retry_post(session, user_id, post_id)
    except ConnectError as exc:
        raise _fail(request_id, exc) from exc
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #
@router.post("/multipost/webhooks/tiktok", summary="TikTok post status webhook (signed)")
async def tiktok_webhook(request: Request):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    enforce_rate_limit(request, "multipost_webhook_tiktok", limit=_WEBHOOK_LIMIT, window_s=60)
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise _error(request_id, 413, "body too large")
    try:
        webhooks.verify_tiktok(raw, request.headers.get("TikTok-Signature", ""))
        with get_session() as session:
            result = webhooks.apply_tiktok(session, raw)
    except webhooks.WebhookError as exc:
        raise _error(request_id, exc.status_code, str(exc)) from exc
    logger.info(f"tiktok webhook: {result}")
    return utils.get_response(200, {"received": True})
