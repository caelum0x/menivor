"""Contract the Brand Agent (branch ``brand-agent-2026-10-06``) consumes. Plain Python, no HTTP.

Connectors view::

    list_connected_accounts(user_id, *, workspace_id=None, brand_space_id=None) -> list[ConnectedAccount]

Inspirations view::

    top_performing_creatives(user_id, ad_account_id, *, period_days=7, limit=10,
                             workspace_id=None, brand_space_id=None) -> list[CreativePerformance]

Ads agent tools (same rules as the HTTP API; nothing executes without approval)::

    ask_campaign_question(user_id, question, *, workspace_id=None, brand_space_id=None, llm=None) -> dict
    pull_report(user_id, *, ad_account_id=None, period_days=7, workspace_id=None, brand_space_id=None) -> dict
    propose_optimization(user_id, *, ad_account_id=None, period_days=7, workspace_id=None) -> dict
    approve(user_id, item_id, *, workspace_id=None, via="api") -> dict
    reject(user_id, item_id, *, workspace_id=None, via="api") -> dict

Every function resolves the caller's scope (workspace membership, Brand space)
first and raises :class:`~app.domains.integrations.errors.IntegrationError`
(``status_code`` + safe ``message``) on any refusal. Sessions are opened here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Callable

from app.domains.integrations import actions, agent, metrics
from app.domains.integrations.connectors import get_connector
from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.scope import resolve
from app.domains.integrations.service import get_account, visible_accounts, account_view

try:
    from app.models.db.base import get_session
except Exception:  # pragma: no cover
    get_session = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ConnectedAccount:
    id: str
    provider: str
    provider_label: str
    external_id: str
    name: str
    currency: str
    status: str
    brand_space_ids: tuple[str, ...]
    last_pulled_at: str | None

    def as_dict(self) -> dict:
        return {**asdict(self), "brand_space_ids": list(self.brand_space_ids)}


@dataclass(frozen=True)
class CreativePerformance:
    ad_account_id: str
    provider: str
    entity_id: str
    entity_name: str
    campaign_id: str
    currency: str
    spend: float
    impressions: int
    clicks: int
    conversions: float | None
    ctr: float | None
    cpa: float | None
    roas: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def _session():
    if get_session is None:
        raise IntegrationError(503, "Integrations storage is unavailable.")
    return get_session()


def list_connected_accounts(user_id: str, *, workspace_id: str | None = None,
                            brand_space_id: str | None = None) -> list[ConnectedAccount]:
    with _session() as session:
        scope = resolve(session, user_id, workspace_id=workspace_id, brand_space_id=brand_space_id)
        out = []
        for row in visible_accounts(session, scope):
            view = account_view(session, row)
            out.append(ConnectedAccount(
                id=row.id, provider=row.provider, provider_label=get_connector(row.provider).label,
                external_id=row.external_id, name=row.name, currency=row.currency, status=row.status,
                brand_space_ids=tuple(view["brand_space_ids"]), last_pulled_at=view["last_pulled_at"]))
        return out


def top_performing_creatives(user_id: str, ad_account_id: str, *, period_days: int = 7, limit: int = 10,
                             workspace_id: str | None = None, brand_space_id: str | None = None,
                             today: date | None = None) -> list[CreativePerformance]:
    with _session() as session:
        scope = resolve(session, user_id, workspace_id=workspace_id, brand_space_id=brand_space_id)
        account = get_account(session, scope, ad_account_id)
        since, until = metrics.window(period_days, today)
        ranked = metrics.rank_top(metrics.creatives(metrics.rows_for(session, [account.id], since, until)))
        out = []
        for item in ranked[: max(1, min(int(limit or 10), 50))]:
            m = item["metrics"]
            out.append(CreativePerformance(
                ad_account_id=account.id, provider=account.provider, entity_id=item["entity_id"],
                entity_name=item["entity_name"], campaign_id=item["campaign_id"], currency=item["currency"],
                spend=m["spend"], impressions=m["impressions"], clicks=m["clicks"], conversions=m["conversions"],
                ctr=m["ctr"], cpa=m["cpa"], roas=m["roas"]))
        return out


def ask_campaign_question(user_id: str, question: str, *, workspace_id: str | None = None,
                          brand_space_id: str | None = None, llm: Callable[[str], str] | None = None,
                          period_days: int = 7) -> dict:
    with _session() as session:
        scope = resolve(session, user_id, workspace_id=workspace_id, brand_space_id=brand_space_id)
        return agent.ask_campaign_question(session, scope, question, llm=llm, days=period_days)


def pull_report(user_id: str, *, ad_account_id: str | None = None, period_days: int = 7,
                workspace_id: str | None = None, brand_space_id: str | None = None) -> dict:
    with _session() as session:
        scope = resolve(session, user_id, workspace_id=workspace_id, brand_space_id=brand_space_id)
        return agent.pull_report(session, scope, ad_account_id=ad_account_id, days=period_days)


def propose_optimization(user_id: str, *, ad_account_id: str | None = None, period_days: int = 7,
                         workspace_id: str | None = None) -> dict:
    with _session() as session:
        scope = resolve(session, user_id, workspace_id=workspace_id)
        return agent.propose_optimization(session, scope, ad_account_id=ad_account_id, days=period_days)


def _decide(user_id: str, item_id: str, decision: str, workspace_id: str | None, via: str) -> dict:
    with _session() as session:
        scope = resolve(session, user_id, workspace_id=workspace_id)
    return actions.decide(scope, item_id, decision, via=via)


def approve(user_id: str, item_id: str, *, workspace_id: str | None = None, via: str = "api") -> dict:
    return _decide(user_id, item_id, "approve", workspace_id, via)


def reject(user_id: str, item_id: str, *, workspace_id: str | None = None, via: str = "api") -> dict:
    return _decide(user_id, item_id, "reject", workspace_id, via)


__all__ = [
    "ConnectedAccount", "CreativePerformance", "approve", "ask_campaign_question", "list_connected_accounts",
    "propose_optimization", "pull_report", "reject", "top_performing_creatives",
]
