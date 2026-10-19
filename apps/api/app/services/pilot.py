"""Compatibility alias for :mod:`app.core.capabilities.service`."""

import sys

from app.core.capabilities import service as _implementation

sys.modules[__name__] = _implementation
