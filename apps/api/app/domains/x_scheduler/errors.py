"""Typed failures for the Buffer / Typefully bridge.

Messages are safe to show to the caller. They never include an API key.
"""

from __future__ import annotations


class SchedulerError(Exception):
    def __init__(self, status_code: int, message: str, *, code: str = "scheduler_error") -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.message = message
        self.code = code


class LimitReached(SchedulerError):
    """The provider refused because a free-plan quota is full. Nothing was posted."""

    def __init__(self, message: str) -> None:
        super().__init__(402, message, code="limit_reached")


def redact(text: str, secret: str) -> str:
    """Drop a credential if a provider error echoed it back."""
    raw = str(text or "")
    key = str(secret or "")
    if key and key in raw:
        raw = raw.replace(key, "[redacted]")
    return raw[:500]
