"""Ad-account connections: signed OAuth state + encrypted token storage.

The advertiser's platform token is stored in the existing BYOK table
(``provider_keys``) as ``provider_key='meta_ads'|'tiktok_ads'``,
``scope='ads'`` — encrypted with the same Fernet scheme as every OAuth token,
never returned. The selected ad account / page-or-identity / currency are
non-secret and kept in the row's ``label`` as ``key=value`` pairs so the choice
survives without a schema change. Revoking the key from the BYOK screen also
disconnects ads.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.domains.ads.config import PlatformConfig
from app.domains.ads.platforms import AccountRef, AdsApiError, TokenGrant
from app.models.db.marketplace import ProviderKey

SCOPE = "ads"
STATE_TTL_S = 600
_PROVIDER_KEYS = {"meta": "meta_ads", "tiktok": "tiktok_ads"}
_LABEL_PREFIX = {"meta": "Meta ads", "tiktok": "TikTok ads"}
_LABEL_RE = re.compile(r"(acct|ident|cur)=([A-Za-z0-9_\-]+)")


class ConnectionError_(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class Connection:
    platform: str
    key_id: str
    token: str
    account: AccountRef | None
    connected_at: datetime | None
    token_hint: str

    def public(self) -> dict:
        return {
            "platform": self.platform,
            "connected": True,
            "account_id": self.account.account_id if self.account else "",
            "identity_id": self.account.identity_id if self.account else "",
            "currency": self.account.currency if self.account else "",
            "ready": bool(self.account and self.account.account_id and self.account.identity_id),
            "token_hint": self.token_hint,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
        }


# --------------------------------------------------------------------- state
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_state(cfg: PlatformConfig, user_id: str, *, now: float | None = None) -> str:
    payload = _b64(json.dumps({"u": user_id, "p": cfg.platform, "e": int((now or time.time()) + STATE_TTL_S)}).encode())
    mac = hmac.new(cfg.app_secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64(mac)}"


def verify_state(cfg: PlatformConfig, state: str, user_id: str, *, now: float | None = None) -> None:
    """Raise unless ``state`` was minted for this user + platform and is fresh."""
    try:
        payload, mac = (state or "").split(".", 1)
        expected = hmac.new(cfg.app_secret.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(mac)):
            raise ValueError("bad mac")
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ConnectionError_(400, "The connect link is invalid. Start the connection again.") from exc
    if data.get("u") != user_id or data.get("p") != cfg.platform:
        raise ConnectionError_(400, "The connect link belongs to a different account.")
    if int(data.get("e") or 0) < int(now or time.time()):
        raise ConnectionError_(400, "The connect link expired. Start the connection again.")


# ---------------------------------------------------------------- persistence
def _crypto() -> Any:
    from app.services import crypto_tokens

    return crypto_tokens


def _hint(token: str) -> str:
    return f"{token[:4]}…{token[-2:]}" if len(token) > 8 else "…"


def build_label(platform: str, account: AccountRef | None) -> str:
    label = _LABEL_PREFIX[platform]
    if account and account.account_id:
        label += f" acct={account.account_id}"
        if account.identity_id:
            label += f" ident={account.identity_id}"
        label += f" cur={account.currency or 'USD'}"
    return label[:120]


def parse_label(label: str) -> AccountRef | None:
    fields = dict(_LABEL_RE.findall(label or ""))
    if not fields.get("acct"):
        return None
    return AccountRef(account_id=fields["acct"], identity_id=fields.get("ident", ""), currency=fields.get("cur", "USD"))


def _active_row(session: Any, user_id: str, platform: str) -> ProviderKey | None:
    stmt = (
        select(ProviderKey)
        .where(ProviderKey.user_id == user_id, ProviderKey.provider_key == _PROVIDER_KEYS[platform],
               ProviderKey.status == "active")
        .order_by(ProviderKey.created_at.desc())
    )
    return session.execute(stmt).scalars().first()


def store_grant(session: Any, user_id: str, platform: str, grant: TokenGrant) -> ProviderKey:
    """Replace any existing connection for the platform with the new token."""
    crypto = _crypto()
    if not crypto.is_configured():
        raise ConnectionError_(503, "Token encryption is not configured on this server.")
    previous = _active_row(session, user_id, platform)
    if previous is not None:
        previous.status = "revoked"
        previous.updated_at = datetime.now(timezone.utc)
    account = None
    if len(grant.account_ids) == 1 and platform == "tiktok":
        account = AccountRef(account_id=grant.account_ids[0])
    row = ProviderKey(
        user_id=user_id, provider_key=_PROVIDER_KEYS[platform], scope=SCOPE, label=build_label(platform, account),
        key_prefix=_hint(grant.access_token), encrypted_secret=crypto.encrypt(grant.access_token), status="active",
    )
    session.add(row)
    session.flush()
    return row


def load(session: Any, user_id: str, platform: str) -> Connection | None:
    row = _active_row(session, user_id, platform)
    if row is None:
        return None
    try:
        token = _crypto().decrypt(row.encrypted_secret)
    except Exception as exc:  # tampered blob or rotated key
        raise ConnectionError_(409, "The stored ad-account token can no longer be read. Reconnect the account.") from exc
    return Connection(platform=platform, key_id=row.id, token=token, account=parse_label(row.label),
                      connected_at=row.created_at, token_hint=row.key_prefix or "")


def require(session: Any, user_id: str, platform: str) -> Connection:
    conn = load(session, user_id, platform)
    if conn is None:
        raise ConnectionError_(409, f"Connect a {_LABEL_PREFIX[platform].split()[0]} ad account first.")
    if conn.account is None or not conn.account.account_id:
        raise ConnectionError_(409, "Choose which ad account to use first.")
    if not conn.account.identity_id:
        what = "Facebook Page" if platform == "meta" else "TikTok ad identity"
        raise ConnectionError_(409, f"Choose a {what} for this ad account first.")
    return conn


def select_account(session: Any, user_id: str, platform: str, account: AccountRef) -> ProviderKey:
    row = _active_row(session, user_id, platform)
    if row is None:
        raise ConnectionError_(409, "Connect the ad account first.")
    row.label = build_label(platform, account)
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row


def disconnect(session: Any, user_id: str, platform: str) -> bool:
    row = _active_row(session, user_id, platform)
    if row is None:
        return False
    row.status = "revoked"
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return True


def is_token_error(exc: AdsApiError) -> bool:
    return exc.status_code == 401


__all__ = [
    "Connection", "ConnectionError_", "build_label", "disconnect", "load", "parse_label", "require",
    "select_account", "sign_state", "store_grant", "verify_state",
]
