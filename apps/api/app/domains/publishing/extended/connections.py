"""Connect, choose a target, refresh and disconnect extended-platform accounts.

States a creator can see for each platform (``connection_state``):

* ``not_configured``  - the operator has not registered the developer app.
* ``plan_required``   - X: no paid X API plan declared on this server.
* ``not_connected``   - available; the creator has not connected yet.
* ``needs_target``    - connected, but a Page / board must be chosen.
* ``needs_reauth``    - the token expired or was revoked; reconnect.
* ``connected``       - ready to post.

``review_note`` states which platform approval the operator still needs
(Meta App Review, LinkedIn Community Management, Pinterest Standard access), so
the UI can say plainly why a connect may be refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

from loguru import logger

from . import oauth
from . import repository as repo
from .catalog import (
    AUTH_APP_PASSWORD,
    AVAILABLE,
    BLUESKY,
    EXTENDED_PLATFORMS,
    FACEBOOK,
    LINKEDIN,
    PINTEREST,
    SPECS,
    TARGET_BOARD,
    TARGET_ORGANIZATION,
    TARGET_PAGE,
    TARGET_SELF,
    server_availability,
    spec_for,
)
from .connectors import bluesky as bluesky_connector
from .connectors.base import PublishError, Transport
from .models import CONN_CONNECTED, CONN_NEEDS_TARGET, CONN_REAUTH, PlatformConnection
from .oauth import ConnectError

try:
    from app.models.db.base import get_session
    from app.services import crypto_tokens

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import-safe; callers get a clear 503
    get_session = None  # type: ignore[assignment]
    crypto_tokens = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

_REFRESH_LEEWAY = timedelta(minutes=10)
# Bluesky logs in per post with the app password; Facebook posts with a Page
# token that does not expire (only the user token used to list Pages does).
_NON_EXPIRING = frozenset({BLUESKY, FACEBOOK})


def require_ready() -> None:
    if get_session is None or crypto_tokens is None:
        raise ConnectError(f"publishing persistence unavailable: {_IMPORT_ERROR}", status_code=503)
    if not crypto_tokens.is_configured():
        raise ConnectError("account connections are not set up on this server (token key missing)",
                           status_code=503)


def _enc(value: str) -> str:
    return crypto_tokens.encrypt(value)  # type: ignore[union-attr]


def _dec(blob: str | None) -> str:
    return crypto_tokens.decrypt(blob) if blob else ""  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Public (token-free) records
# --------------------------------------------------------------------------- #
def connection_record(row: PlatformConnection | None) -> dict | None:
    if row is None:
        return None
    expires = repo.aware(row.token_expires_at)
    return {
        "platform": row.platform,
        "status": row.status,
        "status_note": row.status_note or "",
        "account_name": row.account_name or "",
        "external_account_id": row.external_account_id or "",
        "target_kind": row.target_kind,
        "target_id": row.target_id or "",
        "target_name": row.target_name or "",
        "targets": [t for t in (row.targets or []) if isinstance(t, dict)],
        "scopes": row.scopes or "",
        "token_expires_at": expires.isoformat() if expires else None,
        "connected_at": repo.aware(row.connected_at).isoformat() if row.connected_at else None,
    }


def connection_state(platform: str, row: PlatformConnection | None) -> str:
    server_state, _ = server_availability(platform)
    if server_state != AVAILABLE:
        return server_state
    if row is None:
        return "not_connected"
    expires = repo.aware(row.token_expires_at)
    if row.status == CONN_REAUTH or (expires is not None and expires <= repo.utcnow()
                                     and not row.refresh_token_enc and row.platform not in _NON_EXPIRING):
        return CONN_REAUTH
    return row.status


def platform_record(platform: str, row: PlatformConnection | None) -> dict:
    spec = SPECS[platform]
    server_state, server_note = server_availability(platform)
    return {
        "platform": platform,
        "label": spec.label,
        "auth": spec.auth,
        "target_kind": spec.target_kind,
        "state": connection_state(platform, row),
        "server_state": server_state,
        "server_note": server_note,
        "review_note": spec.review_note,
        "cost_note": spec.cost_note,
        "supports_organization": bool(spec.organization_scopes),
        "rules": spec.rules.to_record(),
        "connection": connection_record(row),
    }


def overview(session: Any, user_id: str) -> list[dict]:
    rows = {r.platform: r for r in repo.list_connections(session, user_id)}
    return [platform_record(p, rows.get(p)) for p in EXTENDED_PLATFORMS]


# --------------------------------------------------------------------------- #
# OAuth connect
# --------------------------------------------------------------------------- #
def start_oauth(user_id: str, platform: str, *, organization: bool = False) -> dict:
    require_ready()
    spec = spec_for(platform)
    if spec is None:
        raise ConnectError("unknown platform", status_code=404)
    if spec.auth == AUTH_APP_PASSWORD:
        raise ConnectError(f"{spec.label} connects with an app password, not a redirect", status_code=400)
    server_state, note = server_availability(spec.key)
    if server_state != AVAILABLE:
        raise ConnectError(note, status_code=409)
    scopes = spec.organization_scopes if organization and spec.organization_scopes else spec.scopes
    state = oauth.new_state()
    verifier = oauth.new_code_verifier() if spec.pkce else ""
    url = oauth.authorize_url(spec.key, state, scopes=scopes, verifier=verifier)
    with get_session() as session:  # type: ignore[misc]
        repo.add_state(
            session, state_hash=oauth.state_hash(state), user_id=user_id, platform=spec.key,
            verifier_enc=_enc(verifier) if verifier else None, scopes=scopes,
        )
    return {"platform": spec.key, "authorize_url": url, "state": state}


def finish_oauth(user_id: str, code: str, state: str, *, transport: Transport) -> dict:
    """Validate the single-use state (bound to this creator), exchange, store."""
    require_ready()
    if not str(state or "").strip():
        raise ConnectError("invalid or expired connect session")
    with get_session() as session:  # type: ignore[misc]
        snapshot = repo.consume_state(session, state_hash=oauth.state_hash(state), user_id=user_id)
    if snapshot is None:
        raise ConnectError("invalid or expired connect session; start the connect again")
    verifier = _dec(snapshot.code_verifier_enc)
    account = oauth.exchange(snapshot.platform, code, verifier=verifier, transport=transport)
    return _store(user_id, snapshot.platform, account, transport=transport)


def _auto_target(platform: str, account: oauth.ConnectedAccount) -> oauth.Target | None:
    spec = SPECS[platform]
    if spec.target_kind == TARGET_SELF:
        selves = [t for t in account.targets if t.kind == TARGET_SELF]
        return selves[0] if selves else oauth.Target(account.external_account_id, account.account_name, TARGET_SELF)
    if len(account.targets) == 1:
        return account.targets[0]
    return None


def _store(user_id: str, platform: str, account: oauth.ConnectedAccount, *, transport: Transport) -> dict:
    target = _auto_target(platform, account)
    target_token_enc: str | None = None
    if platform == FACEBOOK and target is not None:
        target_token_enc = _enc(_facebook_page_token(account.access_token, target.id, transport))
    needs_target = target is None
    if SPECS[platform].target_kind in (TARGET_PAGE, TARGET_BOARD) and not account.targets:
        note = (
            "No Facebook Pages were shared. Reconnect and select at least one Page."
            if platform == FACEBOOK else "No Pinterest boards found. Create a board in Pinterest, then refresh."
        )
    else:
        note = "Choose where to post." if needs_target else ""
    values = {
        "status": CONN_NEEDS_TARGET if needs_target else CONN_CONNECTED,
        "status_note": note,
        "access_token_enc": _enc(account.access_token),
        "refresh_token_enc": _enc(account.refresh_token) if account.refresh_token else None,
        "token_expires_at": account.expires_at,
        "scopes": account.scopes,
        "external_account_id": account.external_account_id[:200],
        "account_name": account.account_name[:200],
        "target_kind": target.kind if target else SPECS[platform].target_kind,
        "target_id": target.id[:200] if target else "",
        "target_name": target.name[:200] if target else "",
        "target_token_enc": target_token_enc,
        "targets": [t.to_record() for t in account.targets],
        "meta": dict(account.meta),
    }
    with get_session() as session:  # type: ignore[misc]
        row = repo.upsert_connection(session, user_id=user_id, platform=platform, values=values)
        return platform_record(platform, row)


def _facebook_page_token(user_token: str, page_id: str, transport: Transport) -> str:
    for page in oauth.facebook_pages(user_token, transport=transport, with_tokens=True):
        if page["id"] == page_id and page.get("access_token"):
            return page["access_token"]
    raise ConnectError("that Facebook Page is not available to this connection; reconnect and select it")


# --------------------------------------------------------------------------- #
# Bluesky (app password)
# --------------------------------------------------------------------------- #
def connect_bluesky(user_id: str, handle: str, app_password: str, *, pds: str = "",
                    transport: Transport) -> dict:
    require_ready()
    ident = str(handle or "").strip().lstrip("@")
    secret = str(app_password or "").strip()
    if not ident or not secret:
        raise ConnectError("enter your Bluesky handle and an app password")
    host = bluesky_connector.pds_of({"pds": pds})
    try:
        session_info = bluesky_connector.create_session(ident, secret, host, transport=transport)
    except PublishError as exc:
        raise ConnectError(str(exc).split("] ", 1)[-1]) from exc
    account = oauth.ConnectedAccount(
        access_token=secret,
        external_account_id=session_info.did,
        account_name=f"@{session_info.handle}",
        targets=(oauth.Target(session_info.did, f"@{session_info.handle}", TARGET_SELF),),
        meta={"pds": host, "handle": session_info.handle},
    )
    return _store(user_id, BLUESKY, account, transport=transport)


# --------------------------------------------------------------------------- #
# Targets / disconnect
# --------------------------------------------------------------------------- #
def select_target(user_id: str, platform: str, target_id: str, *, transport: Transport) -> dict:
    require_ready()
    spec = spec_for(platform)
    if spec is None:
        raise ConnectError("unknown platform", status_code=404)
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_connection(session, user_id, spec.key)
        if row is None:
            raise ConnectError(f"connect {spec.label} first", status_code=409)
        targets = [t for t in (row.targets or []) if isinstance(t, dict)]
        chosen = next((t for t in targets if str(t.get("id")) == str(target_id)), None)
        if chosen is None:
            raise ConnectError("that destination is not available to this connection", status_code=404)
        user_token = _dec(row.access_token_enc)
    page_token_enc = _enc(_facebook_page_token(user_token, str(chosen["id"]), transport)) \
        if spec.key == FACEBOOK else None
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_connection(session, user_id, spec.key)
        if row is None:
            raise ConnectError(f"connect {spec.label} first", status_code=409)
        row.target_id = str(chosen["id"])[:200]
        row.target_name = str(chosen.get("name") or "")[:200]
        row.target_kind = str(chosen.get("kind") or spec.target_kind)
        if spec.key == FACEBOOK:
            row.target_token_enc = page_token_enc
        row.status = CONN_CONNECTED
        row.status_note = ""
        session.flush()
        return platform_record(spec.key, row)


def refresh_targets(user_id: str, platform: str, *, transport: Transport) -> dict:
    """Re-read Pages / organizations / boards (e.g. after creating a board)."""
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_connection(session, user_id, platform)
        if row is None:
            raise ConnectError("connect this platform first", status_code=409)
        token = _dec(row.access_token_enc)
        existing = [t for t in (row.targets or []) if isinstance(t, dict)]
    if platform == FACEBOOK:
        targets = [oauth.Target(p["id"], p["name"], TARGET_PAGE).to_record()
                   for p in oauth.facebook_pages(token, transport=transport)]
    elif platform == PINTEREST:
        targets = [t.to_record() for t in oauth.pinterest_boards(token, transport=transport)]
    elif platform == LINKEDIN:
        selves = [t for t in existing if t.get("kind") == TARGET_SELF]
        targets = selves + [t.to_record() for t in oauth.linkedin_organizations(token, transport=transport)]
    else:
        targets = existing
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_connection(session, user_id, platform)
        if row is None:
            raise ConnectError("connect this platform first", status_code=409)
        row.targets = targets
        if row.target_id and not any(str(t.get("id")) == row.target_id for t in targets):
            row.target_id = ""
            row.target_name = ""
            row.status = CONN_NEEDS_TARGET
            row.status_note = "The chosen destination is no longer available. Choose another."
        session.flush()
        return platform_record(platform, row)


def disconnect(user_id: str, platform: str) -> bool:
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        return repo.delete_connection(session, user_id, platform)


# --------------------------------------------------------------------------- #
# Credentials for a publish / inbox call (refreshing when needed)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Credentials:
    platform: str
    access_token: str
    target_id: str = ""
    target_token: str = ""
    external_account_id: str = ""
    scopes: str = ""
    meta: dict = field(default_factory=dict)


def credentials(user_id: str, platform: str, *, transport: Transport, require_target: bool = True) -> Credentials:
    """Decrypted, fresh credentials for ``platform``; raises :class:`ConnectError` when not usable."""
    require_ready()
    spec = spec_for(platform)
    if spec is None:
        raise ConnectError("unknown platform", status_code=404)
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_connection(session, user_id, spec.key)
        if row is None:
            raise ConnectError(f"no connected {spec.label} account; connect it under Connections", status_code=409)
        if row.status == CONN_REAUTH:
            raise ConnectError(row.status_note or f"reconnect {spec.label}", status_code=409, reauth=True)
        if require_target and row.status == CONN_NEEDS_TARGET:
            raise ConnectError(f"choose where to post on {spec.label} under Connections", status_code=409)
        creds = Credentials(
            platform=spec.key,
            access_token=_dec(row.access_token_enc),
            target_id=row.target_id or "",
            target_token=_dec(row.target_token_enc),
            external_account_id=row.external_account_id or "",
            scopes=row.scopes or "",
            meta=dict(row.meta or {}),
        )
        refresh_token = _dec(row.refresh_token_enc)
        expires = repo.aware(row.token_expires_at)
    if spec.key in _NON_EXPIRING or expires is None or expires - _REFRESH_LEEWAY > repo.utcnow():
        return creds
    try:
        renewed = oauth.refresh(spec.key, access_token=creds.access_token, refresh_token=refresh_token,
                                transport=transport)
    except ConnectError as exc:
        mark_reauth(user_id, spec.key, str(exc))
        raise
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_connection(session, user_id, spec.key)
        if row is not None:
            row.access_token_enc = _enc(renewed.access_token)
            if renewed.refresh_token:
                row.refresh_token_enc = _enc(renewed.refresh_token)
            row.token_expires_at = renewed.expires_at
            if renewed.scopes:
                row.scopes = renewed.scopes
    return replace(creds, access_token=renewed.access_token)


def mark_reauth(user_id: str, platform: str, note: str) -> None:
    try:
        with get_session() as session:  # type: ignore[misc]
            row = repo.get_connection(session, user_id, platform)
            if row is not None:
                row.status = CONN_REAUTH
                row.status_note = (note or "Reconnect this account.")[:500]
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning(f"could not mark {platform} connection for re-auth: {exc}")


def target_kinds() -> tuple[str, ...]:
    return (TARGET_SELF, TARGET_PAGE, TARGET_ORGANIZATION, TARGET_BOARD)
