"""Ingest error type (kept separate so fetchers/resolvers avoid import cycles)."""

from __future__ import annotations


class IngestError(Exception):
    """A user-presentable ingest failure carrying an HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


__all__ = ["IngestError"]
