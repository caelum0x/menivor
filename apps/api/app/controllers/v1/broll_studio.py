"""Compatibility alias for :mod:`app.domains.broll.router`."""

import sys

from app.domains.broll import router as _implementation

sys.modules[__name__] = _implementation
