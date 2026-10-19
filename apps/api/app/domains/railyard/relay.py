"""Railyard RELAY helpers (Python mirror of ``railyard/relay.ts``).

Relay is a TensorZero-based gateway exposing an OpenAI-compatible surface at
``${RELAY_URL}/openai/v1``. Because it speaks the OpenAI wire protocol, the
simplest integration is to reuse the existing OpenAI SDK with a swapped
``base_url`` — no new dependency, the same ``chat.completions.create`` shape
ReelForge's script generator already uses.

The one twist: through Relay the ``model`` field must be a TensorZero model name
(``tensorzero::model_name::openai::gpt-4o-mini``,
``tensorzero::model_name::groq::llama-3.3-70b-versatile``) or a function
(``tensorzero::function_name::chat``). :func:`to_tensorzero_model_name` maps
plain model ids to that form; :func:`relay_provider_for` derives the provider
namespace (groq / openrouter / anthropic / openai) from the configured provider
so Relay routes to the real upstream instead of guessing from the model id.

Entirely OPT-IN with graceful fallback: when ``RELAY_URL`` is unset,
:func:`create_relay_target` reports ``via_relay=False`` and echoes the caller's
own ``base_url``/model, so one call site works either way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Tuple
from urllib.parse import urlparse

from .config import RailyardEnv, get_relay_config

TENSORZERO_PREFIX = "tensorzero::"

_CLAUDE_RE = re.compile(r"^claude", re.IGNORECASE)


#: Menivor LLM provider id -> the Relay provider shorthand it resolves.
RELAY_PROVIDER_BY_LLM_PROVIDER: Mapping[str, str] = MappingProxyType(
    {
        "groq": "groq",
        "openrouter": "openrouter",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "openai": "openai",
    }
)

#: Upstream API host -> Relay provider shorthand (for OpenAI-compatible
#: adapters whose provider id is generic but whose base URL is a known host).
RELAY_PROVIDER_BY_HOST: Mapping[str, str] = MappingProxyType(
    {
        "api.groq.com": "groq",
        "openrouter.ai": "openrouter",
        "api.anthropic.com": "anthropic",
        "api.openai.com": "openai",
    }
)


def relay_provider_for(
    llm_provider: Optional[str] = None, base_url: Optional[str] = None
) -> Optional[str]:
    """Relay provider namespace for a configured provider, or ``None`` if unknown.

    The provider id wins; otherwise the base URL host is matched. ``None`` means
    the caller keeps the legacy inference (``claude*`` → anthropic, else openai).
    """
    key = (llm_provider or "").strip().lower()
    if key in RELAY_PROVIDER_BY_LLM_PROVIDER:
        return RELAY_PROVIDER_BY_LLM_PROVIDER[key]
    if base_url:
        host = (urlparse(base_url.strip()).hostname or "").lower()
        if host in RELAY_PROVIDER_BY_HOST:
            return RELAY_PROVIDER_BY_HOST[host]
    return None


def split_litellm_model(model: str) -> Tuple[Optional[str], str]:
    """Split a LiteLLM route (``groq/openai/gpt-oss-120b``) into Relay parts.

    LiteLLM names the upstream in the model id's first path segment. When that
    segment is a provider Relay knows, return ``(relay_provider, upstream_model)``
    so Relay targets the real upstream; otherwise ``(None, model)`` unchanged.
    """
    head, sep, rest = model.strip().partition("/")
    provider = RELAY_PROVIDER_BY_LLM_PROVIDER.get(head.lower()) if sep and rest else None
    if provider is None:
        return None, model
    return provider, rest


def _infer_provider(model: str) -> str:
    """Legacy inference from a plain model id (used only for unknown providers)."""
    return "anthropic" if _CLAUDE_RE.match(model.strip()) else "openai"


def to_tensorzero_model_name(
    model: str,
    *,
    function_name: Optional[str] = None,
    provider: Optional[str] = None,
) -> str:
    """Map a plain model id (or TensorZero name) to what Relay expects.

    - an already-``tensorzero::…`` string passes through untouched;
    - ``function_name`` → ``tensorzero::function_name::<fn>``;
    - otherwise → ``tensorzero::model_name::<provider>::<model>`` using
      ``provider`` when given (see :func:`relay_provider_for`), else the legacy
      inference from the id (``claude*`` → anthropic, else openai).
    """
    if function_name:
        return f"{TENSORZERO_PREFIX}function_name::{function_name}"
    trimmed = model.strip()
    if trimmed.startswith(TENSORZERO_PREFIX):
        return trimmed
    resolved = provider or _infer_provider(trimmed)
    return f"{TENSORZERO_PREFIX}model_name::{resolved}::{trimmed}"


@dataclass(frozen=True)
class RelayTarget:
    """Where an OpenAI-compatible chat call should be sent.

    When ``via_relay`` is True, ``base_url`` is the Relay OpenAI surface and the
    model must be mapped with :meth:`map_model`; otherwise both fall back to the
    caller's own direct-provider values unchanged.
    """

    via_relay: bool
    #: OpenAI-SDK base URL to use (Relay surface, or the caller's direct URL).
    base_url: Optional[str]
    #: API key for the SDK (Relay credential when set, else the caller's key).
    api_key: Optional[str]

    def map_model(
        self,
        model: str,
        *,
        function_name: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> str:
        """TensorZero name when ``via_relay``, else the plain id unchanged."""
        if not self.via_relay:
            return model
        return to_tensorzero_model_name(
            model, function_name=function_name, provider=provider
        )


def create_relay_target(
    *,
    fallback_api_key: str = "",
    fallback_base_url: Optional[str] = None,
    env: Optional[RailyardEnv] = None,
) -> RelayTarget:
    """Resolve the OpenAI-SDK target: Relay when ``RELAY_URL`` is set, else the
    caller's direct provider values. Never raises for missing config.

    ``fallback_api_key`` / ``fallback_base_url`` are the caller's existing direct
    provider credentials, used verbatim when Relay is not configured.
    """
    relay = get_relay_config(env)
    if relay.configured and relay.openai_base_url:
        # gateway.auth is off by default → no Relay credential today; the SDK
        # still needs a non-empty key, so prefer the Relay key (if the owner
        # later enables auth), then the caller's key, then a harmless placeholder
        # a no-auth Relay ignores.
        api_key = relay.api_key or (fallback_api_key or "railyard-relay")
        return RelayTarget(
            via_relay=True, base_url=relay.openai_base_url, api_key=api_key
        )
    return RelayTarget(
        via_relay=False, base_url=fallback_base_url, api_key=fallback_api_key or None
    )
