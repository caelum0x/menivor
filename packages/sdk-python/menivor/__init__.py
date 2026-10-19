"""Menivor Python SDK (``pip install menivor``).

The product was renamed from ReelForge. The implementation lives in
``reelforge_sdk`` (kept importable for existing code); this module exposes the
same client and models under Menivor names::

    from menivor import MenivorClient

    client = MenivorClient(api_key=os.environ["MENIVOR_API_KEY"])
"""

from reelforge_sdk import (
    BrollGenerateRequest,
    BrollGeneration,
    EditorExportRequest,
    Job,
    PresignRequest,
    ReelForgeApiError,
    ReelForgeClient,
    WEBHOOK_EVENT_TYPES,
    __version__,
)

MenivorClient = ReelForgeClient
MenivorApiError = ReelForgeApiError

__all__ = [
    "BrollGenerateRequest",
    "BrollGeneration",
    "EditorExportRequest",
    "Job",
    "MenivorApiError",
    "MenivorClient",
    "PresignRequest",
    "ReelForgeApiError",
    "ReelForgeClient",
    "WEBHOOK_EVENT_TYPES",
    "__version__",
]
