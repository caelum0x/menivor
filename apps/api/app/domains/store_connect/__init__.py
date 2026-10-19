"""Phase 3 "Connect your store": App Store Connect + Google Play credential
storage and the first feature built on it (apps + current version + ratings,
feeding the App Store Audit tool).

See :mod:`.clients` (provider HTTP, injectable Transport), :mod:`.service`
(validate → encrypt → persist → read), and :mod:`.router` (the HTTP surface).
"""

from __future__ import annotations

from .router import router

__all__ = ["router"]
