"""Railyard error type (Python mirror of ``vcglass/lib/railyard/errors.ts``).

A single typed error the caller can catch to fall back to its direct-provider
path. The ``code`` distinguishes recoverable-by-fallthrough cases (e.g.
``not_configured``) from hard-stop cases (``cap_exceeded`` — the per-key spend
cap is spent, so the caller must NOT retry on another transport).
"""

from __future__ import annotations

_MAX_DETAIL = 200


def truncate_detail(detail: object) -> str:
    """Bound an upstream error string so it never bloats a log line."""
    text = "" if detail is None else str(detail)
    return text[:_MAX_DETAIL]


class RailyardError(RuntimeError):
    """A Railyard-origin failure (never carries an API key in its message)."""

    def __init__(
        self,
        message: str,
        *,
        service: str,
        code: str,
        status: int | None = None,
        endpoint: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.code = code
        self.status = status
        self.endpoint = endpoint
        self.detail = detail
