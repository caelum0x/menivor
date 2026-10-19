"""Ad Clone port (implemented by branch ``ad-clone-2026-10-06``).

Contract: ``clone_from_link(user_id, url, *, brand, space_id) -> dict`` starts an
ad clone of a TikTok / Meta ad link re-skinned for ``brand`` (the current brand
memory sections) and returns at least ``{"status": str, "job_id": str}``. It may
spend credits, so the agent calls it only after the user approves the action.
Raise :class:`PortUnavailable` with a plain reason when it cannot run.

Looked up at ``app.domains.adclone.agent_port:PORT`` (override with
``BRAND_AGENT_AD_CLONE_PORT=module:attr``).
"""

from __future__ import annotations

from typing import Any, Protocol

from .base import PortUnavailable, load_port

ENV = "BRAND_AGENT_AD_CLONE_PORT"
DEFAULT_PATH = "app.domains.adclone.agent_port:PORT"


class AdClonePort(Protocol):
    def clone_from_link(self, user_id: str, url: str, *, brand: dict[str, Any], space_id: str) -> dict[str, Any]: ...


class StubAdClone:
    def clone_from_link(self, user_id: str, url: str, *, brand: dict[str, Any], space_id: str) -> dict[str, Any]:
        raise PortUnavailable("Ad Clone is not installed on this server yet. The link is saved in Inspirations.")


def get_port() -> AdClonePort:
    return load_port(ENV, DEFAULT_PATH, StubAdClone())


__all__ = ["AdClonePort", "StubAdClone", "get_port"]
