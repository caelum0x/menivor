"""Menivor -> Railyard integration (opt-in, env-gated).

* :mod:`.relay`    -- ``RAILYARD_RELAY_URL`` routes LLM chat calls through Relay.
* :mod:`.metering` -- ``RAILYARD_RAGO_URL`` + ``RAILYARD_RAGO_API_KEY`` meter
  settled renders and Relay-routed LLM calls to Rago.

With none of the ``RAILYARD_*`` variables set, nothing here changes behavior.
See ``railyard/docs/CONSUMERS.md`` for the full product -> Railyard map.
"""

from .metering import UsageEvent, emit, flush, meter_llm_call, meter_render
from .relay import relay_env, relay_openai_base_url
from .settings import RailyardSettings, load_settings

__all__ = [
    "RailyardSettings",
    "UsageEvent",
    "emit",
    "flush",
    "load_settings",
    "meter_llm_call",
    "meter_render",
    "relay_env",
    "relay_openai_base_url",
]
