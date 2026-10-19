"""Direct-Publish publisher seam (upload a rendered reel to a social platform).

This is the thin, provider-agnostic boundary that takes a *decrypted* OAuth
access token (see :mod:`app.services.oauth_connect` /
:mod:`app.services.crypto_tokens`) plus a rendered video URL and hands them to a
provider upload client. It is deliberately a **seam**, not a live integration:
the actual HTTP upload lives behind an injectable :class:`VideoUploadClient` so
the prod-critical path never makes an unexpected network call and tests inject a
mock. A real client is dropped in later when live credentials exist.

Security / ownership: a publisher only ever receives an already-decrypted token
for the *resolved caller* — token decryption and per-user account resolution
happen upstream in the OAuth service, so this layer never sees an encrypted blob
or another creator's credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.models.db.repositories import _normalize_provider


class PublishError(Exception):
    """Raised when a reel cannot be published (bad input or upload failure)."""


@dataclass(frozen=True)
class PublishResult:
    """The outcome of a successful publish.

    Immutable (frozen): ``raw`` holds the provider's untouched response so callers
    can record provenance without this layer needing to model every provider.
    """

    provider: str
    external_post_id: str
    url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VideoUploadClient(Protocol):
    """The network seam: upload a video for a provider on behalf of a token.

    Implementations perform the real provider upload; tests supply a mock. Returns
    a raw provider response dict (``id`` / ``url`` are read into
    :class:`PublishResult` when present).
    """

    def upload(
        self,
        provider: str,
        access_token: str,
        video_url: str,
        *,
        caption: str = "",
        **options: Any,
    ) -> dict[str, Any]:
        """Upload ``video_url`` to ``provider`` using ``access_token``."""
        ...


class BasePublisher:
    """Thin base publisher: validate inputs, delegate the upload to a client.

    Subclasses set :attr:`provider`. Construction takes the injectable
    :class:`VideoUploadClient` (no default network client, by design). Concrete
    per-provider subclasses stay tiny — the only provider-specific piece today is
    the ``provider`` token; provider-specific request shaping lives in the client.
    """

    provider: str = ""

    def __init__(self, client: VideoUploadClient) -> None:
        if client is None:
            raise PublishError("a VideoUploadClient must be provided")
        self._client = client

    def publish(
        self,
        *,
        access_token: str,
        video_url: str,
        caption: str = "",
        **options: Any,
    ) -> PublishResult:
        """Publish a rendered reel; return a :class:`PublishResult`.

        Validates that a decrypted ``access_token`` and a ``video_url`` are both
        present (raising :class:`PublishError` otherwise — an empty token must
        never reach a provider), delegates to the injected upload client, and
        normalizes the raw response into a :class:`PublishResult`.
        """
        provider = _normalize_provider(self.provider)
        if not (access_token or "").strip():
            raise PublishError("access_token must be a non-empty decrypted token")
        if not (video_url or "").strip():
            raise PublishError("video_url must be a non-empty string")

        raw = self._client.upload(
            provider, access_token, video_url, caption=caption, **options
        )
        raw = dict(raw or {})
        return PublishResult(
            provider=provider,
            external_post_id=str(raw.get("id", "") or ""),
            url=str(raw.get("url", "") or ""),
            raw=raw,
        )


__all__ = [
    "PublishError",
    "PublishResult",
    "VideoUploadClient",
    "BasePublisher",
]
