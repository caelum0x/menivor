"""Shared contracts for the multi-account platform clients.

Every network call goes through the injectable :class:`Transport` (the same
shape native publishing uses). Tests pass a fake transport and assert the exact
request shapes; nothing else is faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HttpResponse(Protocol):
    status_code: int
    headers: Any

    def json(self) -> Any: ...


@runtime_checkable
class Transport(Protocol):
    """The single network seam every client calls."""

    def request(self, method: str, url: str, *, headers: dict | None = None, params: dict | None = None,
                json: Any | None = None, data: Any | None = None) -> HttpResponse: ...


class RequestsTransport:
    """Default :class:`Transport` backed by ``requests`` (lazy import)."""

    def __init__(self, timeout_s: float = 120.0) -> None:
        self._timeout = timeout_s

    def request(self, method, url, *, headers=None, params=None, json=None, data=None) -> HttpResponse:
        import requests

        return requests.request(method, url, headers=headers, params=params, json=json, data=data,
                                timeout=self._timeout)

__all__ = [
    "AuthError",
    "ClientError",
    "HttpResponse",
    "PostSpec",
    "PublishOutcome",
    "RateLimited",
    "RequestsTransport",
    "Transport",
    "body_of",
    "is_ok",
    "require_platform_url",
]


class ClientError(RuntimeError):
    """A platform call failed. ``retryable`` marks transient (5xx / network) failures."""

    def __init__(self, provider: str, message: str, *, retryable: bool = False, code: str = "") -> None:
        self.provider = provider
        self.retryable = retryable
        self.code = code
        super().__init__(message)


class AuthError(ClientError):
    """The token was rejected or revoked: the account must be reconnected."""


class RateLimited(ClientError):
    """The platform refused because of its posting cap or API rate limit."""

    def __init__(self, provider: str, message: str, *, retry_after_s: int = 0, code: str = "") -> None:
        super().__init__(provider, message, retryable=True, code=code)
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class PostSpec:
    """What to post, already resolved to platform-neutral values.

    ``visibility`` is ``public`` | ``friends`` | ``private``. ``video_url`` is a
    short-lived public URL; ``video_path`` a local file for byte uploads.
    """

    video_url: str = ""
    video_path: str = ""
    title: str = ""
    caption: str = ""
    hashtags: tuple[str, ...] = ()
    visibility: str = "private"
    ai_generated: bool = True
    allow_comments: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    brand_content: bool = False
    brand_organic: bool = False
    tiktok_mode: str = "direct"
    extra: dict = field(default_factory=dict)

    def text(self, limit: int) -> str:
        tags = " ".join(t if t.startswith("#") else f"#{t}" for t in self.hashtags if t)
        base = (self.caption or self.title or "").strip()
        joined = f"{base} {tags}".strip() if tags else base
        return joined[:limit]


@dataclass(frozen=True)
class PublishOutcome:
    """``status``: ``published`` | ``processing``. ``ref`` is the handle to poll."""

    status: str
    ref: str = ""
    external_id: str = ""
    url: str = ""
    provider_status: str = ""
    raw: dict = field(default_factory=dict)


def require_platform_url(provider: str, url: str, host_suffixes: tuple[str, ...]) -> str:
    """Refuse an upload URL a platform handed back unless it is HTTPS on that platform's hosts.

    The URL comes from a response body/header, so it is checked before any video
    bytes or bearer tokens are sent to it (no SSRF, no token leak to a stray host).
    """
    from urllib.parse import urlsplit

    parts = urlsplit(str(url or ""))
    host = (parts.hostname or "").lower().rstrip(".")
    ok_host = any(host == sfx or host.endswith(f".{sfx}") for sfx in host_suffixes)
    if parts.scheme != "https" or not ok_host or parts.username or parts.password:
        raise ClientError(provider, f"{provider} returned an upload address outside its own servers; not sending")
    return str(url)


def is_ok(resp: Any) -> bool:
    return 200 <= int(getattr(resp, "status_code", 0) or 0) < 300


def body_of(resp: Any) -> dict:
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 - non-JSON error pages
        return {}
    return body if isinstance(body, dict) else {"data": body}
