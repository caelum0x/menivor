"""OAuth for multi-account connect: authorize URL, code exchange + identity, refresh.

Pure functions over the injectable transport; persistence lives in
:mod:`.accounts`. Tokens leave this module only as return values.

* TikTok Login Kit v2 - access token ~24 h, refresh token ~365 days (rotates).
* Instagram API with Instagram Login - short-lived token exchanged for a 60-day
  long-lived token, refreshed with ``ig_refresh_token`` (no refresh token).
* Google OAuth for YouTube - offline access + PKCE; ``prompt=consent
  select_account`` so a creator can pick a different channel/Brand Account each
  time they connect.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

from . import settings
from .clients.base import Transport, body_of, is_ok
from .models import INSTAGRAM, PROVIDERS, TIKTOK, YOUTUBE

AUTHORIZE_URLS = {
    TIKTOK: "https://www.tiktok.com/v2/auth/authorize/",
    INSTAGRAM: "https://www.instagram.com/oauth/authorize",
    YOUTUBE: "https://accounts.google.com/o/oauth2/v2/auth",
}
TOKEN_URLS = {
    TIKTOK: "https://open.tiktokapis.com/v2/oauth/token/",
    INSTAGRAM: "https://api.instagram.com/oauth/access_token",
    YOUTUBE: "https://oauth2.googleapis.com/token",
}
SCOPES = {
    TIKTOK: "user.info.basic,video.publish,video.upload",
    INSTAGRAM: "instagram_business_basic,instagram_business_content_publish",
    YOUTUBE: "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
}
TIKTOK_USER_URL = "https://open.tiktokapis.com/v2/user/info/"
IG_LONG_LIVED_URL = "https://graph.instagram.com/access_token"
IG_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
IG_ME_URL = "https://graph.instagram.com/v21.0/me"
YT_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
PKCE_PROVIDERS = frozenset({YOUTUBE})


class ConnectError(RuntimeError):
    """A connect/refresh step failed. ``reauth`` means the account must be reconnected."""

    def __init__(self, message: str, *, status_code: int = 400, reauth: bool = False) -> None:
        self.status_code = status_code
        self.reauth = reauth
        super().__init__(message)


@dataclass(frozen=True)
class Identity:
    external_account_id: str
    handle: str = ""
    display_name: str = ""
    avatar_url: str = ""


@dataclass(frozen=True)
class Grant:
    """Tokens from an exchange/refresh (in memory only)."""

    access_token: str
    refresh_token: str = ""
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    scopes: str = ""


def new_state() -> str:
    return secrets.token_urlsafe(32)


def state_hash(state: str) -> str:
    return hashlib.sha256(str(state or "").encode("utf-8")).hexdigest()


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _expires(seconds: Any, now: datetime | None = None) -> datetime | None:
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return (now or datetime.now(timezone.utc)) + timedelta(seconds=value)


def require_configured(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ConnectError(f"unknown platform {provider!r}", status_code=404)
    missing = settings.missing_settings(provider)
    if missing:
        raise ConnectError(f"{provider} is not set up on this server yet (missing: {', '.join(missing)})",
                           status_code=503)


def authorize_url(provider: str, state: str, *, verifier: str = "") -> str:
    require_configured(provider)
    key_name = "client_key" if provider == TIKTOK else "client_id"
    params: dict[str, str] = {
        key_name: settings.client_id(provider),
        "redirect_uri": settings.redirect_uri(),
        "response_type": "code",
        "scope": SCOPES[provider],
        "state": state,
    }
    if provider == YOUTUBE:
        params.update({"access_type": "offline", "prompt": "consent select_account",
                       "include_granted_scopes": "true"})
    if provider == TIKTOK:
        # Always show TikTok's account picker so a second account can be added.
        params["disable_auto_auth"] = "1"
    if provider in PKCE_PROVIDERS:
        if not verifier:
            raise ConnectError("missing PKCE verifier", status_code=500)
        params["code_challenge"] = code_challenge(verifier)
        params["code_challenge_method"] = "S256"
    return f"{AUTHORIZE_URLS[provider]}?{urlencode(params, quote_via=quote)}"


def _token_body(resp: Any, provider: str, *, reauth: bool = False) -> dict:
    body = body_of(resp)
    if not is_ok(resp) or body.get("error") or not body.get("access_token"):
        detail = body.get("error_description") or body.get("error_message") or body.get("error") or \
            f"HTTP {getattr(resp, 'status_code', 0)}"
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
        raise ConnectError(f"{provider} would not issue a token: {detail}", status_code=400, reauth=reauth)
    return body


def exchange(provider: str, code: str, *, verifier: str = "", transport: Transport) -> tuple[Grant, Identity]:
    """Swap ``code`` for tokens and read which account was authorized."""
    require_configured(provider)
    if not str(code or "").strip():
        raise ConnectError("authorization code is required")
    if provider == TIKTOK:
        return _exchange_tiktok(code, transport)
    if provider == INSTAGRAM:
        return _exchange_instagram(code, transport)
    return _exchange_youtube(code, verifier, transport)


def _exchange_tiktok(code: str, transport: Transport) -> tuple[Grant, Identity]:
    body = _token_body(transport.request(
        "POST", TOKEN_URLS[TIKTOK],
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"client_key": settings.client_id(TIKTOK), "client_secret": settings.client_secret(TIKTOK),
              "code": code, "grant_type": "authorization_code", "redirect_uri": settings.redirect_uri()},
    ), "TikTok")
    grant = _tiktok_grant(body)
    me = transport.request("GET", TIKTOK_USER_URL, params={"fields": "open_id,avatar_url,display_name"},
                           headers={"Authorization": f"Bearer {grant.access_token}"})
    user = (body_of(me).get("data") or {}).get("user") or {} if is_ok(me) else {}
    open_id = str(user.get("open_id") or body.get("open_id") or "")
    if not open_id:
        raise ConnectError("TikTok did not say which account was connected", status_code=502)
    name = str(user.get("display_name") or "")
    # The @username needs an extra scope; creator_info returns it at first post.
    return grant, Identity(open_id, handle="", display_name=name, avatar_url=str(user.get("avatar_url") or ""))


def _tiktok_grant(body: dict) -> Grant:
    return Grant(
        access_token=str(body["access_token"]),
        refresh_token=str(body.get("refresh_token") or ""),
        expires_at=_expires(body.get("expires_in")),
        refresh_expires_at=_expires(body.get("refresh_expires_in")),
        scopes=str(body.get("scope") or SCOPES[TIKTOK]),
    )


def _exchange_instagram(code: str, transport: Transport) -> tuple[Grant, Identity]:
    short = _token_body(transport.request(
        "POST", TOKEN_URLS[INSTAGRAM],
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"client_id": settings.client_id(INSTAGRAM), "client_secret": settings.client_secret(INSTAGRAM),
              "grant_type": "authorization_code", "redirect_uri": settings.redirect_uri(),
              "code": str(code).split("#")[0]},
    ), "Instagram")
    long_body = _token_body(transport.request(
        "GET", IG_LONG_LIVED_URL,
        params={"grant_type": "ig_exchange_token", "client_secret": settings.client_secret(INSTAGRAM),
                "access_token": str(short["access_token"])},
    ), "Instagram")
    token = str(long_body["access_token"])
    me = transport.request("GET", IG_ME_URL,
                           params={"fields": "user_id,username,name,profile_picture_url", "access_token": token})
    me_body = body_of(me) if is_ok(me) else {}
    user_id = str(me_body.get("user_id") or short.get("user_id") or "")
    if not user_id:
        raise ConnectError("Instagram did not say which account was connected", status_code=502)
    perms = short.get("permissions")
    scopes = ",".join(perms) if isinstance(perms, list) else SCOPES[INSTAGRAM]
    grant = Grant(access_token=token, expires_at=_expires(long_body.get("expires_in")), scopes=scopes)
    handle = str(me_body.get("username") or "")
    return grant, Identity(user_id, handle=handle, display_name=str(me_body.get("name") or handle),
                           avatar_url=str(me_body.get("profile_picture_url") or ""))


def _exchange_youtube(code: str, verifier: str, transport: Transport) -> tuple[Grant, Identity]:
    body = _token_body(transport.request(
        "POST", TOKEN_URLS[YOUTUBE],
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"client_id": settings.client_id(YOUTUBE), "client_secret": settings.client_secret(YOUTUBE),
              "code": code, "grant_type": "authorization_code", "redirect_uri": settings.redirect_uri(),
              "code_verifier": verifier},
    ), "YouTube")
    grant = Grant(access_token=str(body["access_token"]), refresh_token=str(body.get("refresh_token") or ""),
                  expires_at=_expires(body.get("expires_in")), scopes=str(body.get("scope") or SCOPES[YOUTUBE]))
    resp = transport.request("GET", YT_CHANNELS_URL, params={"part": "snippet", "mine": "true"},
                             headers={"Authorization": f"Bearer {grant.access_token}"})
    items = body_of(resp).get("items") or [] if is_ok(resp) else []
    if not items:
        raise ConnectError("this Google account has no YouTube channel to post to", status_code=400)
    channel = items[0]
    snippet = channel.get("snippet") or {}
    thumbs = snippet.get("thumbnails") or {}
    avatar = str(((thumbs.get("default") or {}).get("url")) or "")
    return grant, Identity(str(channel.get("id") or ""), handle=str(snippet.get("customUrl") or ""),
                           display_name=str(snippet.get("title") or ""), avatar_url=avatar)


def refresh(provider: str, *, access_token: str, refresh_token: str, transport: Transport) -> Grant:
    """Renew an expiring token. Raises :class:`ConnectError` (``reauth=True``) when impossible."""
    if provider == INSTAGRAM:
        resp = transport.request("GET", IG_REFRESH_URL,
                                 params={"grant_type": "ig_refresh_token", "access_token": access_token})
        body = _token_body(resp, "Instagram", reauth=True)
        return Grant(access_token=str(body["access_token"]), expires_at=_expires(body.get("expires_in")))
    if not refresh_token:
        raise ConnectError(f"the {provider} connection expired; reconnect it", reauth=True)
    if provider == TIKTOK:
        body = _token_body(transport.request(
            "POST", TOKEN_URLS[TIKTOK],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"client_key": settings.client_id(TIKTOK), "client_secret": settings.client_secret(TIKTOK),
                  "grant_type": "refresh_token", "refresh_token": refresh_token},
        ), "TikTok", reauth=True)
        return _tiktok_grant(body)
    if provider == YOUTUBE:
        body = _token_body(transport.request(
            "POST", TOKEN_URLS[YOUTUBE],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"client_id": settings.client_id(YOUTUBE), "client_secret": settings.client_secret(YOUTUBE),
                  "grant_type": "refresh_token", "refresh_token": refresh_token},
        ), "YouTube", reauth=True)
        # Google keeps the same refresh token unless it sends a new one.
        return Grant(access_token=str(body["access_token"]),
                     refresh_token=str(body.get("refresh_token") or refresh_token),
                     expires_at=_expires(body.get("expires_in")), scopes=str(body.get("scope") or ""))
    raise ConnectError(f"unknown platform {provider!r}", status_code=404)
