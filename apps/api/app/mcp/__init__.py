"""ReelForge MCP server — agent-facing tools over the product domains.

Exposes a small, safe toolset (browse catalog, quote a generation, read wallet,
start a repurpose job, check a job) so Claude/agents can drive ReelForge — the
CTO plan §10.1 "ReelForge MCP server", inspired by short-video-maker. The tool
dispatch (:mod:`app.mcp.tools`) runs the domain services in-process and is
pure/testable; :mod:`app.mcp.server` is a thin stdio wrapper (guarded import of
the ``mcp`` SDK) that authenticates a caller to a user and dispatches.
"""

from .tools import TOOLS, dispatch

__all__ = ["TOOLS", "dispatch"]
