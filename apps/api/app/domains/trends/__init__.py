"""Trend ingestion + scoring domain (HTTP facade re-exports the router)."""

from __future__ import annotations

from .router import router

__all__ = ["router"]
