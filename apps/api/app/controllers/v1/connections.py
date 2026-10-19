"""Direct-Publish Account-Connect v1 API controller (OAuth).

Auth-gated, strictly owner-scoped endpoints under ``/api/v1`` that let a creator
connect a social platform (TikTok / Instagram / YouTube) via the OAuth
authorization-code flow so a finished reel can be posted straight to their
account, and then publish one of their OWN completed jobs to a connected
provider:

* ``GET    /me/connections``                  — list the caller's connected
  providers. TOKEN-FREE: only the provider, provider-side account id, connection
  status/expiry and scopes are returned — never an access/refresh token.
* ``GET    /connections/{provider}/authorize`` — mint an opaque single-use CSRF
  ``state`` and return the provider authorize URL to send the browser to.
* ``GET    /connections/{provider}/callback``  — validate ``state`` (single-use),
  exchange the ``code`` for tokens, encrypt + store the connection, return ok.
* ``DELETE /me/connections/{provider}``        — disconnect (owner-scoped).
* ``POST   /jobs/{job_id}/publish/{provider}``  — publish the caller's OWN
  completed job to a connected provider (403 for a foreign job, 409 when the
  provider is not connected / the job is not complete).

Design notes
------------
* **Auth + persistence guard reused.** ``_require_db`` / ``_resolve_user`` /
  ``get_session`` are imported from :mod:`app.controllers.v1.jobs` (the canonical
  guard block behind the single ``base.verify_token`` gate), so both auth paths
  (Clerk JWT + ``x-api-key``) match the rest of the API and this module stays
  import-safe.
* **Import-safe optional deps.** The OAuth service, publisher seam and DB layer
  are imported inside guarded blocks; when absent the endpoints degrade to a
  clean ``503`` at request time instead of an ``ImportError`` at startup.
* **SECURITY — never serialise a token.** No endpoint ever returns an access or
  refresh token (encrypted or not). Tokens are decrypted in-memory only for the
  outbound publish and are never placed in a response body.
* **CSRF state — shared + single-use.** ``authorize`` mints an opaque token in
  Redis; ``callback`` atomically consumes it exactly once and aborts (400) on a
  missing/unknown/replayed state BEFORE any code exchange. Redis failures fail
  closed with 503 rather than weakening CSRF protection.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`. No secrets are hardcoded — provider client
  ids/secrets and the token-encryption key come from config/env only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Path, Query, Request
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.core.launch import require_publishing_enabled

# Reuse the canonical persistence guard + auth helpers from jobs.py (which owns
# the guarded DB import). When the DB layer is absent these are ``None`` and
# ``_require_db`` raises a clean 503 at request time.
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.const import TASK_STATE_COMPLETE
from app.models.exception import HttpException
from app.models.schema import (
    AuthorizeResponse,
    ConnectionListResponse,
    PublishResultResponse,
)
from app.services.billing.pro_access import require_pro_action
from app.services.ratelimit import enforce_rate_limit
from app.utils import utils

# --------------------------------------------------------------------------- #
# Guarded optional imports (authored by sibling agents / depend on the DB layer;
# may be absent at compile time). Keeping these guarded makes the module
# import-safe: a missing dependency degrades to a clean 503 at request time.
# --------------------------------------------------------------------------- #
try:
    from app.services import oauth_connect
    from app.services.oauth_connect import (
        OAuthConfigError,
        OAuthError,
        OAuthRefreshError,
        OAuthStateStoreError,
    )

    _OAUTH_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the service layer
    oauth_connect = None  # type: ignore[assignment]
    OAuthConfigError = OAuthError = OAuthRefreshError = OAuthStateStoreError = Exception  # type: ignore[misc,assignment]
    _OAUTH_IMPORT_ERROR = exc

try:
    from app.models.db.models import Job
    from app.models.db.repositories import (
        SOCIAL_PROVIDERS,
        SocialAccountRepository,
        _normalize_provider,
    )

    _CONN_DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before the DB layer
    Job = None  # type: ignore[assignment,misc]
    SOCIAL_PROVIDERS = frozenset()  # type: ignore[assignment]
    SocialAccountRepository = None  # type: ignore[assignment,misc]
    _normalize_provider = None  # type: ignore[assignment]
    _CONN_DB_IMPORT_ERROR = exc


router = new_router()

# --------------------------------------------------------------------------- #
# Single-use CSRF state store. Redis is deliberately mandatory here: unlike rate
# limits, a process-local fallback would break CSRF validation across API replicas.
# --------------------------------------------------------------------------- #
try:
    _STATE_STORE = (
        oauth_connect.RedisSingleUseStateStore.from_config()
        if oauth_connect is not None
        else None
    )
except Exception as exc:  # pragma: no cover - only when Redis client init fails
    _STATE_STORE = None
    _OAUTH_IMPORT_ERROR = _OAUTH_IMPORT_ERROR or exc

# --------------------------------------------------------------------------- #
# Tunables (config-overridable). Both connect and publish reach external
# providers, so each is rate-limited per caller (the limiter degrades OPEN
# without Redis, so it never breaks the flow).
# --------------------------------------------------------------------------- #
_DEFAULT_CONNECT_RATE_LIMIT: int = 30
_DEFAULT_CONNECT_RATE_WINDOW_S: int = 3600
_DEFAULT_PUBLISH_RATE_LIMIT: int = 60
_DEFAULT_PUBLISH_RATE_WINDOW_S: int = 3600


def _connect_rate_limit() -> int:
    """Max connect operations per window per user (``reelforge_connect_rate_limit``)."""
    return int(
        config.app.get("reelforge_connect_rate_limit", _DEFAULT_CONNECT_RATE_LIMIT)
    )


def _connect_rate_window_s() -> int:
    """Connect rate-limit window in seconds (``reelforge_connect_rate_window_s``)."""
    return int(
        config.app.get(
            "reelforge_connect_rate_window_s", _DEFAULT_CONNECT_RATE_WINDOW_S
        )
    )


def _publish_rate_limit() -> int:
    """Max direct publishes per window per user (``reelforge_direct_publish_rate_limit``)."""
    return int(
        config.app.get(
            "reelforge_direct_publish_rate_limit", _DEFAULT_PUBLISH_RATE_LIMIT
        )
    )


def _publish_rate_window_s() -> int:
    """Direct-publish rate-limit window (``reelforge_direct_publish_rate_window_s``)."""
    return int(
        config.app.get(
            "reelforge_direct_publish_rate_window_s", _DEFAULT_PUBLISH_RATE_WINDOW_S
        )
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _require_connections(request_id: str) -> None:
    """Raise 503 when the OAuth service / connections DB layer is unavailable."""
    if (
        oauth_connect is None
        or SocialAccountRepository is None
        or _STATE_STORE is None
    ):
        error = _OAUTH_IMPORT_ERROR or _CONN_DB_IMPORT_ERROR
        logger.error(
            f"connections layer unavailable, request_id: {request_id}, error: {error}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: account-connect is not available",
        )


def _normalized_provider(provider: str, request_id: str) -> str:
    """Validate + normalize a path ``provider`` to a known social provider.

    An unknown/blank provider is a clean ``404`` (no existence leak — the route
    simply does not resolve to a supported platform) rather than a raw ``422``.
    """
    try:
        return _normalize_provider(provider)
    except Exception:  # noqa: BLE001 - unknown provider -> clean 404
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: unknown provider",
        )


def _redirect_uri(provider: str) -> str:
    """Resolve the OAuth callback redirect URI for ``provider`` (config/env only).

    Env ``<PROVIDER>_REDIRECT_URI`` wins over ``config.app['<provider>_redirect_uri']``,
    which wins over a base ``config.app['oauth_redirect_base'] + the callback path``.
    Returns ``""`` when nothing is configured (the caller maps that to a clean 503
    — a redirect URI is server-side config, never a client input). Never raises.
    """
    env = os.getenv(f"{provider.upper()}_REDIRECT_URI", "").strip()
    if env:
        return env
    explicit = str(config.app.get(f"{provider}_redirect_uri", "") or "").strip()
    if explicit:
        return explicit
    base_url = str(config.app.get("oauth_redirect_base", "") or "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}/api/v1/connections/{provider}/callback"
    return ""


def _connection_status(token_expires_at: Any, now: datetime) -> str:
    """Return ``'expired'`` when the token's expiry is in the past, else ``'connected'``."""
    if token_expires_at is None:
        return "connected"
    expires = token_expires_at
    if getattr(expires, "tzinfo", None) is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return "expired" if expires <= now else "connected"


def _connection_public_data(row: Any, now: datetime) -> dict:
    """Serialise a ``SocialAccount`` row to its TOKEN-FREE public envelope.

    NEVER includes ``access_token_enc`` / ``refresh_token_enc`` (or any decrypted
    token) — only the provider, the provider-side account id, the connection
    status/expiry, the granted scopes and timestamps. Read every attribute while
    the row is still attached to its session.
    """
    expires = getattr(row, "token_expires_at", None)
    connected_at = getattr(row, "connected_at", None)
    updated_at = getattr(row, "updated_at", None)
    return {
        "provider": row.provider,
        "external_account_id": getattr(row, "external_account_id", "") or "",
        "connected": True,
        "status": _connection_status(expires, now),
        "scopes": getattr(row, "scopes", "") or "",
        "token_expires_at": expires.isoformat() if expires is not None else None,
        "connected_at": connected_at.isoformat() if connected_at is not None else None,
        "updated_at": updated_at.isoformat() if updated_at is not None else None,
    }


def _upload_client(provider: str) -> Any:
    """Return the provider's live :class:`VideoUploadClient`, or ``None``.

    The live client (:class:`~app.services.publishers.http_client.NativeUploadClient`)
    delegates the documented platform HTTP upload to the native connectors and
    resolves credentials from the supplied per-user token or ``<PLATFORM>_ACCESS_TOKEN``.
    It degrades cleanly (a clear :class:`PublishError`) when no token can be
    resolved rather than making a half-formed call. ``None`` is returned only for
    a provider that has no connector at all — the endpoint maps that to a clean
    ``503`` "not configured". Tests inject their own mock.
    """
    from app.domains.publishing.connectors import get_connector
    from app.services.publishers.http_client import NativeUploadClient

    if get_connector(provider) is None:
        return None
    return NativeUploadClient()


def _build_publisher(provider: str, client: Any) -> Any:
    """Construct a publisher for ``provider`` wired to the injected upload client."""
    from app.services.publishers.instagram import InstagramPublisher
    from app.services.publishers.tiktok import TikTokPublisher
    from app.services.publishers.youtube import YouTubePublisher

    builders = {
        "tiktok": TikTokPublisher,
        "instagram": InstagramPublisher,
        "youtube": YouTubePublisher,
    }
    builder = builders.get(provider)
    if builder is not None:
        return builder(client)

    from app.services.publishers.base import BasePublisher

    publisher = BasePublisher(client)
    publisher.provider = provider
    return publisher


def _enforce_content_gate(provider: str, caption: str, request_id: str) -> None:
    """Run the pre-publish content quality + safety gate; ``409`` when held.

    Mirrors the native publish path: the exact copy that would be posted is judged
    BEFORE any outbound call. A held verdict (``needs_edit`` / ``block`` / low
    confidence) stops the publish with a clean ``409`` for human review; the gate
    itself degrades to allow-with-review and never raises, so a decision-backend
    outage cannot break publishing. The caption is treated as untrusted data.
    """
    from app.domains.publishing.content_gate import GateContext, evaluate_content_sync

    hook = next((ln.strip() for ln in (caption or "").splitlines() if ln.strip()), "")
    gate = evaluate_content_sync(caption or "", hook, GateContext(platform=provider))
    if gate.can_publish:
        return
    reasons = "; ".join(f"{k}: {v}" for k, v in gate.reasons.items()) or gate.decision
    logger.info(
        f"content gate held publish to {provider} (decision={gate.decision}), "
        f"request_id: {request_id}"
    )
    raise HttpException(
        task_id=request_id,
        status_code=409,
        message=(
            f"{request_id}: content gate held this reel for review "
            f"(decision={gate.decision}); reasons: {reasons}"
        ),
    )


# --------------------------------------------------------------------------- #
# GET /me/connections  (list — token-free)
# --------------------------------------------------------------------------- #
@router.get(
    "/me/connections",
    response_model=ConnectionListResponse,
    summary="List the caller's connected social accounts (never any token)",
)
def list_connections(request: Request):
    """Return the caller's connected providers, newest first (owner-scoped).

    TOKEN-FREE: only the provider, provider-side account id, connection
    status/expiry and scopes are returned — never an access/refresh token.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_connections(request_id)

    now = datetime.now(timezone.utc)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = SocialAccountRepository(session).list_for_user(user.id)
        data = [_connection_public_data(r, now) for r in rows]

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /connections/{provider}/authorize  (mint state + authorize URL)
# --------------------------------------------------------------------------- #
@router.get(
    "/connections/{provider}/authorize",
    response_model=AuthorizeResponse,
    summary="Begin an OAuth connect: return the authorize URL + single-use state",
)
def authorize_connection(
    request: Request,
    provider: str = Path(..., description="tiktok | instagram | youtube"),
    scopes: str = Query(default="", max_length=500, description="Override scopes"),
):
    """Mint an opaque single-use CSRF ``state`` and return the authorize URL.

    Order: auth -> validate provider (404) -> per-caller rate limit -> resolve the
    server-side redirect URI (503 if unconfigured) -> mint state -> build the
    provider authorize URL (503 when the provider's client id is not configured).
    The caller must echo ``state`` back on the callback; nothing sensitive is
    returned.
    """
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    _require_db(request_id)
    _require_connections(request_id)
    normalized = _normalized_provider(provider, request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)  # auth gate
        enforce_rate_limit(
            request,
            f"connect:{user.id}",
            limit=_connect_rate_limit(),
            window_s=_connect_rate_window_s(),
        )

    redirect_uri = _redirect_uri(normalized)
    if not redirect_uri:
        logger.error(
            f"no OAuth redirect uri configured for {normalized}, "
            f"request_id: {request_id}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: {normalized} connect is not configured",
        )

    try:
        state = _STATE_STORE.issue()
    except OAuthStateStoreError as exc:
        logger.error(
            f"OAuth state store unavailable for {normalized}, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: account-connect is temporarily unavailable",
        )
    try:
        authorize_url = oauth_connect.build_authorize_url(
            normalized, state, redirect_uri, scopes=scopes
        )
    except OAuthConfigError as exc:
        # Provider client id absent — a server-side misconfiguration, not a client
        # error. Surface a clean 503 (never leak the missing key name to callers).
        logger.error(
            f"{normalized} authorize misconfigured, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: {normalized} connect is not configured",
        )

    data = {"provider": normalized, "authorize_url": authorize_url, "state": state}
    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# GET /connections/{provider}/callback  (validate state -> exchange -> store)
# --------------------------------------------------------------------------- #
@router.get(
    "/connections/{provider}/callback",
    response_model=ConnectionListResponse,
    summary="OAuth callback: validate state, exchange code, store the connection",
)
def connection_callback(
    request: Request,
    provider: str = Path(..., description="tiktok | instagram | youtube"),
    code: str = Query(default="", description="Provider authorization code"),
    state: str = Query(default="", description="The single-use CSRF state"),
):
    """Finish an OAuth connect: validate ``state``, exchange ``code``, store tokens.

    CSRF: ``state`` is :meth:`SingleUseStateStore.consume`-d FIRST — a missing,
    unknown, or replayed state is a clean ``400`` BEFORE any code exchange. A
    blank ``code`` is a ``400``. The exchanged tokens are encrypted and UPSERTed
    into the caller's single ``(user, provider)`` connection; the response is the
    caller's connection list (TOKEN-FREE) — the tokens themselves are never
    returned.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_connections(request_id)
    normalized = _normalized_provider(provider, request_id)

    # CSRF gate FIRST — reject a missing/unknown/replayed state before any work.
    try:
        state_valid = _STATE_STORE.consume(state)
    except OAuthStateStoreError as exc:
        logger.error(
            f"OAuth state store unavailable for {normalized}, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: account-connect is temporarily unavailable",
        )
    if not state_valid:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid or expired state",
        )
    if not (code or "").strip():
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: authorization code is required",
        )

    redirect_uri = _redirect_uri(normalized)
    if not redirect_uri:
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: {normalized} connect is not configured",
        )

    now = datetime.now(timezone.utc)
    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            tokens = oauth_connect.exchange_code(normalized, code, redirect_uri)
            oauth_connect.store_account(session, user.id, normalized, tokens)
            rows = SocialAccountRepository(session).list_for_user(user.id)
            data = [_connection_public_data(r, now) for r in rows]
    except HttpException:
        raise
    except OAuthConfigError as exc:
        logger.error(
            f"{normalized} callback misconfigured, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: {normalized} connect is not configured",
        )
    except (OAuthError, ValueError) as exc:
        # Bad code / unusable provider response -> clean 400 (client-recoverable).
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: failed to connect {normalized}: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - token-store / crypto failure -> 502
        logger.error(
            f"failed to store {normalized} connection, request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to store the {normalized} connection",
        )

    return utils.get_response(200, data)


# --------------------------------------------------------------------------- #
# DELETE /me/connections/{provider}  (disconnect — owner-scoped)
# --------------------------------------------------------------------------- #
@router.delete(
    "/me/connections/{provider}",
    summary="Disconnect one of the caller's connected providers",
)
def disconnect_connection(
    request: Request,
    provider: str = Path(..., description="tiktok | instagram | youtube"),
):
    """Disconnect the caller's ``provider`` connection. ``404`` when not connected.

    Owner-scoped in the repository (``delete`` filters on the caller's
    ``user_id``): a provider the caller has not connected is indistinguishable
    from another creator's connection, so a caller can never disconnect — or even
    confirm the existence of — another user's account.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)
    _require_connections(request_id)
    normalized = _normalized_provider(provider, request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        deleted = SocialAccountRepository(session).delete(user.id, normalized)
        if not deleted:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: {normalized} is not connected",
            )

    return utils.get_response(200, {"disconnected": True, "provider": normalized})


# --------------------------------------------------------------------------- #
# POST /jobs/{job_id}/publish/{provider}  (direct publish — owner-scoped)
# --------------------------------------------------------------------------- #
@router.post(
    "/jobs/{job_id}/publish/{provider}",
    response_model=PublishResultResponse,
    summary="Publish your completed job straight to a connected provider",
)
def publish_to_provider(
    request: Request,
    job_id: str = Path(..., description="Job ID (must be the caller's own)"),
    provider: str = Path(..., description="tiktok | instagram | youtube"),
    caption: str = Query(default="", max_length=2200, description="Post caption"),
):
    """Publish the caller's OWN completed job to a connected provider.

    Order: auth -> validate provider (404) -> per-caller rate limit -> ownership
    (``404`` unknown job / ``403`` foreign job) -> completeness (``409`` when the
    job is not done) -> connection (``409`` when the provider is not connected) ->
    proactive token refresh -> decrypt token in-memory -> presign the rendered
    result -> upload via the injected provider client. The decrypted token is used
    only for the outbound call and is NEVER placed in the response.
    """
    request_id = base.get_task_id(request)
    require_publishing_enabled(request_id)
    _require_db(request_id)
    _require_connections(request_id)
    normalized = _normalized_provider(provider, request_id)
    if Job is None:  # pragma: no cover - guarded import already 503'd via _require_db
        _require_db(request_id)

    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        require_pro_action(str(user.id), request_id, action="direct publish")
        enforce_rate_limit(
            request,
            f"direct_publish:{user.id}:{job_id}",
            limit=_publish_rate_limit(),
            window_s=_publish_rate_window_s(),
        )

        job = session.get(Job, job_id)
        if job is None:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        # Ownership: a job owned by another creator is a 403 (the caller may not
        # publish someone else's job) — distinct from an unknown job's 404.
        if job.user_id != user.id:
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=f"{request_id}: not your job",
            )
        if job.state != TASK_STATE_COMPLETE or not getattr(job, "result_key", ""):
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: job is not complete; cannot publish",
            )

        # The provider must already be connected by this caller (409 otherwise).
        if oauth_connect.get_account(session, user.id, normalized) is None:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: {normalized} is not connected",
            )

        # Proactively refresh a (near-)expired token, then decrypt in-memory. A
        # missing refresh token on an expired connection means the user must
        # re-connect (409).
        try:
            oauth_connect.refresh_if_needed(session, user.id, normalized)
            tokens = oauth_connect.load_tokens(session, user.id, normalized)
        except OAuthRefreshError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: reconnect {normalized}: {exc}",
            )
        except OAuthConfigError as exc:
            logger.error(
                f"{normalized} publish misconfigured, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=503,
                message=f"{request_id}: {normalized} publish is not configured",
            )
        except HttpException:
            raise
        except Exception as exc:  # noqa: BLE001 - token decrypt failure -> 502
            logger.error(
                f"failed to load {normalized} tokens, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to load the {normalized} connection",
            )

        if tokens is None:  # pragma: no cover - get_account already asserted a row
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"{request_id}: {normalized} is not connected",
            )
        result_key = job.result_key

    # Presign the rendered result (external storage) and upload via the injected
    # provider client. Both are outside the DB transaction — a provider/storage
    # failure is a clean 502, never a 500 leak.
    try:
        video_url = _resolve_video_url_by_key(result_key, request_id)
    except Exception as exc:  # noqa: BLE001 - storage unavailable -> 502
        logger.error(
            f"failed to presign result for job {job_id}, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: object storage is unavailable",
        )

    client = _upload_client(normalized)
    if client is None:
        logger.error(
            f"no upload client wired for {normalized}, request_id: {request_id}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: {normalized} publish is not configured",
        )

    # Pre-publish CONTENT QUALITY + SAFETY gate — in front of every outbound call.
    _enforce_content_gate(normalized, caption, request_id)

    try:
        from app.services.publishers.base import PublishError

        publisher = _build_publisher(normalized, client)
        result = publisher.publish(
            access_token=tokens.access_token,
            video_url=video_url,
            caption=caption,
            external_account_id=getattr(tokens, "external_account_id", "") or "",
        )
    except PublishError as exc:
        logger.error(
            f"{normalized} publish failed for job {job_id}, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to publish to {normalized}: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - provider upload failure -> 502
        logger.error(
            f"{normalized} publish crashed for job {job_id}, "
            f"request_id: {request_id}: {exc}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: failed to publish to {normalized}",
        )

    data = {
        "provider": result.provider,
        "external_post_id": result.external_post_id,
        "url": result.url,
        "status": "published",
    }
    logger.info(
        f"published job {job_id} to {normalized} "
        f"(post={result.external_post_id}) request_id: {request_id}"
    )
    return utils.get_response(200, data)


def _resolve_video_url_by_key(result_key: str, request_id: str) -> str:
    """Presign a rendered result key for the outbound upload (external storage)."""
    from app.services.storage.r2 import get_r2_client

    return get_r2_client().presign_result_get(result_key)
