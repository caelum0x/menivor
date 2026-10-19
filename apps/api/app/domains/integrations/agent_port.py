"""Brand Agent adapter: the agent's integrations port over :mod:`app.domains.integrations.contract`.

The Brand Agent looks this module up at ``app.domains.integrations.agent_port:PORT``
(see ``app.domains.brand_agent.ports.integrations``). Every call is owner-scoped by
``user_id`` through the contract (personal scope: the agent's Brand spaces are not
brand kits, so no Brand-space filter is applied). Refusals become
:class:`PortUnavailable` with the contract's safe message so the agent can show it
with Retry; nothing here writes or spends.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlencode

from app.domains.brand_agent.ports.base import PortUnavailable
from app.domains.integrations import contract
from app.domains.integrations.errors import IntegrationError

DEFAULT_PERIOD_DAYS = 7
MAX_LIMIT = 50
NO_RESULTS = ("No ad results from the last {days} days yet. Press Refresh on the ad account in "
              "Settings > Integrations, then Retry.")
NOT_CONNECTED = ("{label} is not connected yet. Connect your ad account in Settings > Integrations, "
                 "then press Retry.")
_LABELS = {"meta": "Meta Ads", "google_ads": "Google Ads", "tiktok": "TikTok Ads", "snapchat": "Snapchat Ads",
           "reddit": "Reddit Ads", "applovin": "AppLovin", "openai_ads": "OpenAI Ads"}


def _ads_manager_url(provider: str, external_id: str, entity_id: str) -> str:
    """A link that opens the ad in its platform (Inspirations need a real https link)."""
    account = str(external_id or "").removeprefix("act_")
    if provider == "meta":
        return "https://adsmanager.facebook.com/adsmanager/manage/ads?" + urlencode(
            {"act": account, "selected_ad_ids": entity_id})
    if provider == "tiktok":
        return "https://ads.tiktok.com/i18n/perf/creative?" + urlencode({"aadvid": account, "keyword": entity_id})
    if provider == "google_ads":
        return "https://ads.google.com/aw/ads?" + urlencode({"ocid": account, "adId": entity_id})
    return ""


def _rank_key(item: Any) -> tuple:
    return (item.roas if item.roas is not None else -1.0, item.conversions or 0.0,
            item.ctr if item.ctr is not None else -1.0, item.spend)


def _creative_view(item: Any, external_id: str) -> dict[str, Any]:
    return {
        "id": item.entity_id,
        "title": item.entity_name or f"Ad {item.entity_id}",
        "url": _ads_manager_url(item.provider, external_id, item.entity_id),
        "thumbnail_url": "",
        "metrics": {"spend": item.spend, "impressions": item.impressions, "clicks": item.clicks,
                    "conversions": item.conversions, "ctr": item.ctr, "cpa": item.cpa, "roas": item.roas,
                    "currency": item.currency, "ad_account_id": item.ad_account_id},
    }


class IntegrationsAgentPort:
    """Plain-Python adapter; ``api`` defaults to the contract module (tests pass a fake)."""

    def __init__(self, api: Any = contract, *, period_days: int = DEFAULT_PERIOD_DAYS) -> None:
        self._api = api
        self._days = period_days

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except IntegrationError as exc:
            raise PortUnavailable(exc.message) from exc

    def list_connected_accounts(self, user_id: str) -> list[dict[str, Any]]:
        try:
            accounts = self._api.list_connected_accounts(user_id)
        except IntegrationError:
            return []  # the connectors panel shows "not connected"; no reason leaks
        return [{"platform": a.provider, "account_id": a.id, "name": a.name or a.external_id,
                 "provider_label": a.provider_label, "currency": a.currency, "status": a.status}
                for a in accounts if a.status != "unavailable"]

    def top_performing_creatives(self, user_id: str, *, platform: str, limit: int) -> list[dict[str, Any]]:
        provider = str(platform or "").strip().lower()
        accounts = [a for a in self._call(self._api.list_connected_accounts, user_id)
                    if a.provider == provider and a.status == "active"]
        if not accounts:
            raise PortUnavailable(NOT_CONNECTED.format(label=_LABELS.get(provider, provider or "The ad account")))
        cap = max(1, min(int(limit or 10), MAX_LIMIT))
        ranked: list[tuple[Any, str]] = []
        for account in accounts:
            for item in self._call(self._api.top_performing_creatives, user_id, account.id,
                                   period_days=self._days, limit=cap):
                ranked.append((item, account.external_id))
        if not ranked:
            raise PortUnavailable(NO_RESULTS.format(days=self._days))
        ranked.sort(key=lambda pair: _rank_key(pair[0]), reverse=True)
        views = [_creative_view(item, ext) for item, ext in ranked]
        return [v for v in views if v["url"]][:cap]

    def ask_campaign_question(self, user_id: str, question: str) -> dict[str, Any]:
        return dict(self._call(self._api.ask_campaign_question, user_id, question, period_days=self._days))

    def pull_report(self, user_id: str, **filters: Any) -> dict[str, Any]:
        return dict(self._call(self._api.pull_report, user_id, ad_account_id=filters.get("ad_account_id"),
                               period_days=int(filters.get("period_days") or self._days)))

    def propose_optimization(self, user_id: str, **kwargs: Any) -> dict[str, Any]:
        return dict(self._call(self._api.propose_optimization, user_id, ad_account_id=kwargs.get("ad_account_id"),
                               period_days=int(kwargs.get("period_days") or self._days)))


PORT = IntegrationsAgentPort()

__all__ = ["IntegrationsAgentPort", "PORT"]
