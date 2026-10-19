"""Native platform-publish connector contracts + HTTP transport seam.

Where the existing ``services/upload_post`` path posts through a third-party
aggregator, these connectors talk to the **native platform APIs directly**
(YouTube Data API v3, TikTok Content Posting API, Instagram Graph API) using the
OAuth access token the ``connections`` domain already stores (Fernet-encrypted,
auto-refreshed by ``oauth_connect.refresh_if_needed``).

The only thing that touches the network is the injectable :class:`Transport`
(default: ``requests``). Tests pass a fake transport and assert the exact request
shapes — that is the network boundary, not a stub of connector logic. Everything
else (endpoint choice, payload assembly, response parsing, error mapping) is real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class PublishError(RuntimeError):
    """A native publish failed (bad token, API rejection, unresolved output)."""

    def __init__(self, platform: str, message: str, *, retryable: bool = False) -> None:
        self.platform = platform
        self.retryable = retryable
        super().__init__(f"[{platform}] {message}")


@dataclass(frozen=True)
class PublishRequest:
    """Everything a connector needs to post one rendered reel.

    ``video_url`` is a short-lived public URL to the rendered MP4 (a presigned R2
    GET) — the API-hosted-upload path most platforms prefer. ``video_path`` is an
    optional local file for byte-upload (YouTube resumable). ``access_token`` is
    the decrypted, valid OAuth token; ``external_account_id`` the platform user/
    channel/ig-user id captured at connect time.
    """

    platform: str
    access_token: str
    video_url: str = ""
    video_path: str = ""
    title: str = ""
    description: str = ""
    caption: str = ""
    hashtags: tuple[str, ...] = ()
    privacy: str = "public"
    external_account_id: str = ""
    extra: dict = field(default_factory=dict)

    def caption_with_tags(self) -> str:
        """Caption + hashtags joined the way TikTok/IG expect (space-separated)."""
        tags = " ".join(t if t.startswith("#") else f"#{t}" for t in self.hashtags if t)
        base = (self.caption or self.title or "").strip()
        return f"{base} {tags}".strip() if tags else base


@dataclass(frozen=True)
class PublishResult:
    """The outcome of a native publish."""

    platform: str
    status: str            # "published" | "processing" | "failed"
    external_id: str = ""  # platform video/post/publish id
    url: str = ""          # canonical post URL when known
    raw: dict = field(default_factory=dict)


@runtime_checkable
class HttpResponse(Protocol):
    status_code: int
    headers: Any

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...


@runtime_checkable
class Transport(Protocol):
    """The single network seam every connector calls."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json: Any | None = None,
        data: Any | None = None,
    ) -> HttpResponse: ...


class RequestsTransport:
    """Default :class:`Transport` backed by ``requests`` (lazy import)."""

    def __init__(self, timeout_s: float = 120.0) -> None:
        self._timeout = timeout_s

    def request(
        self, method, url, *, headers=None, params=None, json=None, data=None
    ) -> HttpResponse:
        import requests

        return requests.request(
            method, url, headers=headers, params=params, json=json, data=data,
            timeout=self._timeout,
        )


@runtime_checkable
class PublishConnector(Protocol):
    """Publishes one :class:`PublishRequest` to a specific platform."""

    platform: str

    def publish(self, req: PublishRequest, *, transport: Transport) -> PublishResult: ...


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, PublishConnector] = {}


def register_connector(connector: PublishConnector) -> None:
    _REGISTRY[connector.platform] = connector


def get_connector(platform: str) -> PublishConnector | None:
    return _REGISTRY.get(str(platform or "").strip().lower())


def available_platforms() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def _ok(resp: HttpResponse) -> bool:
    return 200 <= int(getattr(resp, "status_code", 0)) < 300


def _safe_json(resp: HttpResponse) -> dict:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {"data": body}
    except Exception:
        return {}
