"""Compatibility alias for :mod:`app.domains.broll.providers.base`."""

import sys

from app.domains.broll.providers import base as _implementation

sys.modules[__name__] = _implementation
