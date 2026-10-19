"""Railyard client layer (Python) — env-gated, opt-in LLM metering for ReelForge.

Mirrors the VCPeer TypeScript pattern at ``vcglass/lib/railyard/{relay,abacus,
gtm-llm}.ts`` so Menivor's Python API can route its OpenAI-compatible chat calls
through the Railyard RELAY gateway (TensorZero) and, optionally, the ABACUS
per-key spend cap in front of it — so *all* AI spend is metered and capped.

Everything here is entirely OPT-IN and never a hard dependency:

* ``RELAY_URL`` unset  → :func:`is_relay_enabled` is ``False``.
* ``ABACUS_URL`` (+ ``ABACUS_API_KEY``) unset → :func:`is_abacus_enabled` is
  ``False``.
* neither set → :func:`railyard_llm_enabled` is ``False`` and every caller keeps
  its existing direct-provider path completely unchanged.

No API key is ever logged. The only failure a caller must handle is a
:class:`RailyardError` (e.g. an Abacus per-key cap breach), from which it falls
back to the direct provider path.
"""

from __future__ import annotations

from .abacus import AbacusClient, create_abacus_client
from .config import (
    AbacusConfig,
    RelayConfig,
    get_abacus_config,
    get_relay_config,
    is_abacus_enabled,
    is_relay_enabled,
)
from .errors import RailyardError
from .llm_gateway import (
    railyard_llm_enabled,
    resolve_provider_key,
    resolve_relay_model,
    run_chat_text,
)
from .relay import (
    RelayTarget,
    create_relay_target,
    relay_provider_for,
    split_litellm_model,
    to_tensorzero_model_name,
)

__all__ = [
    "AbacusClient",
    "AbacusConfig",
    "RailyardError",
    "RelayConfig",
    "RelayTarget",
    "create_abacus_client",
    "create_relay_target",
    "get_abacus_config",
    "get_relay_config",
    "is_abacus_enabled",
    "is_relay_enabled",
    "railyard_llm_enabled",
    "relay_provider_for",
    "split_litellm_model",
    "resolve_provider_key",
    "resolve_relay_model",
    "run_chat_text",
    "to_tensorzero_model_name",
]
