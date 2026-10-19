"""Ad accounts + Max port (implemented by branch ``integrations-2026-10-06``).

Contract (every method is owner-scoped by ``user_id``):

* ``list_connected_accounts(user_id) -> list[dict]`` - ``{"platform", "account_id", "name"}``
  per connected ad / social account; ``[]`` when none.
* ``top_performing_creatives(user_id, *, platform, limit) -> list[dict]`` - best ads,
  each ``{"id", "title", "url", "thumbnail_url", "metrics": {...}}``. Raise
  :class:`PortUnavailable` with a plain reason (not connected, token expired,
  missing permission) so the agent can show it with Retry.
* ``ask_campaign_question(user_id, question) -> dict`` - Max's answer.
* ``pull_report(user_id, **filters) -> dict`` and ``propose_optimization(user_id, **kw) -> dict``:
  read-only / proposal-only; approving an optimization stays in Max's own flow.

Looked up at ``app.domains.integrations.agent_port:PORT`` (override with
``BRAND_AGENT_INTEGRATIONS_PORT=module:attr``).
"""

from __future__ import annotations

from typing import Any, Protocol

from .base import PortUnavailable, load_port

ENV = "BRAND_AGENT_INTEGRATIONS_PORT"
DEFAULT_PATH = "app.domains.integrations.agent_port:PORT"
NOT_CONNECTED = ("Meta Ads is not connected on this server yet. Connect your ad account in Connectors, "
                 "then press Retry.")


class IntegrationsPort(Protocol):
    def list_connected_accounts(self, user_id: str) -> list[dict[str, Any]]: ...

    def top_performing_creatives(self, user_id: str, *, platform: str, limit: int) -> list[dict[str, Any]]: ...

    def ask_campaign_question(self, user_id: str, question: str) -> dict[str, Any]: ...

    def pull_report(self, user_id: str, **filters: Any) -> dict[str, Any]: ...

    def propose_optimization(self, user_id: str, **kwargs: Any) -> dict[str, Any]: ...


class StubIntegrations:
    def list_connected_accounts(self, user_id: str) -> list[dict[str, Any]]:
        return []

    def top_performing_creatives(self, user_id: str, *, platform: str, limit: int) -> list[dict[str, Any]]:
        raise PortUnavailable(NOT_CONNECTED)

    def ask_campaign_question(self, user_id: str, question: str) -> dict[str, Any]:
        raise PortUnavailable("Ads Q&A (Max) is not installed on this server yet.")

    def pull_report(self, user_id: str, **filters: Any) -> dict[str, Any]:
        raise PortUnavailable("Ad reports are not available until an ad account is connected.")

    def propose_optimization(self, user_id: str, **kwargs: Any) -> dict[str, Any]:
        raise PortUnavailable("Ad optimizations are not available until an ad account is connected.")


def get_port() -> IntegrationsPort:
    return load_port(ENV, DEFAULT_PATH, StubIntegrations())


__all__ = ["IntegrationsPort", "StubIntegrations", "get_port"]
