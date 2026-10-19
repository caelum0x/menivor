"""Stable public SDK error types."""

from typing import Any


class ReelForgeApiError(Exception):
    """Raised for any non-2xx ReelForge response."""

    def __init__(
        self,
        status: int,
        message: str,
        body: Any = None,
        correlation_id: str = "",
    ) -> None:
        visible_message = (
            f"{message} (correlation {correlation_id})"
            if correlation_id and correlation_id not in message
            else message
        )
        super().__init__(f"ReelForge API error {status}: {visible_message}")
        self.status = status
        self.message = message
        self.body = body
        self.correlation_id = correlation_id
