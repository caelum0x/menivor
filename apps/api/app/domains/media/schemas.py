"""Media-domain public DTO compatibility exports."""

from app.models.schema import (
    PresignRequest,
    PresignResponse,
    RegisterUploadRequest,
    RegisterUploadResponse,
)

__all__ = [
    "PresignRequest",
    "PresignResponse",
    "RegisterUploadRequest",
    "RegisterUploadResponse",
]
