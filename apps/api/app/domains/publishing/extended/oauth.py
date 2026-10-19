"""OAuth 2.0 for the extended platforms: authorize URL, code exchange, refresh,
and the identity/target lookups each platform needs after connecting.

Pure functions over the injectable :class:`Transport`; persistence lives in
:mod:`.repository` / :mod:`.service`. Nothing here logs or returns a token
except as the explicit return value of an exchange.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

from .catalog import (
    FACEBOOK,
    LINKEDIN,
    PINTEREST,
    TARGET_BOARD,
    TARGET_ORGANIZATION,
    TARGET_PAGE,
    TARGET_SELF,
    THREADS,
    X,
    client_id,
    client_secret,
    pinterest_api_base,
    redirect_uri,
    spec_for,
)
from .connectors.base import Transport, error_text, is_ok, json_of
from .connectors.linkedin import headers as linkedin_headers


class ConnectError(RuntimeError):
    """A connect/refresh step failed. ``status_code`` maps to HTTP for the router."""

    def __init__(self, message: str, *, status_code: int = 400, reauth: bool = False) -> None:
        self.status_code = status_code
        self.reauth = reauth
        super().__init__(message)


@dataclass(frozen=True)
class Target:
    id: str
    name: str
    kind: str

    def to_record(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind}


@dataclass(frozen=True)
class ConnectedAccount:
    """What a successful exchange yields (tokens in memory only)."""

    access_token: str
    refresh_token: str = ""
    expires_at: datetime | None = None
    scopes: str = ""
    external_account_id: str = ""
    account_name: str = ""
    targets: tuple[Target, ...] = ()
    meta: dict = field(default_factory=dict)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def state_hash(state: str) -> str:
    return hashlib.sha256(str(state or "").encode("utf-8")).hexdigest()


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _expires(raw: Any) -> datetime | None:
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=seconds) if seconds > 0 else None


def _basic(platform: str) -> str:
    raw = f"{client_id(platform)}:{client_secret(platform)}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _require_config(platform: str) -> None:
    if not client_id(platform) or not client_secret(platform) or not redirect_uri(platform):
        raise ConnectError(f"{platform} connect is not set up on this server", status_code=503)


# --------------------------------------------------------------------------- #
# Authorize
# --------------------------------------------------------------------------- #
def authorize_url(platform: str, state: str, *, scopes: str = "", verifier: str = "") -> str:
    spec = spec_for(platform)
    if spec is None or not spec.uses_oauth:
        raise ConnectError(f"{platform} does not use OAuth", status_code=400)
    _require_config(spec.key)
    params: dict[str, str] = {
        "client_id": client_id(spec.key),
        "redirect_uri": redirect_uri(spec.key),
        "response_type": "code",
        "state": state,
        "scope": scopes or spec.scopes,
    }
    if spec.pkce:
        if not verifier:
            raise ConnectError("missing PKCE verifier", status_code=500)
        params["code_challenge"] = code_challenge(verifier)
        params["code_challenge_method"] = "S256"
    return f"{spec.authorize_url}?{urlencode(params, quote_via=quote)}"


# --------------------------------------------------------------------------- #
# Exchange (+ identity/targets)
# --------------------------------------------------------------------------- #
def exchange(platform: str, code: str, *, verifier: str = "", transport: Transport) -> ConnectedAccount:
    """Swap ``code`` for tokens and look up who/where the account can post."""
    spec = spec_for(platform)
    if spec is None or not spec.uses_oauth:
        raise ConnectError(f"{platform} does not use OAuth", status_code=400)
    if not str(code or "").strip():
        raise ConnectError("authorization code is required")
    _require_config(spec.key)
    handlers = {
        FACEBOOK: _exchange_facebook,
        LINKEDIN: _exchange_linkedin,
        X: _exchange_x,
        THREADS: _exchange_threads,
        PINTEREST: _exchange_pinterest,
    }
    return handlers[spec.key](code, verifier, transport)


def _token_or_raise(resp: Any, platform: str) -> dict:
    if not is_ok(resp):
        raise ConnectError(f"{platform} refused the connection: {error_text(resp)}")
    body = json_of(resp)
    if not str(body.get("access_token") or "").strip():
        raise ConnectError(f"{platform} returned no access token")
    return body


def _exchange_facebook(code: str, _verifier: str, transport: Transport) -> ConnectedAccount:
    spec = spec_for(FACEBOOK)
    short = _token_or_raise(transport.request("GET", spec.token_url, params={
        "client_id": client_id(FACEBOOK),
        "client_secret": client_secret(FACEBOOK),
        "redirect_uri": redirect_uri(FACEBOOK),
        "code": code,
    }), "Facebook")
    long = transport.request("GET", spec.token_url, params={
        "grant_type": "fb_exchange_token",
        "client_id": client_id(FACEBOOK),
        "client_secret": client_secret(FACEBOOK),
        "fb_exchange_token": short["access_token"],
    })
    body = json_of(long) if is_ok(long) and json_of(long).get("access_token") else short
    token = str(body["access_token"])
    me = transport.request("GET", "https://graph.facebook.com/v21.0/me",
                           params={"fields": "id,name", "access_token": token})
    me_body = json_of(me) if is_ok(me) else {}
    pages = facebook_pages(token, transport=transport)
    return ConnectedAccount(
        access_token=token,
        expires_at=_expires(body.get("expires_in")),
        scopes=spec.scopes,
        external_account_id=str(me_body.get("id") or ""),
        account_name=str(me_body.get("name") or ""),
        targets=tuple(Target(p["id"], p["name"], TARGET_PAGE) for p in pages),
    )


def facebook_pages(user_token: str, *, transport: Transport, with_tokens: bool = False) -> list[dict]:
    """Pages the user manages: ``[{"id","name"(, "access_token")}]``."""
    resp = transport.request("GET", "https://graph.facebook.com/v21.0/me/accounts",
                             params={"fields": "id,name,access_token", "limit": "100", "access_token": user_token})
    if not is_ok(resp):
        raise ConnectError(f"could not list your Facebook Pages: {error_text(resp)}", reauth=True)
    out: list[dict] = []
    for page in json_of(resp).get("data") or []:
        if not isinstance(page, dict) or not page.get("id"):
            continue
        row = {"id": str(page["id"]), "name": str(page.get("name") or "Page")}
        if with_tokens:
            row["access_token"] = str(page.get("access_token") or "")
        out.append(row)
    return out


def _exchange_linkedin(code: str, _verifier: str, transport: Transport) -> ConnectedAccount:
    spec = spec_for(LINKEDIN)
    body = _token_or_raise(transport.request(
        "POST", spec.token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(LINKEDIN),
            "client_id": client_id(LINKEDIN),
            "client_secret": client_secret(LINKEDIN),
        },
    ), "LinkedIn")
    token = str(body["access_token"])
    info = transport.request("GET", "https://api.linkedin.com/v2/userinfo",
                             headers={"Authorization": f"Bearer {token}"})
    if not is_ok(info):
        raise ConnectError(f"LinkedIn did not share your profile: {error_text(info)}")
    profile = json_of(info)
    member_id = str(profile.get("sub") or "")
    member_urn = f"urn:li:person:{member_id}" if member_id else ""
    name = str(profile.get("name") or "")
    scopes = str(body.get("scope") or spec.scopes)
    targets = [Target(member_urn, name or "Your profile", TARGET_SELF)] if member_urn else []
    if "w_organization_social" in scopes:
        targets.extend(linkedin_organizations(token, transport=transport))
    return ConnectedAccount(
        access_token=token,
        refresh_token=str(body.get("refresh_token") or ""),
        expires_at=_expires(body.get("expires_in")),
        scopes=scopes,
        external_account_id=member_id,
        account_name=name,
        targets=tuple(targets),
        meta={"member_urn": member_urn},
    )


def linkedin_organizations(token: str, *, transport: Transport, limit: int = 10) -> list[Target]:
    """Company pages the member administers (Community Management API only)."""
    resp = transport.request(
        "GET", "https://api.linkedin.com/rest/organizationAcls",
        headers=linkedin_headers(token, json_body=False),
        params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
    )
    if not is_ok(resp):
        return []
    out: list[Target] = []
    for element in (json_of(resp).get("elements") or [])[:limit]:
        urn = str((element or {}).get("organization") or "")
        if not urn.startswith("urn:li:organization:"):
            continue
        org_id = urn.rsplit(":", 1)[-1]
        name = f"Company page {org_id}"
        org = transport.request("GET", f"https://api.linkedin.com/rest/organizations/{org_id}",
                                headers=linkedin_headers(token, json_body=False))
        if is_ok(org):
            name = str(json_of(org).get("localizedName") or name)
        out.append(Target(urn, name, TARGET_ORGANIZATION))
    return out


def _exchange_x(code: str, verifier: str, transport: Transport) -> ConnectedAccount:
    spec = spec_for(X)
    if not verifier:
        raise ConnectError("the X connect session expired; start again")
    body = _token_or_raise(transport.request(
        "POST", spec.token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": _basic(X)},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(X),
            "code_verifier": verifier,
            "client_id": client_id(X),
        },
    ), "X")
    token = str(body["access_token"])
    me = transport.request("GET", "https://api.x.com/2/users/me", headers={"Authorization": f"Bearer {token}"})
    data = (json_of(me).get("data") or {}) if is_ok(me) else {}
    return ConnectedAccount(
        access_token=token,
        refresh_token=str(body.get("refresh_token") or ""),
        expires_at=_expires(body.get("expires_in")),
        scopes=str(body.get("scope") or spec.scopes),
        external_account_id=str(data.get("id") or ""),
        account_name=f"@{data['username']}" if data.get("username") else str(data.get("name") or ""),
    )


def _exchange_threads(code: str, _verifier: str, transport: Transport) -> ConnectedAccount:
    spec = spec_for(THREADS)
    short = _token_or_raise(transport.request(
        "POST", spec.token_url,
        data={
            "client_id": client_id(THREADS),
            "client_secret": client_secret(THREADS),
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(THREADS),
            "code": code,
        },
    ), "Threads")
    long = transport.request("GET", "https://graph.threads.net/access_token", params={
        "grant_type": "th_exchange_token",
        "client_secret": client_secret(THREADS),
        "access_token": short["access_token"],
    })
    body = json_of(long) if is_ok(long) and json_of(long).get("access_token") else short
    token = str(body["access_token"])
    me = transport.request("GET", "https://graph.threads.net/v1.0/me",
                           params={"fields": "id,username", "access_token": token})
    me_body = json_of(me) if is_ok(me) else {}
    return ConnectedAccount(
        access_token=token,
        expires_at=_expires(body.get("expires_in")),
        scopes=spec.scopes,
        external_account_id=str(me_body.get("id") or short.get("user_id") or ""),
        account_name=f"@{me_body['username']}" if me_body.get("username") else "",
        meta={"username": str(me_body.get("username") or "")},
    )


def _exchange_pinterest(code: str, _verifier: str, transport: Transport) -> ConnectedAccount:
    spec = spec_for(PINTEREST)
    body = _token_or_raise(transport.request(
        "POST", spec.token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": _basic(PINTEREST)},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(PINTEREST)},
    ), "Pinterest")
    token = str(body["access_token"])
    base = pinterest_api_base()
    me = transport.request("GET", f"{base}/v5/user_account", headers={"Authorization": f"Bearer {token}"})
    me_body = json_of(me) if is_ok(me) else {}
    return ConnectedAccount(
        access_token=token,
        refresh_token=str(body.get("refresh_token") or ""),
        expires_at=_expires(body.get("expires_in")),
        scopes=str(body.get("scope") or spec.scopes),
        external_account_id=str(me_body.get("username") or ""),
        account_name=str(me_body.get("username") or ""),
        targets=tuple(pinterest_boards(token, transport=transport)),
    )


def pinterest_boards(token: str, *, transport: Transport) -> list[Target]:
    resp = transport.request("GET", f"{pinterest_api_base()}/v5/boards",
                             headers={"Authorization": f"Bearer {token}"}, params={"page_size": "100"})
    if not is_ok(resp):
        return []
    return [
        Target(str(b["id"]), str(b.get("name") or "Board"), TARGET_BOARD)
        for b in (json_of(resp).get("items") or [])
        if isinstance(b, dict) and b.get("id")
    ]


# --------------------------------------------------------------------------- #
# Refresh
# --------------------------------------------------------------------------- #
def refresh(platform: str, *, access_token: str, refresh_token: str, transport: Transport) -> ConnectedAccount:
    """Refresh an expiring token. Raises :class:`ConnectError` (``reauth=True``) when impossible."""
    spec = spec_for(platform)
    if spec is None:
        raise ConnectError(f"unknown platform {platform!r}")
    if spec.key == THREADS:
        resp = transport.request("GET", "https://graph.threads.net/refresh_access_token",
                                 params={"grant_type": "th_refresh_token", "access_token": access_token})
    elif spec.key == X and refresh_token:
        resp = transport.request(
            "POST", spec.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": _basic(X)},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id(X)},
        )
    elif spec.key == PINTEREST and refresh_token:
        resp = transport.request(
            "POST", spec.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": _basic(PINTEREST)},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
    elif spec.key == LINKEDIN and refresh_token:
        resp = transport.request(
            "POST", spec.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token", "refresh_token": refresh_token,
                "client_id": client_id(LINKEDIN), "client_secret": client_secret(LINKEDIN),
            },
        )
    else:
        raise ConnectError(f"the {spec.label} connection expired; reconnect it", reauth=True)
    if not is_ok(resp):
        raise ConnectError(f"{spec.label} would not renew the connection: {error_text(resp)}", reauth=True)
    body = json_of(resp)
    token = str(body.get("access_token") or "")
    if not token:
        raise ConnectError(f"{spec.label} returned no renewed token", reauth=True)
    return ConnectedAccount(
        access_token=token,
        refresh_token=str(body.get("refresh_token") or refresh_token or ""),
        expires_at=_expires(body.get("expires_in")),
        scopes=str(body.get("scope") or ""),
    )
