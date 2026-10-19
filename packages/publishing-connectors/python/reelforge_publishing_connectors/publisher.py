"""The ``Publisher`` contract every platform client implements (mirror of ``src/publisher.ts``).

Tokens are passed **in** per call (never read from env/store) — the API decrypts
Fernet tokens and injects them; connectors are stateless (the security seam). All
value types are frozen (immutable) dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PublishRequest:
    """Everything a connector needs to post one rendered reel."""

    video_url: str
    caption: str
    aspect: str
    duration_s: float
    # Platform where the source was watermarked, if any (cross-post guard).
    watermark_source: str | None = None


@dataclass(frozen=True)
class PublishResult:
    platform: str
    post_id: str
    url: str


@dataclass(frozen=True)
class TokenRefresh:
    """Result of an OAuth refresh (mirror of the TS ``{ accessToken, expiresIn }``)."""

    access_token: str
    expires_in: int


@dataclass(frozen=True)
class ConnectorError:
    kind: str  # "auth" | "cap" | "watermark" | "rate" | "platform"
    message: str
    platform: str
    retryable: bool


@dataclass(frozen=True)
class AnalyticsSnapshot:
    """Read-only analytics snapshot normalized to the shared shape."""

    platform: str
    views: int
    watch_time_s: float
    retention_pct: float


@runtime_checkable
class Publisher(Protocol):
    """The stateless publish contract; tokens are injected per call."""

    platform: str

    def caps(self) -> dict: ...

    def schedule_supported(self) -> bool: ...

    def publish(self, req: PublishRequest, token: str) -> PublishResult: ...

    def refresh(self, refresh_token: str) -> TokenRefresh: ...

    def fetch_analytics(self, post_id: str, token: str) -> AnalyticsSnapshot: ...
