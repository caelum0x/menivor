"""Ad-account integrations: connect, accounts, Brand-space assignment, reporting pull, overview.

Every function takes an open SQLAlchemy ``session`` (the router owns the
transaction) and a resolved :class:`~app.domains.integrations.scope.Scope`.
Tokens are encrypted with :mod:`app.services.crypto_tokens` before they reach a
row and decrypted only in :func:`valid_token`; nothing returned carries a token.
Network calls go through an injected transport.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from app.domains.integrations import metrics, onboarding
from app.domains.integrations.connectors import AD_PROVIDERS, get_connector
from app.domains.integrations.connectors.base import AccountInfo, AuthError, CampaignDraftRequest, ConnectorError, Grant
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.models import (
    KIND_ADS, STATUS_CONNECTED, STATUS_REAUTH, IntegrationAdAccount, IntegrationAdAccountBrand, IntegrationAdMetric,
    IntegrationConnection, IntegrationOAuthState,
)
from app.domains.integrations.scope import Scope, brand_space_belongs
from app.domains.integrations.settings import redirect_uri
from app.services import crypto_tokens

STATE_TTL = timedelta(minutes=15)
_REFRESH_LEAD = {"meta": timedelta(days=7)}
_DEFAULT_LEAD = timedelta(minutes=5)
MAX_BRAND_SPACES = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _hint(token: str) -> str:
    return f"{token[:4]}...{token[-2:]}" if len(token) > 10 else "..."


def _connector(provider: str):
    if provider not in AD_PROVIDERS:
        raise IntegrationError(404, "Unknown ad platform.")
    return get_connector(provider)


def _mapped(exc: ConnectorError) -> IntegrationError:
    if isinstance(exc, AuthError):
        return IntegrationError(400, exc.message)
    return IntegrationError(exc.status_code if exc.status_code in (400, 403, 422, 503) else 502, exc.message)


def _encrypt(value: str) -> str:
    try:
        return crypto_tokens.encrypt(value)
    except crypto_tokens.MissingTokenKeyError as exc:
        raise IntegrationError(503, "Token encryption is not configured on this server.") from exc


# --------------------------------------------------------------------------- #
# OAuth state (single use, hashed, bound to the user)
# --------------------------------------------------------------------------- #
def issue_state(session: Any, scope: Scope, provider: str) -> str:
    session.execute(delete(IntegrationOAuthState).where(IntegrationOAuthState.expires_at < _now()))
    state = secrets.token_urlsafe(32)
    session.add(IntegrationOAuthState(state_hash=_hash(state), owner_scope=scope.owner_scope,
                                      workspace_id=scope.workspace_id, user_id=scope.user_id, provider=provider,
                                      expires_at=_now() + STATE_TTL))
    session.flush()
    return state


def claim_state(session: Any, user_id: str, state: str) -> IntegrationOAuthState:
    row = session.get(IntegrationOAuthState, _hash(state or "")) if state else None
    if row is None or row.user_id != user_id:
        raise IntegrationError(400, "This connect link is not valid. Start again from Integrations.")
    # Consumed before the expiry check on purpose: a state is single use even when it fails.
    session.delete(row)
    session.flush()
    if _aware(row.expires_at) < _now():
        raise IntegrationError(400, "This connect link expired. Start again from Integrations.")
    return row


# --------------------------------------------------------------------------- #
# Connect / disconnect
# --------------------------------------------------------------------------- #
def start_connect(session: Any, scope: Scope, provider: str) -> dict:
    scope.require_manage()
    conn = _connector(provider)
    if conn.auth != "oauth":
        raise IntegrationError(400, f"{conn.label} connects with an API key.")
    if not conn.configured():
        raise IntegrationError(503, f"{conn.label} is not set up on this server yet.")
    state = issue_state(session, scope, provider)
    return {"provider": provider, "authorize_url": conn.authorize_url(state, redirect_uri())}


def store_connection(session: Any, *, owner_scope: str, workspace_id: str | None, user_id: str, kind: str,
                     provider: str, grant: Grant, display_name: str = "", meta: dict | None = None,
                     external_id: str = "") -> IntegrationConnection:
    row = session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == owner_scope, IntegrationConnection.provider == provider,
    )).scalar_one_or_none()
    if row is None:
        row = IntegrationConnection(owner_scope=owner_scope, provider=provider, kind=kind, access_token_enc="")
        session.add(row)
    row.workspace_id = workspace_id
    row.user_id = user_id
    row.kind = kind
    row.status = STATUS_CONNECTED
    row.access_token_enc = _encrypt(grant.access_token)
    row.refresh_token_enc = _encrypt(grant.refresh_token) if grant.refresh_token else None
    row.token_expires_at = grant.expires_at
    row.scopes = grant.scopes or ""
    row.token_hint = _hint(grant.access_token)
    row.external_id = (external_id or grant.external_id or "")[:200]
    row.display_name = display_name[:200]
    row.meta = dict(meta or {})
    row.last_error = ""
    row.connected_at = _now()
    session.flush()
    return row


def sync_accounts(session: Any, conn: IntegrationConnection, accounts: list[AccountInfo]) -> list[IntegrationAdAccount]:
    existing = {a.external_id: a for a in session.execute(select(IntegrationAdAccount).where(
        IntegrationAdAccount.connection_id == conn.id)).scalars()}
    seen = []
    for info in accounts:
        row = existing.get(info.external_id)
        if row is None:
            row = IntegrationAdAccount(connection_id=conn.id, owner_scope=conn.owner_scope, provider=conn.provider,
                                       external_id=info.external_id[:128])
            session.add(row)
        row.name = info.name[:300]
        row.currency = (info.currency or "USD")[:3].upper()
        row.timezone = (info.timezone or "")[:64]
        row.status = info.status if info.status in ("active", "inactive") else "active"
        seen.append(row)
    for external_id, row in existing.items():
        if external_id not in {a.external_id for a in accounts}:
            row.status = "unavailable"
    session.flush()
    return seen


def _after_connect(session: Any, scope: Scope, conn: IntegrationConnection, accounts: list[AccountInfo]) -> dict:
    rows = sync_accounts(session, conn, accounts)
    granted = onboarding.grant_once(session, scope, "connect_ad_accounts") if rows else 0
    return {"provider": conn.provider, "accounts": [account_view(session, r) for r in rows],
            "credits_granted": granted}


def finish_connect(session: Any, user_id: str, *, code: str, state: str, transport: Any) -> dict:
    claimed = claim_state(session, user_id, state)
    conn = _connector(claimed.provider)
    scope = Scope(user_id=user_id, workspace_id=claimed.workspace_id,
                  role="owner" if not claimed.workspace_id else _current_role(session, claimed.workspace_id, user_id))
    scope.require_manage()
    if not (code or "").strip():
        raise IntegrationError(400, f"{conn.label} did not send an authorization code.")
    try:
        grant = conn.exchange_code(transport, code.strip(), redirect_uri())
        accounts = conn.list_accounts(transport, grant.access_token)
    except ConnectorError as exc:
        raise _mapped(exc) from exc
    row = store_connection(session, owner_scope=claimed.owner_scope, workspace_id=claimed.workspace_id,
                           user_id=user_id, kind=KIND_ADS, provider=claimed.provider, grant=grant)
    return _after_connect(session, scope, row, accounts)


def _current_role(session: Any, workspace_id: str, user_id: str) -> str:
    from app.domains.integrations.scope import resolve

    return resolve(session, user_id, workspace_id=workspace_id).role


def connect_api_key(session: Any, scope: Scope, provider: str, api_key: str, *, transport: Any) -> dict:
    scope.require_manage()
    conn = _connector(provider)
    if conn.auth != "api_key":
        raise IntegrationError(400, f"{conn.label} connects by signing in.")
    key = (api_key or "").strip()
    # The internal-whitespace guard catches an accidentally-partial single-token
    # paste (applovin, openai_ads); it's skipped for a JSON credential blob
    # (apple_search_ads's {client_id, team_id, key_id, private_key}), whose PEM
    # private key legitimately contains spaces (e.g. "-----BEGIN PRIVATE KEY-----")
    # and newlines -- `conn.validate_key()` below does that format's own strict check.
    looks_like_json = key.startswith("{")
    if not 8 <= len(key) <= 4096 or (not looks_like_json and any(ch.isspace() for ch in key)):
        raise IntegrationError(422, f"Paste the full {conn.label} key.")
    try:
        grant = conn.validate_key(transport, key)
        accounts = conn.list_accounts(transport, grant.access_token)
    except ConnectorError as exc:
        raise _mapped(exc) from exc
    row = store_connection(session, owner_scope=scope.owner_scope, workspace_id=scope.workspace_id,
                           user_id=scope.user_id, kind=KIND_ADS, provider=provider, grant=grant)
    return _after_connect(session, scope, row, accounts)


def _connection(session: Any, owner_scope: str, provider: str) -> IntegrationConnection | None:
    return session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == owner_scope, IntegrationConnection.provider == provider,
    )).scalar_one_or_none()


def disconnect(session: Any, scope: Scope, provider: str) -> bool:
    """Delete the connection with its tokens, accounts, assignments and stored metrics."""
    scope.require_manage()
    row = _connection(session, scope.owner_scope, provider)
    if row is None:
        return False
    ids = list(session.execute(select(IntegrationAdAccount.id).where(
        IntegrationAdAccount.connection_id == row.id)).scalars())
    if ids:
        session.execute(delete(IntegrationAdMetric).where(IntegrationAdMetric.ad_account_id.in_(ids)))
        session.execute(delete(IntegrationAdAccountBrand).where(IntegrationAdAccountBrand.ad_account_id.in_(ids)))
        session.execute(delete(IntegrationAdAccount).where(IntegrationAdAccount.id.in_(ids)))
    session.delete(row)
    session.flush()
    return True


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def _grant_of(conn: IntegrationConnection) -> Grant:
    try:
        access = crypto_tokens.decrypt(conn.access_token_enc)
        refresh = crypto_tokens.decrypt(conn.refresh_token_enc) if conn.refresh_token_enc else None
    except crypto_tokens.TokenCryptoError as exc:
        raise IntegrationError(409, "The stored sign-in can no longer be read. Reconnect the account.") from exc
    return Grant(access_token=access, refresh_token=refresh, expires_at=_aware(conn.token_expires_at),
                 scopes=conn.scopes or "")


def mark_reauth(conn: IntegrationConnection, message: str) -> None:
    conn.status = STATUS_REAUTH
    conn.last_error = message[:1000]


def valid_token(session: Any, conn: IntegrationConnection, *, transport: Any, now: datetime | None = None) -> str:
    """Decrypted access token, refreshed first when it expires soon. Reauth needed -> 409."""
    if conn.status == STATUS_REAUTH:
        raise IntegrationError(409, f"Reconnect {get_connector(conn.provider).label} to keep reading reports.")
    grant = _grant_of(conn)
    moment = now or _now()
    lead = _REFRESH_LEAD.get(conn.provider, _DEFAULT_LEAD)
    if grant.expires_at is None or grant.expires_at - lead > moment:
        return grant.access_token
    try:
        fresh = get_connector(conn.provider).refresh(transport, grant)
    except AuthError as exc:
        mark_reauth(conn, exc.message)
        session.flush()
        raise IntegrationError(409, f"{exc.message}") from exc
    except ConnectorError as exc:
        raise _mapped(exc) from exc
    conn.access_token_enc = _encrypt(fresh.access_token)
    if fresh.refresh_token:
        conn.refresh_token_enc = _encrypt(fresh.refresh_token)
    conn.token_expires_at = fresh.expires_at
    conn.token_hint = _hint(fresh.access_token)
    session.flush()
    return fresh.access_token


# --------------------------------------------------------------------------- #
# Accounts + Brand spaces
# --------------------------------------------------------------------------- #
def _brand_ids(session: Any, account_id: str) -> list[str]:
    return sorted(session.execute(select(IntegrationAdAccountBrand.brand_space_id).where(
        IntegrationAdAccountBrand.ad_account_id == account_id)).scalars())


def account_view(session: Any, row: IntegrationAdAccount) -> dict:
    pulled = _aware(row.last_pulled_at)
    return {"id": row.id, "provider": row.provider, "external_id": row.external_id, "name": row.name,
            "currency": row.currency, "timezone": row.timezone, "status": row.status,
            "brand_space_ids": _brand_ids(session, row.id), "last_pulled_at": pulled.isoformat() if pulled else None}


def visible_accounts(session: Any, scope: Scope, *, provider: str | None = None) -> list[IntegrationAdAccount]:
    stmt = select(IntegrationAdAccount).where(IntegrationAdAccount.owner_scope == scope.owner_scope,
                                              IntegrationAdAccount.status != "unavailable")
    if provider:
        stmt = stmt.where(IntegrationAdAccount.provider == provider)
    if scope.brand_space_id:
        stmt = stmt.join(IntegrationAdAccountBrand,
                         IntegrationAdAccountBrand.ad_account_id == IntegrationAdAccount.id).where(
            IntegrationAdAccountBrand.brand_space_id == scope.brand_space_id)
    return list(session.execute(stmt.order_by(IntegrationAdAccount.created_at, IntegrationAdAccount.id)).scalars())


def get_account(session: Any, scope: Scope, ad_account_id: str) -> IntegrationAdAccount:
    for row in visible_accounts(session, scope):
        if row.id == ad_account_id:
            return row
    raise IntegrationError(404, "Ad account not found.")


def assign_brand_spaces(session: Any, scope: Scope, ad_account_id: str, brand_space_ids: list[str]) -> dict:
    """Replace the set of Brand spaces that can see one ad account."""
    scope.require_manage()
    row = session.get(IntegrationAdAccount, ad_account_id)
    if row is None or row.owner_scope != scope.owner_scope:
        raise IntegrationError(404, "Ad account not found.")
    wanted = list(dict.fromkeys(str(b).strip() for b in brand_space_ids if str(b).strip()))
    if len(wanted) > MAX_BRAND_SPACES:
        raise IntegrationError(422, f"Pick at most {MAX_BRAND_SPACES} Brand spaces.")
    for brand in wanted:
        if not brand_space_belongs(session, scope.user_id, scope.workspace_id, brand):
            raise IntegrationError(404, "Brand space not found.")
    session.execute(delete(IntegrationAdAccountBrand).where(IntegrationAdAccountBrand.ad_account_id == row.id))
    for brand in wanted:
        session.add(IntegrationAdAccountBrand(ad_account_id=row.id, brand_space_id=brand, created_by=scope.user_id))
    session.flush()
    return account_view(session, row)


# --------------------------------------------------------------------------- #
# Reporting pull
# --------------------------------------------------------------------------- #
def _info(row: IntegrationAdAccount) -> AccountInfo:
    return AccountInfo(external_id=row.external_id, name=row.name, currency=row.currency, timezone=row.timezone,
                       status=row.status)


def _upsert_rows(session: Any, account: IntegrationAdAccount, rows: list) -> int:
    existing = {(m.day, m.entity_id): m for m in session.execute(select(IntegrationAdMetric).where(
        IntegrationAdMetric.ad_account_id == account.id,
        IntegrationAdMetric.day.in_(list({r.day for r in rows}) or [""]))).scalars()}
    count = 0
    for r in rows:
        if not r.day or not r.entity_id:
            continue
        m = existing.get((r.day, r.entity_id))
        if m is None:
            m = IntegrationAdMetric(ad_account_id=account.id, owner_scope=account.owner_scope,
                                    provider=account.provider, day=r.day, entity_id=r.entity_id[:160])
            session.add(m)
            existing[(r.day, r.entity_id)] = m
        m.entity_name = (r.entity_name or m.entity_name or "")[:300]
        m.campaign_id = (r.campaign_id or "")[:128]
        m.group_id = (r.group_id or "")[:128]
        m.spend_minor, m.impressions, m.clicks = int(r.spend_minor), int(r.impressions), int(r.clicks)
        m.conversions, m.conversion_value_minor = r.conversions, r.conversion_value_minor
        m.reach = getattr(r, "reach", None)
        m.currency = (r.currency or account.currency)[:3]
        m.pulled_at = _now()
        count += 1
    session.flush()
    return count


def pull_metrics(session: Any, scope: Scope, *, transport: Any, ad_account_id: str | None = None, days: int = 7,
                 today: date | None = None) -> dict:
    """Read-only reporting pull for the visible accounts into ``integration_ad_metrics``."""
    since, until = metrics.window(days, today)
    accounts = visible_accounts(session, scope)
    if ad_account_id:
        accounts = [a for a in accounts if a.id == ad_account_id]
        if not accounts:
            raise IntegrationError(404, "Ad account not found.")
    total, errors = 0, []
    for account in accounts:
        conn = session.get(IntegrationConnection, account.connection_id)
        connector = get_connector(account.provider)
        try:
            token = valid_token(session, conn, transport=transport)
            rows = connector.fetch_metrics(transport, token, _info(account), since, until)
        except IntegrationError as exc:
            errors.append({"ad_account_id": account.id, "provider": account.provider, "message": exc.message})
            continue
        except AuthError as exc:
            mark_reauth(conn, exc.message)
            errors.append({"ad_account_id": account.id, "provider": account.provider, "message": exc.message})
            continue
        except ConnectorError as exc:
            conn.last_error = exc.message[:1000]
            errors.append({"ad_account_id": account.id, "provider": account.provider, "message": exc.message})
            continue
        total += _upsert_rows(session, account, rows)
        account.last_pulled_at = _now()
    session.flush()
    return {"accounts": len(accounts), "rows": total, "errors": errors}


# --------------------------------------------------------------------------- #
# Campaign drafts (always paused; never a spend decision, so no approval gate)
# --------------------------------------------------------------------------- #
MAX_DRAFT_COUNTRIES = 25


def draft_campaign(session: Any, scope: Scope, ad_account_id: str, *, name: str, daily_budget_minor: int,
                   countries: list[str] | None = None, adam_id: str = "", transport: Any) -> dict:
    """Create a new, PAUSED campaign on the connected platform. Credentials and
    targeting are the workspace's own; Menivor never enables spend on what it
    creates here -- the workspace reviews and launches it on the platform itself.
    """
    scope.require_manage()
    account = get_account(session, scope, ad_account_id)
    conn = session.get(IntegrationConnection, account.connection_id)
    connector = get_connector(account.provider)
    request = CampaignDraftRequest(name=name, daily_budget_minor=daily_budget_minor,
                                   countries=tuple((countries or [])[:MAX_DRAFT_COUNTRIES]), adam_id=adam_id)
    try:
        token = valid_token(session, conn, transport=transport)
        draft = connector.create_campaign(transport, token, _info(account), request)
    except AuthError as exc:
        mark_reauth(conn, exc.message)
        session.flush()
        raise IntegrationError(409, exc.message) from exc
    except ConnectorError as exc:
        raise _mapped(exc) from exc
    return {"provider": account.provider, "ad_account_id": account.id, "external_id": draft.external_id,
            "name": draft.name, "status": draft.status, "manage_url": draft.manage_url}


# --------------------------------------------------------------------------- #
# Keyword insights (read-only; used by app.domains.keyword_tracker)
# --------------------------------------------------------------------------- #
def keyword_insights(session: Any, scope: Scope, *, adam_id: str, country: str, terms: list[str],
                     transport: Any) -> list[dict]:
    """Apple's own Search Popularity for ``terms`` against one App Store app,
    via whichever ``apple_search_ads`` account is connected for ``scope``.
    Returns ``[]`` with no connected account -- the caller (keyword tracker)
    treats that as "not available yet", never an error. A connector that
    cannot support this (every other ad platform, today) also returns ``[]``,
    same honest fallback."""
    accounts = visible_accounts(session, scope, provider="apple_search_ads")
    if not accounts:
        return []
    account = accounts[0]
    connector = get_connector(account.provider)
    if not connector.supports_keyword_insights:
        return []
    conn = session.get(IntegrationConnection, account.connection_id)
    cache = dict((conn.meta or {}).get("keyword_insights") or {})
    try:
        token = valid_token(session, conn, transport=transport)
        insights, cache = connector.keyword_insights(transport, token, _info(account), adam_id=adam_id,
                                                      country=country, terms=terms, cache=cache)
    except AuthError as exc:
        mark_reauth(conn, exc.message)
        session.flush()
        raise IntegrationError(409, exc.message) from exc
    except ConnectorError as exc:
        raise _mapped(exc) from exc
    meta = dict(conn.meta or {})
    meta["keyword_insights"] = cache
    conn.meta = meta
    session.flush()
    return [{"term": i.term, "popularity": i.popularity} for i in insights]


# --------------------------------------------------------------------------- #
# Overview (the provider cards)
# --------------------------------------------------------------------------- #
def overview(session: Any, scope: Scope) -> dict:
    conns = {c.provider: c for c in session.execute(select(IntegrationConnection).where(
        IntegrationConnection.owner_scope == scope.owner_scope, IntegrationConnection.kind == KIND_ADS)).scalars()}
    accounts = visible_accounts(session, scope)
    cards = []
    for provider in AD_PROVIDERS:
        c = get_connector(provider)
        conn = conns.get(provider)
        mine = [account_view(session, a) for a in accounts if a.provider == provider]
        connected_at = _aware(conn.connected_at) if conn else None
        cards.append({
            "provider": provider, "label": c.label, "capabilities": c.capabilities, "auth": c.auth,
            "configured": c.configured(), "delivery": c.supports_delivery,
            "campaign_drafts": c.supports_campaign_drafts, "connected": conn is not None,
            "status": conn.status if conn else "not_connected", "token_hint": conn.token_hint if conn else "",
            "connected_at": connected_at.isoformat() if connected_at else None,
            "last_error": (conn.last_error or None) if conn else None,
            "account_count": len(mine), "accounts": mine,
        })
    return {"providers": cards, "can_manage": scope.can_manage, "brand_space_id": scope.brand_space_id}


def social_overview(session: Any, scope: Scope) -> dict:
    """One account per platform shared by the workspace (reuses multi-account publishing)."""
    from app.domains.multipost import accounts as acct_service
    from app.domains.multipost import settings as mp_settings
    from app.domains.multipost.models import PROVIDERS, MultipostAccount

    stmt = select(MultipostAccount)
    if scope.workspace_id:
        stmt = stmt.where(MultipostAccount.workspace_id == scope.workspace_id)
    else:
        stmt = stmt.where(MultipostAccount.user_id == scope.user_id, MultipostAccount.workspace_id.is_(None))
    rows = list(session.execute(stmt.order_by(MultipostAccount.connected_at)).scalars())
    platforms = []
    for provider in PROVIDERS:
        mine = [r for r in rows if r.provider == provider]
        pick = next((r for r in mine if r.status == "connected"), mine[0] if mine else None)
        server = mp_settings.provider_overview(provider)
        platforms.append({"provider": provider, "label": server["label"], "ready": server["ready"],
                          "notes": server["notes"],
                          "account": acct_service.public(pick, user_id=scope.user_id) if pick else None})
    return {"platforms": platforms, "workspace_id": scope.workspace_id, "can_manage": scope.can_manage}


__all__ = [
    "account_view", "assign_brand_spaces", "claim_state", "connect_api_key", "disconnect", "draft_campaign",
    "finish_connect", "get_account", "issue_state", "keyword_insights", "mark_reauth", "overview", "pull_metrics",
    "social_overview", "start_connect", "store_connection", "sync_accounts", "valid_token", "visible_accounts",
]
