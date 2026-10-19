"""Compatibility alias for :mod:`app.platform.storage.r2`.

New code imports the platform adapter. This module remains an exact module
alias until every legacy service caller has migrated, including integrations
that monkeypatch the adapter module during local development.
"""

from __future__ import annotations

import sys

from app.platform.storage import r2 as _canonical

sys.modules[__name__] = _canonical
