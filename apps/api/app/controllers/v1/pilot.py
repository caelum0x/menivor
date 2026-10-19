"""Compatibility alias for :mod:`app.core.capabilities.router`."""

import sys

from app.core.capabilities import router as _implementation

sys.modules[__name__] = _implementation
