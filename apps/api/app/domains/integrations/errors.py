"""The one user-facing error type of the Integrations domain."""

from __future__ import annotations


class IntegrationError(Exception):
    """``message`` is safe to show; ``status_code`` maps straight to the HTTP answer."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


__all__ = ["IntegrationError"]
