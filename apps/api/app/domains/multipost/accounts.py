"""Connected accounts: OAuth connect, listing, pacing settings, tokens.

Every function takes an open SQLAlchemy ``session`` (the router/queue owns the
transaction). Access rules: an account is visible to its owner and, when shared
to a workspace, to that workspace's members; posting needs owner/admin/editor,
managing (settings, disconnect) needs owner/admin.

Tokens: encrypted with :mod:`app.services.crypto_tokens` before they reach a row
and decrypted only inside :func:`valid_token`. Nothing returned to a client ever
carries a token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, or_, select

from app.services import crypto_tokens

from . import oauth, pacing, settings
from .clients.base import Transport
from .models import (
    ACCOUNT_CONNECTED,
    ACCOUNT_PAUSED,
    ACCOUNT_REAUTH,
    COUNTED_POST_STATUSES,
    INSTAGRAM,
    OPEN_POST_STATUSES,
    POST_CANCELED,
    MultipostAccount,
    MultipostOAuthState,
    MultipostPost,
)

STATE_TTL = timedelta(minutes=15)
POSTING_ROLES = frozenset({"owner", "admin", "editor"})
MANAGING_ROLES = frozenset({"owner", "admin"})
# Refresh this long before expiry (Instagram tokens last 60 days: renew a week early).
_REFRESH_LEAD = {"tiktok": timedelta(minutes=30), "youtube": timedelta(minutes=5), "instagram": timedelta(days=7)}
MAX_ACCOUNTS_PER_OWNER = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Access
# --------------------------------------------------------------------------- #
def memberships(session: Any, user_id: str) -> dict[str, str]:
    """``{workspace_id: role}`` for the user (empty when workspaces are unavailable)."""
    try:
        from app.models.db.models import WorkspaceMember
    except Exception:  # pragma: no cover - core models always import
        return {}
    rows = session.execute(
        select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(WorkspaceMember.user_id == user_id)
    ).all()
    return {str(ws): str(role or "") for ws, role in rows}


def _allowed(row: MultipostAccount, user_id: str, roles: dict[str, str], needed: frozenset[str]) -> bool:
    if row.user_id == user_id:
        return True
    return bool(row.workspace_id) and roles.get(str(row.workspace_id), "") in needed


def can_post(session: Any, user_id: str, row: MultipostAccount) -> bool:
    """Whether ``user_id`` may post to ``row`` right now (re-checked by the queue at publish time,
    so a member removed from the workspace, or demoted to viewer, stops posting to a shared account)."""
    if row.user_id == user_id:
        return True
    if not row.workspace_id:
        return False
    return _allowed(row, user_id, memberships(session, user_id), POSTING_ROLES)


def visible(session: Any, user_id: str) -> list[MultipostAccount]:
    roles = memberships(session, user_id)
    cond = MultipostAccount.user_id == user_id
    if roles:
        cond = or_(cond, MultipostAccount.workspace_id.in_(list(roles)))
    rows = session.execute(select(MultipostAccount).where(cond).order_by(MultipostAccount.connected_at)).scalars()
    return list(rows)


def get_for(session: Any, user_id: str, account_id: str, *, manage: bool = False) -> MultipostAccount:
    roles = memberships(session, user_id)
    row = session.get(MultipostAccount, account_id)
    if row is None or not (row.user_id == user_id or (row.workspace_id and str(row.workspace_id) in roles)):
        raise oauth.ConnectError("account not found", status_code=404)
    if not _allowed(row, user_id, roles, MANAGING_ROLES if manage else POSTING_ROLES):
        raise oauth.ConnectError("you do not have permission to do that with this account", status_code=403)
    return row


def check_workspace(session: Any, user_id: str, workspace_id: str | None) -> str | None:
    if not workspace_id:
        return None
    if memberships(session, user_id).get(workspace_id, "") not in MANAGING_ROLES:
        raise oauth.ConnectError("only workspace owners and admins can share accounts there", status_code=403)
    return workspace_id


# --------------------------------------------------------------------------- #
# Public envelope
# --------------------------------------------------------------------------- #
def limits_for(row: MultipostAccount) -> pacing.Limits:
    pol = settings.policy(row.provider)
    return pacing.effective_limits(
        daily_cap=int(row.daily_cap or 0), gap_minutes=int(row.min_gap_minutes or 0),
        platform_cap=pol.platform_daily_cap, default_cap=pol.default_daily_cap,
        default_gap=pol.default_gap_minutes, gap_floor=pol.min_gap_floor_minutes,
        hours=list(row.posting_hours or []), tz=row.timezone or "UTC",
    )


def counted_times(session: Any, account_id: str, *, around: datetime, exclude_post: str = "",
                  include_scheduled: bool = False) -> list[datetime]:
    """Times of posts that count against the account's limits within +-2 days of ``around``."""
    statuses = set(COUNTED_POST_STATUSES) | ({"scheduled"} if include_scheduled else set())
    rows = session.execute(
        select(MultipostPost.id, MultipostPost.status, MultipostPost.scheduled_at, MultipostPost.next_attempt_at,
               MultipostPost.published_at)
        .where(MultipostPost.account_id == account_id, MultipostPost.status.in_(statuses))
    ).all()
    out: list[datetime] = []
    for post_id, status, scheduled_at, next_attempt_at, published_at in rows:
        if post_id == exclude_post:
            continue
        when = aware(published_at) if status == "published" and published_at else \
            aware(next_attempt_at or scheduled_at)
        if when is not None and abs(when - around) <= timedelta(days=2):
            out.append(when)
    return sorted(out)


def public(row: MultipostAccount, *, user_id: str = "", session: Any = None) -> dict:
    limits = limits_for(row)
    used = 0
    if session is not None:
        now = _now()
        used = sum(1 for t in counted_times(session, row.id, around=now) if now - pacing.DAY < t <= now)
    return {
        "id": row.id,
        "provider": row.provider,
        "handle": row.handle,
        "display_name": row.display_name or row.handle,
        "avatar_url": row.avatar_url,
        "status": row.status,
        "workspace_id": row.workspace_id,
        "shared": bool(row.workspace_id),
        "mine": bool(user_id) and row.user_id == user_id,
        "daily_cap": limits.daily_cap,
        "min_gap_minutes": int(limits.gap.total_seconds() // 60),
        "posting_hours": list(limits.hours),
        "timezone": limits.tz,
        "posts_last_24h": used,
        "token_expires_at": aware(row.token_expires_at).isoformat() if row.token_expires_at else None,
        "last_error": row.last_error,
        "connected_at": aware(row.connected_at).isoformat() if row.connected_at else None,
    }


# --------------------------------------------------------------------------- #
# Connect
# --------------------------------------------------------------------------- #
def start_connect(session: Any, user_id: str, provider: str, *, workspace_id: str | None = None) -> dict:
    oauth.require_configured(provider)
    ws = check_workspace(session, user_id, workspace_id)
    session.execute(delete(MultipostOAuthState).where(MultipostOAuthState.expires_at < _now()))
    state = oauth.new_state()
    verifier = oauth.new_code_verifier() if provider in oauth.PKCE_PROVIDERS else ""
    session.add(MultipostOAuthState(
        state_hash=oauth.state_hash(state), user_id=user_id, provider=provider, workspace_id=ws,
        code_verifier_enc=crypto_tokens.encrypt(verifier) if verifier else None,
        expires_at=_now() + STATE_TTL,
    ))
    return {"provider": provider, "authorize_url": oauth.authorize_url(provider, state, verifier=verifier)}


@dataclass(frozen=True)
class ClaimedState:
    """A consumed OAuth state (plain values; the row is already deleted)."""

    provider: str
    workspace_id: str | None
    verifier: str


def claim_state(session: Any, user_id: str, state: str) -> ClaimedState:
    """Consume the single-use state bound to ``user_id``.

    The router commits this in its own transaction before the code exchange, so a
    failed exchange can never leave the state usable a second time.
    """
    row = session.get(MultipostOAuthState, oauth.state_hash(state))
    if row is None or row.user_id != user_id:
        raise oauth.ConnectError("this connect link is invalid or was already used; start again")
    expired = aware(row.expires_at) < _now()
    claimed = ClaimedState(
        provider=row.provider, workspace_id=row.workspace_id,
        verifier=crypto_tokens.decrypt(row.code_verifier_enc) if row.code_verifier_enc else "",
    )
    session.delete(row)
    session.flush()
    if expired:
        raise oauth.ConnectError("this connect link expired; start again")
    return claimed


def store_connection(session: Any, user_id: str, claimed: ClaimedState, grant: oauth.Grant,
                     identity: oauth.Identity) -> dict:
    """Create or refresh the account row for an exchanged grant."""
    row = session.execute(select(MultipostAccount).where(
        MultipostAccount.user_id == user_id, MultipostAccount.provider == claimed.provider,
        MultipostAccount.external_account_id == identity.external_account_id,
    )).scalar_one_or_none()
    if row is None:
        count = len(session.execute(select(MultipostAccount.id).where(MultipostAccount.user_id == user_id)).all())
        if count >= MAX_ACCOUNTS_PER_OWNER:
            raise oauth.ConnectError(f"you can connect up to {MAX_ACCOUNTS_PER_OWNER} accounts", status_code=409)
        row = MultipostAccount(user_id=user_id, provider=claimed.provider,
                               external_account_id=identity.external_account_id, access_token_enc="")
        session.add(row)
    _apply_grant(row, grant, keep_refresh=False)
    row.handle = identity.handle or row.handle
    row.display_name = identity.display_name or row.display_name
    row.avatar_url = identity.avatar_url or row.avatar_url
    if claimed.workspace_id and check_workspace(session, user_id, claimed.workspace_id):
        row.workspace_id = claimed.workspace_id
    row.status = ACCOUNT_CONNECTED
    row.last_error = ""
    session.flush()
    return public(row, user_id=user_id, session=session)


def finish_connect(session: Any, user_id: str, code: str, state: str, *, transport: Transport) -> dict:
    """Validate the single-use state, exchange the code and store (or refresh) the account.

    One-session convenience (tests, scripts). The HTTP route runs the three steps
    in separate transactions so no DB connection is held during the exchange.
    """
    claimed = claim_state(session, user_id, state)
    grant, identity = oauth.exchange(claimed.provider, code, verifier=claimed.verifier, transport=transport)
    return store_connection(session, user_id, claimed, grant, identity)


def _apply_grant(row: MultipostAccount, grant: oauth.Grant, *, keep_refresh: bool) -> None:
    row.access_token_enc = crypto_tokens.encrypt(grant.access_token)
    if grant.refresh_token:
        row.refresh_token_enc = crypto_tokens.encrypt(grant.refresh_token)
    elif not keep_refresh:
        row.refresh_token_enc = None
    row.token_expires_at = grant.expires_at
    if grant.refresh_expires_at:
        row.refresh_expires_at = grant.refresh_expires_at
    if grant.scopes:
        row.scopes = grant.scopes
    row.last_refreshed_at = _now()


# --------------------------------------------------------------------------- #
# Settings / disconnect
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AccountUpdate:
    daily_cap: int | None = None
    min_gap_minutes: int | None = None
    posting_hours: list[int] | None = None
    timezone: str | None = None
    paused: bool | None = None


def update(session: Any, user_id: str, account_id: str, change: AccountUpdate) -> dict:
    row = get_for(session, user_id, account_id, manage=True)
    pol = settings.policy(row.provider)
    if change.daily_cap is not None:
        if not 1 <= change.daily_cap <= pol.platform_daily_cap:
            raise oauth.ConnectError(f"{pol.label} allows 1 to {pol.platform_daily_cap} posts a day per account")
        row.daily_cap = int(change.daily_cap)
    if change.min_gap_minutes is not None:
        if change.min_gap_minutes < pol.min_gap_floor_minutes:
            raise oauth.ConnectError(f"leave at least {pol.min_gap_floor_minutes} minutes between posts")
        row.min_gap_minutes = int(change.min_gap_minutes)
    if change.posting_hours is not None:
        hours = sorted({int(h) for h in change.posting_hours})
        if any(h < 0 or h > 23 for h in hours):
            raise oauth.ConnectError("posting hours must be between 0 and 23")
        row.posting_hours = hours
    if change.timezone is not None:
        if pacing._tz_name(change.timezone) != change.timezone:  # noqa: SLF001 - same package
            raise oauth.ConnectError("unknown time zone")
        row.timezone = change.timezone
    if change.paused is not None:
        if change.paused:
            row.status = ACCOUNT_PAUSED
        elif row.status == ACCOUNT_PAUSED:
            row.status = ACCOUNT_CONNECTED
    session.flush()
    return public(row, user_id=user_id, session=session)


def disconnect(session: Any, user_id: str, account_id: str) -> int:
    """Remove the account and cancel its posts that have not gone out. Returns canceled count."""
    row = get_for(session, user_id, account_id, manage=True)
    pending = session.execute(select(MultipostPost).where(
        MultipostPost.account_id == row.id, MultipostPost.status.in_(list(OPEN_POST_STATUSES)),
    )).scalars().all()
    for post in pending:
        post.status = POST_CANCELED
        post.error = "account disconnected"
    # Finished posts keep their history; the account row is replaced by a tombstone-free delete
    # only when nothing references it.
    referenced = session.execute(select(MultipostPost.id).where(MultipostPost.account_id == row.id)).first()
    if referenced:
        row.status = ACCOUNT_REAUTH
        row.access_token_enc = crypto_tokens.encrypt("revoked")
        row.refresh_token_enc = None
        row.token_expires_at = _now()
        row.last_error = "disconnected"
        row.external_account_id = f"disconnected:{row.id}:{row.external_account_id}"[:200]
    else:
        session.delete(row)
    session.flush()
    return len(pending)


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def needs_refresh(row: MultipostAccount, now: datetime | None = None) -> bool:
    expires = aware(row.token_expires_at)
    if expires is None:
        return False
    return expires - (now or _now()) <= _REFRESH_LEAD.get(row.provider, timedelta(minutes=5))


def mark_reauth(row: MultipostAccount, message: str) -> None:
    row.status = ACCOUNT_REAUTH
    row.last_error = message[:500]


def valid_token(session: Any, row: MultipostAccount, *, transport: Transport, now: datetime | None = None) -> str:
    """Decrypt the access token, refreshing first when it is close to expiry.

    Raises :class:`oauth.ConnectError` (``reauth=True``) and flags the account
    when the platform will not renew it.
    """
    if row.status == ACCOUNT_REAUTH:
        raise oauth.ConnectError("this account needs to be reconnected", reauth=True, status_code=409)
    if needs_refresh(row, now):
        access = crypto_tokens.decrypt(row.access_token_enc)
        refresh_token = crypto_tokens.decrypt(row.refresh_token_enc) if row.refresh_token_enc else ""
        if row.provider == INSTAGRAM:
            refresh_token = ""
        try:
            grant = oauth.refresh(row.provider, access_token=access, refresh_token=refresh_token,
                                  transport=transport)
        except oauth.ConnectError as exc:
            expired = aware(row.token_expires_at) is not None and aware(row.token_expires_at) <= (now or _now())
            if exc.reauth and expired:
                mark_reauth(row, str(exc))
                session.flush()
                raise
            if expired:
                raise
            # Still valid for a while: use it and try renewing on the next pass.
            row.last_error = str(exc)[:500]
            return access
        _apply_grant(row, grant, keep_refresh=True)
        row.last_error = ""
        session.flush()
        return grant.access_token
    return crypto_tokens.decrypt(row.access_token_enc)


def refresh_expiring(session: Any, *, transport: Transport, limit: int = 100) -> int:
    """Renew tokens nearing expiry (beat sweep). Returns how many were renewed."""
    now = _now()
    horizon = now + timedelta(days=7)
    rows = session.execute(select(MultipostAccount).where(
        MultipostAccount.status != ACCOUNT_REAUTH,
        MultipostAccount.token_expires_at.is_not(None),
        MultipostAccount.token_expires_at <= horizon,
    ).limit(limit)).scalars().all()
    renewed = 0
    for row in rows:
        if not needs_refresh(row, now):
            continue
        try:
            before = row.access_token_enc
            valid_token(session, row, transport=transport, now=now)
            renewed += int(row.access_token_enc != before)
        except oauth.ConnectError:
            continue
    return renewed
