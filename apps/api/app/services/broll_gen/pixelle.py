"""Compatibility alias for the Pixelle B-roll provider."""

import sys

from app.domains.broll.providers import pixelle as _implementation

sys.modules[__name__] = _implementation
