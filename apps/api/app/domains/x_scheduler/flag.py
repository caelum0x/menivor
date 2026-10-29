"""MCP switch for Buffer / Typefully tools. Off unless explicitly enabled.

Same on-switch as ``MENIVOR_MCP_PUBLISHING_TOOLS`` (PR #1): unset, blank, or
anything other than ``1`` / ``true`` / ``yes`` / ``on`` keeps the tools hidden.
This flag is separate so turning Buffer and Typefully on does not re-advertise
the closed native ``schedule_publish`` tool.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Optional

FLAG = "MENIVOR_MCP_SCHEDULER_TOOLS"
_ON = {"1", "true", "yes", "on"}


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = (env if env is not None else os.environ).get(FLAG) or ""
    return raw.strip().lower() in _ON
