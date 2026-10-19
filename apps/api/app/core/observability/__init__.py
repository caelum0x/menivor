"""Request/worker observability primitives shared by product domains."""

from .correlation import (
    CORRELATION_HEADER,
    correlation_middleware,
    request_correlation_id,
)

__all__ = [
    "CORRELATION_HEADER",
    "correlation_middleware",
    "request_correlation_id",
]
