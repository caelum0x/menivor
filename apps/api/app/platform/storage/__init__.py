"""Canonical object-storage platform boundary."""

from __future__ import annotations

from typing import Any

from .r2 import PresignResult, R2Client, get_r2_client

__all__ = ["PresignResult", "R2Client", "get_r2_client", "r2_client"]


def __getattr__(name: str) -> Any:
    if name == "r2_client":
        return get_r2_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
