"""Shared shapes for the competitor ad sources (official APIs only, never scraping)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class SourceError(Exception):
    """A source call failed; ``message`` is safe to show (never carries a token)."""

    def __init__(self, source: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.source = source
        self.message = message
        self.status_code = status_code


class SourceNotConnected(SourceError):
    """The owner has not set this source's keys yet (``message`` says what to do)."""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(source, message, status_code=409)


@dataclass(frozen=True)
class TrackedAd:
    source: str
    external_id: str
    advertiser: str = ""
    body: str = ""
    title: str = ""
    page_url: str = ""
    media_url: str = ""
    thumbnail_url: str = ""
    platforms: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.stopped_at is None


def parse_time(value: Any) -> datetime | None:
    """ISO-8601 / ``YYYY-MM-DD`` / unix seconds -> aware UTC datetime (None when absent or bad)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():  # TikTok's YYYYMMDD
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    elif text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def first_text(value: Any, limit: int) -> str:
    if isinstance(value, (list, tuple)):
        value = next((v for v in value if str(v or "").strip()), "")
    return " ".join(str(value or "").split())[:limit]


def https_only(url: Any) -> str:
    text = str(url or "").strip()
    return text[:2000] if text.startswith("https://") else ""


__all__ = ["SourceError", "SourceNotConnected", "TrackedAd", "first_text", "https_only", "parse_time"]
