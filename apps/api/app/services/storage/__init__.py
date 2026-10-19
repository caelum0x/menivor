"""ReelForge object storage package (Cloudflare R2, S3-compatible).

Exposes the R2 client surface from ``r2.py`` (INTEGRATION_CONTRACT.md §2.7).
Access ``storage.r2_client`` lazily — it is constructed on first use so
importing this package never requires boto3 or a populated ``config.r2``.
"""

from __future__ import annotations

from typing import Any

from app.platform.storage.r2 import (
    PresignResult,
    R2Client,
    get_r2_client,
)

__all__ = [
    "PresignResult",
    "R2Client",
    "get_r2_client",
    "r2_client",
]


def __getattr__(name: str) -> Any:
    """Lazily resolve the ``r2_client`` singleton on first attribute access."""
    if name == "r2_client":
        return get_r2_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
