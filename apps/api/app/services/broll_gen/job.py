"""Compatibility alias for :mod:`app.domains.broll.service`."""

import sys

from app.domains.broll import service as _implementation

sys.modules[__name__] = _implementation
