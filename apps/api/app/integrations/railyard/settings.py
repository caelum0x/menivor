"""Env settings for the Menivor -> Railyard integration.

Everything is OFF unless configured. Reading settings never opens a socket.

Relay (LLM gateway, OpenAI-compatible):
    RAILYARD_RELAY_URL        base URL of Relay; LLM chat calls route through
                              ``${RAILYARD_RELAY_URL}/openai/v1``
    RAILYARD_RELAY_API_KEY    optional bearer key when Relay gateway auth is on

    The older ``RELAY_URL`` / ``RELAY_API_KEY`` names (read by
    ``app.domains.railyard``) still work and win when both are set, so existing
    deployments are unchanged.

Rago (usage metering, Lago-compatible events API):
    RAILYARD_RAGO_URL                 base URL of Rago
    RAILYARD_RAGO_API_KEY             Rago API key (Bearer)
    RAILYARD_RAGO_SUBSCRIPTION_ID     portfolio mode: every event is metered
                                      against this one subscription
    RAILYARD_RAGO_SUBSCRIPTION_PREFIX customer mode (used when no single
                                      subscription is set): the subscription is
                                      ``<prefix><workspace or user id>``
    RAILYARD_RAGO_RENDER_METRIC       count metric for settled renders
                                      (default ``reel_generated``, seeded by
                                      railyard/apps/rago/seeds/menivor-reels.json)
    RAILYARD_RAGO_CREDITS_METRIC      sum metric for credits consumed, property
                                      ``credits`` in micros (default
                                      ``reel_ai_credits``, same seed)
    RAILYARD_RAGO_LLM_METRIC          metric code for LLM calls
                                      (default ``menivor_llm_call``)
    RAILYARD_RAGO_TIMEOUT_SECONDS     per-request timeout (default 5)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

Env = Mapping[str, Optional[str]]

DEFAULT_RENDER_METRIC = "reel_generated"
DEFAULT_CREDITS_METRIC = "reel_ai_credits"
DEFAULT_LLM_METRIC = "menivor_llm_call"
DEFAULT_TIMEOUT_S = 5.0


def _read(env: Env, key: str) -> Optional[str]:
    raw = env.get(key)
    value = raw.strip() if isinstance(raw, str) else ""
    return value or None


@dataclass(frozen=True)
class RailyardSettings:
    relay_url: Optional[str]
    relay_api_key: Optional[str]
    rago_url: Optional[str]
    rago_api_key: Optional[str]
    rago_subscription_id: Optional[str]
    rago_subscription_prefix: Optional[str]
    render_metric: str
    credits_metric: str
    llm_metric: str
    timeout_s: float

    @property
    def relay_enabled(self) -> bool:
        return self.relay_url is not None

    @property
    def metering_enabled(self) -> bool:
        return bool(self.rago_url and self.rago_api_key)

    def subscription_for(self, owner_key: Optional[str]) -> Optional[str]:
        """The Rago subscription an event is metered against, or ``None``.

        Portfolio mode (one subscription for all of our own usage) wins; else
        customer mode maps each workspace/user to ``<prefix><owner>``.
        """
        if self.rago_subscription_id:
            return self.rago_subscription_id
        owner = (owner_key or "").strip()
        if self.rago_subscription_prefix and owner:
            return f"{self.rago_subscription_prefix}{owner}"
        return None


def load_settings(env: Optional[Env] = None) -> RailyardSettings:
    env = env if env is not None else os.environ
    timeout_raw = _read(env, "RAILYARD_RAGO_TIMEOUT_SECONDS")
    try:
        timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_S
    except ValueError:
        timeout = DEFAULT_TIMEOUT_S
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT_S
    relay_url = _read(env, "RAILYARD_RELAY_URL")
    rago_url = _read(env, "RAILYARD_RAGO_URL")
    return RailyardSettings(
        relay_url=relay_url.rstrip("/") if relay_url else None,
        relay_api_key=_read(env, "RAILYARD_RELAY_API_KEY"),
        rago_url=rago_url.rstrip("/") if rago_url else None,
        rago_api_key=_read(env, "RAILYARD_RAGO_API_KEY"),
        rago_subscription_id=_read(env, "RAILYARD_RAGO_SUBSCRIPTION_ID"),
        rago_subscription_prefix=_read(env, "RAILYARD_RAGO_SUBSCRIPTION_PREFIX"),
        render_metric=_read(env, "RAILYARD_RAGO_RENDER_METRIC") or DEFAULT_RENDER_METRIC,
        credits_metric=_read(env, "RAILYARD_RAGO_CREDITS_METRIC") or DEFAULT_CREDITS_METRIC,
        llm_metric=_read(env, "RAILYARD_RAGO_LLM_METRIC") or DEFAULT_LLM_METRIC,
        timeout_s=timeout,
    )
