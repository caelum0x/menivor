"""Shared contract for ad-account connectors.

Each provider is one :class:`Connector` subclass. Every network call goes through
an injectable transport (the multipost ``Transport`` shape), so tests pass a
recording fake and nothing else is faked. Connectors are stateless: they take a
token in and return frozen values out; storage and encryption live in the service.

Money: every amount leaves a connector in account-currency MINOR units (cents for
USD), the Menivor-wide convention. A metric the platform did not report is
``None`` - never an invented 0.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.domains.ads.platforms import minor_factor

ACTIONS: frozenset[str] = frozenset({"pause", "resume"})
HTTP_TIMEOUT_S = 30.0


class ConnectorError(Exception):
    """A provider call failed; ``message`` is safe to show (never carries a token)."""

    def __init__(self, provider: str, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.provider = provider
        self.message = message
        self.status_code = status_code


class AuthError(ConnectorError):
    """The provider rejected the token: the account must be reconnected."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(provider, message, status_code=401)


@dataclass(frozen=True)
class Grant:
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: str = ""
    external_id: str = ""
    account_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AccountInfo:
    external_id: str
    name: str
    currency: str = "USD"
    timezone: str = ""
    status: str = "active"


@dataclass(frozen=True)
class CampaignDraftRequest:
    """What the workspace asked for. ``countries`` and ``adam_id`` are read by
    only the providers that need them (Apple Search Ads requires ``adam_id``,
    the App Store numeric id of the app being promoted; Google Ads and Meta
    ignore it)."""

    name: str
    daily_budget_minor: int
    countries: tuple[str, ...] = ()
    adam_id: str = ""


@dataclass(frozen=True)
class CampaignDraft:
    """A campaign Menivor just created on the platform. Always paused: Menivor
    never flips a campaign live on its own, no matter what the platform's
    default status would otherwise be."""

    external_id: str
    name: str
    status: str = "paused"
    manage_url: str = ""
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class KeywordInsight:
    """Apple's own Search Popularity index for one term: an integer 5-100 in
    steps of 5, or ``None`` when Apple has not accumulated enough search
    volume to score it yet. Apple's Search Ads API does not publish a
    separate "difficulty" number alongside it -- Menivor shows only what the
    platform actually reports, never an invented proxy (same rule as
    :class:`MetricRow`'s money/engagement fields)."""

    term: str
    popularity: int | None = None


@dataclass(frozen=True)
class MetricRow:
    """One day of one creative (or campaign, for PMax) in the common shape."""

    day: str
    entity_id: str
    entity_name: str = ""
    campaign_id: str = ""
    group_id: str = ""
    spend_minor: int = 0
    impressions: int = 0
    clicks: int = 0
    conversions: float | None = None
    conversion_value_minor: int | None = None
    currency: str = "USD"
    #: Unique people reached that day; None when the platform does not report it.
    reach: int | None = None


class RequestsTransport:
    """Default transport (lazy ``requests`` import, short timeout, no redirects)."""

    def __init__(self, timeout_s: float = HTTP_TIMEOUT_S) -> None:
        self._timeout = timeout_s

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        import requests

        return requests.request(method, url, headers=headers, params=params, json=json, data=data,
                                timeout=self._timeout, allow_redirects=False)


# --------------------------------------------------------------------------- helpers
def env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def expires_from(seconds: Any) -> datetime | None:
    try:
        value = int(float(seconds or 0))
    except (TypeError, ValueError):
        return None
    return now_utc() + timedelta(seconds=value) if value > 0 else None


def to_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def major_to_minor(amount: Any, currency: str) -> int:
    value = to_float(amount) or 0.0
    return int(round(value * minor_factor(currency)))


def micros_to_minor(micros: Any, currency: str) -> int:
    value = to_float(micros) or 0.0
    return int(round(value / 1_000_000 * minor_factor(currency)))


def body_of(resp: Any) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {}


def day_str(value: date) -> str:
    return value.isoformat()


class Connector:
    """Base connector. Subclasses override what their platform supports."""

    provider: str = ""
    label: str = ""
    capabilities: str = ""
    auth: str = "oauth"  # "oauth" | "api_key"
    supports_delivery: bool = False
    delivery_level: str = "ad"  # which entity a pause/resume targets
    supports_campaign_drafts: bool = False
    supports_keyword_insights: bool = False
    required_env: tuple[str, ...] = ()
    #: Extra env this provider needs only for drafting campaigns (beyond ``required_env``).
    draft_required_env: tuple[str, ...] = ()

    # ------------------------------------------------------------- configuration
    def missing_settings(self) -> list[str]:
        return [name for name in self.required_env if not env(name)]

    def configured(self) -> bool:
        return not self.missing_settings()

    def _require_configured(self) -> None:
        missing = self.missing_settings()
        if missing:
            raise ConnectorError(self.provider, f"{self.label} is not set up on this server yet.", status_code=503)

    # ------------------------------------------------------------------- flows
    def authorize_url(self, state: str, redirect_uri: str) -> str:  # pragma: no cover - api-key connectors
        raise ConnectorError(self.provider, f"{self.label} connects with an API key, not a sign-in.", status_code=400)

    def exchange_code(self, transport: Any, code: str, redirect_uri: str) -> Grant:  # pragma: no cover
        raise ConnectorError(self.provider, f"{self.label} connects with an API key, not a sign-in.", status_code=400)

    def refresh(self, transport: Any, grant: Grant) -> Grant:
        """Default: tokens that never expire are returned unchanged."""
        if grant.expires_at is not None and grant.expires_at <= now_utc():
            raise AuthError(self.provider, f"The {self.label} connection expired. Reconnect it.")
        return grant

    def validate_key(self, transport: Any, key: str) -> Grant:  # pragma: no cover - oauth connectors
        raise ConnectorError(self.provider, f"{self.label} connects by signing in, not with a key.", status_code=400)

    def list_accounts(self, transport: Any, token: str) -> list[AccountInfo]:  # pragma: no cover
        raise NotImplementedError

    def fetch_metrics(self, transport: Any, token: str, account: AccountInfo, since: date,
                      until: date) -> list[MetricRow]:  # pragma: no cover
        raise NotImplementedError

    def execute(self, transport: Any, token: str, account: AccountInfo, action: str, entity_id: str) -> dict:
        self._check_action(action, entity_id)
        if not self.supports_delivery:
            raise ConnectorError(self.provider, f"{self.label} changes are not available from Menivor yet.",
                                 status_code=400)
        return self._execute(transport, token, account, action, entity_id)

    def _execute(self, transport: Any, token: str, account: AccountInfo, action: str,
                 entity_id: str) -> dict:  # pragma: no cover
        raise NotImplementedError

    def _check_action(self, action: str, entity_id: str) -> None:
        if action not in ACTIONS:
            raise ConnectorError(self.provider, "Only pause and resume are supported.", status_code=400)
        if not str(entity_id or "").strip():
            raise ConnectorError(self.provider, "Choose which ad to change.", status_code=400)

    # --------------------------------------------------------------- campaign drafts
    def missing_draft_settings(self) -> list[str]:
        return [name for name in (*self.required_env, *self.draft_required_env) if not env(name)]

    def create_campaign(self, transport: Any, token: str, account: AccountInfo,
                        request: "CampaignDraftRequest") -> "CampaignDraft":
        """Create a new campaign on the platform, always left PAUSED. Menivor never
        enables spend on a campaign it created; the workspace reviews and launches
        it from the platform's own dashboard."""
        self._check_draft(request)
        if not self.supports_campaign_drafts:
            raise ConnectorError(self.provider, f"{self.label} campaign drafts are not available from Menivor yet.",
                                 status_code=400)
        missing = self.missing_draft_settings()
        if missing:
            raise ConnectorError(self.provider, f"{self.label} campaign drafts are not set up on this server yet.",
                                 status_code=503)
        draft = self._create_campaign(transport, token, account, request)
        if draft.status != "paused":  # pragma: no cover - defensive, every connector must return "paused"
            raise ConnectorError(self.provider, "Refused to create a campaign that is not paused.", status_code=500)
        return draft

    def _create_campaign(self, transport: Any, token: str, account: AccountInfo,
                         request: "CampaignDraftRequest") -> "CampaignDraft":  # pragma: no cover
        raise NotImplementedError

    def _check_draft(self, request: "CampaignDraftRequest") -> None:
        if not str(request.name or "").strip():
            raise ConnectorError(self.provider, "Name the campaign.", status_code=400)
        if request.daily_budget_minor <= 0:
            raise ConnectorError(self.provider, "Set a daily budget greater than zero.", status_code=400)

    # --------------------------------------------------------------- keyword insights
    def keyword_insights(self, transport: Any, token: str, account: "AccountInfo", *, adam_id: str, country: str,
                         terms: list[str], cache: dict | None = None) -> tuple[list["KeywordInsight"], dict]:
        """Apple's own Search Popularity index for a batch of terms against one
        App Store app. Returns ``(insights, cache)`` -- ``cache`` is an opaque
        blob the connector may ask the caller to persist (and pass back next
        time) so repeat lookups do not re-provision anything on the platform;
        connectors that do not support this raise rather than guess."""
        if not self.supports_keyword_insights:
            raise ConnectorError(self.provider, f"{self.label} does not provide keyword popularity.",
                                 status_code=400)
        cleaned = list(dict.fromkeys(t.strip() for t in terms if t and t.strip()))
        if not cleaned:
            return [], dict(cache or {})
        return self._fetch_keyword_insights(transport, token, account, adam_id=adam_id, country=country,
                                            terms=cleaned, cache=dict(cache or {}))

    def _fetch_keyword_insights(self, transport: Any, token: str, account: "AccountInfo", *, adam_id: str,
                                country: str, terms: list[str],
                                cache: dict) -> tuple[list["KeywordInsight"], dict]:  # pragma: no cover
        raise NotImplementedError


__all__ = [
    "ACTIONS", "AccountInfo", "AuthError", "CampaignDraft", "CampaignDraftRequest", "Connector", "ConnectorError",
    "Grant", "KeywordInsight", "MetricRow", "RequestsTransport", "body_of", "day_str", "env", "expires_from",
    "major_to_minor", "micros_to_minor", "now_utc", "to_float", "to_int",
]
