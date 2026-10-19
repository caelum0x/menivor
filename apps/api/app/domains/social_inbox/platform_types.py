"""Normalized shapes every platform client returns, plus the shared error type.

Clients translate platform JSON into these frozen records so the sync/reply code
never touches a platform payload directly. The only network seam is the same
injectable :class:`~app.domains.publishing.connectors.base.Transport` the
publish connectors use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.domains.publishing.connectors.base import RequestsTransport, Transport, _ok, _safe_json

__all__ = [
    "FetchedMessage",
    "FetchedThread",
    "InboxPlatformError",
    "RequestsTransport",
    "Transport",
    "default_transport",
    "is_ok",
    "json_of",
    "parse_time",
    "status_of",
]

# Inbox calls are small JSON reads/writes; fail fast instead of the 120s publish timeout.
_INBOX_TIMEOUT_S = 20.0


def default_transport() -> Transport:
    return RequestsTransport(timeout_s=_INBOX_TIMEOUT_S)


def is_ok(resp: Any) -> bool:
    return _ok(resp)


def json_of(resp: Any) -> dict:
    return _safe_json(resp)


def status_of(resp: Any) -> int:
    try:
        return int(getattr(resp, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def parse_time(value: Any) -> datetime | None:
    """Parse the ISO-8601 variants platforms send (``Z``, ``+0000``) into aware UTC."""
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw.replace("Z", "+00:00")]
    if len(raw) >= 5 and raw[-5] in "+-" and raw[-4:].isdigit():
        candidates.append(f"{raw[:-2]}:{raw[-2:]}")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


class InboxPlatformError(RuntimeError):
    """A platform refused or failed an inbox call.

    ``permission`` marks an auth/scope refusal (the creator must reconnect);
    ``not_available`` marks something the platform will not do for this post
    (comments turned off, video removed); ``retryable`` marks a transient
    failure (5xx, quota, network).
    """

    def __init__(
        self,
        platform: str,
        message: str,
        *,
        permission: bool = False,
        not_available: bool = False,
        retryable: bool = False,
    ) -> None:
        self.platform = platform
        self.permission = permission
        self.not_available = not_available
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class FetchedMessage:
    external_id: str
    author_name: str
    author_id: str
    text: str
    at: datetime | None
    from_me: bool

    def to_record(self) -> dict:
        return {
            "id": self.external_id,
            "author": self.author_name,
            "author_id": self.author_id,
            "text": self.text,
            "at": self.at.isoformat() if self.at else None,
            "from_me": self.from_me,
        }


@dataclass(frozen=True)
class FetchedThread:
    kind: str                    # "comment" | "dm"
    external_thread_id: str      # top-level comment id / conversation id
    author_name: str
    author_id: str
    text: str                    # top-level comment text / latest inbound DM text
    permalink: str = ""
    like_count: int = 0
    messages: tuple[FetchedMessage, ...] = field(default_factory=tuple)

    @property
    def last_message_at(self) -> datetime | None:
        times = [m.at for m in self.messages if m.at]
        return max(times) if times else None

    @property
    def last_inbound_at(self) -> datetime | None:
        times = [m.at for m in self.messages if m.at and not m.from_me]
        return max(times) if times else None

    @property
    def last_from_me(self) -> bool:
        dated = [m for m in self.messages if m.at]
        if not dated:
            return False
        return max(dated, key=lambda m: m.at).from_me  # type: ignore[arg-type,return-value]
