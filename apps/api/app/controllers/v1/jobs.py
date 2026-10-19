"""Compatibility alias for :mod:`app.domains.reels.router`.

The public HTTP owner moved to the reels domain. Existing internal imports and
extensions keep resolving to the exact canonical module object until their
separate domain migrations are complete.
"""

from __future__ import annotations

import importlib
import sys

from app.domains.media.router import presign_upload, register_upload

_canonical = importlib.import_module("app.domains.reels.router")
_canonical.presign_upload = presign_upload
_canonical.register_upload = register_upload
sys.modules[__name__] = _canonical
