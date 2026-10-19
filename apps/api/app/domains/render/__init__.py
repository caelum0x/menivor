"""Async-GPU render HTTP domain (start/status/advance a metered render job)."""

from __future__ import annotations

from .router import router

__all__ = ["router"]
