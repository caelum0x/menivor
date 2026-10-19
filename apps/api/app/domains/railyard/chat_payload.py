"""Railyard hop for callers that need the FULL chat response (usage, id, cost).

:func:`app.domains.railyard.llm_gateway.run_chat_text` returns only the text,
which is enough for script generation. Routing adapters (e.g. the OpenRouter
``ProviderAdapter``) also need the OpenAI ``usage`` block to price the run, so
this module sends a verbatim OpenAI ``chat.completions`` body through the same
opt-in order and hands back the raw response dict:

1. ABACUS (``ABACUS_URL`` + ``ABACUS_API_KEY`` + an agent id) enforces the
   per-key spend cap first (``POST /v1/proxy``).
2. RELAY (``RELAY_URL`` / ``RAILYARD_RELAY_URL``) serves the OpenAI surface at
   ``${RELAY_URL}/openai/v1/chat/completions`` with a TensorZero model name.
3. ``None`` is returned when neither hop is configured or the hop is
   unavailable, and the caller keeps its existing direct-provider path.

Policy outcomes are hard stops, never routed around: an Abacus cap breach or a
Relay 402/429 raises ``RailyardError`` (``cap_exceeded`` / ``rate_limited``).

Scope note: Relay (TensorZero) and Abacus only speak chat completions and
embeddings. Image generation and TTS have no Railyard route today, so those
provider calls stay direct and are metered to Rago per settled job instead
(see ``app.domains.gateway.media_gateway._meter_settled_job``).

No API key is ever logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from loguru import logger

from .abacus import RequestFn, _default_transport, create_abacus_client
from .config import (
    RAILYARD_HTTP_TIMEOUT_S,
    RailyardEnv,
    get_abacus_config,
    get_relay_config,
    is_abacus_enabled,
)
from .errors import RailyardError, truncate_detail
from .llm_gateway import resolve_provider_key, resolve_relay_model

#: Codes a caller must treat as "stop spending", never as "try direct".
HARD_STOP_CODES = frozenset({"cap_exceeded", "rate_limited"})

_RELAY_POLICY_STATUS = {402: "cap_exceeded", 429: "rate_limited"}


@dataclass(frozen=True)
class RoutedChat:
    """A chat response served by Railyard, plus which hop served it."""

    payload: dict
    routed_via: str  # "abacus" | "relay"


def _has_choices(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get("choices"))


def _error_code(payload: Mapping[str, Any]) -> Optional[str]:
    error = payload.get("error") if isinstance(payload, Mapping) else None
    code = error.get("code") if isinstance(error, Mapping) else None
    return code if isinstance(code, str) and code else None


def _via_abacus(
    body: dict,
    *,
    provider_api_key: str,
    agent_id: Optional[str],
    request_id: Optional[str],
    env: RailyardEnv,
    request_fn: Optional[RequestFn],
) -> Optional[RoutedChat]:
    resolved_agent = agent_id or get_abacus_config(env).agent_id
    if not resolved_agent:
        return None
    try:
        client = create_abacus_client(env=env, request_fn=request_fn)
        payload = client.proxy_chat(
            body,
            provider_key=resolve_provider_key(provider_api_key, env),
            agent_id=resolved_agent,
            request_id=request_id,
        )
    except RailyardError as error:
        if error.code in HARD_STOP_CODES:
            raise
        logger.warning(f"railyard: Abacus hop skipped ({error.code}); trying Relay/direct")
        return None
    if not _has_choices(payload):
        logger.warning("railyard: Abacus returned no choices; trying Relay/direct")
        return None
    return RoutedChat(payload=payload, routed_via="abacus")


def _via_relay(
    body: dict,
    *,
    env: RailyardEnv,
    request_fn: Optional[RequestFn],
    timeout_s: float,
) -> Optional[RoutedChat]:
    relay = get_relay_config(env)
    if not relay.configured or not relay.openai_base_url:
        return None
    headers = {"Content-Type": "application/json"}
    if relay.api_key:
        headers["Authorization"] = f"Bearer {relay.api_key}"
    url = f"{relay.openai_base_url}/chat/completions"
    transport = request_fn or _default_transport
    try:
        status, payload = transport(url, headers, body, timeout_s)
    except RailyardError as error:
        logger.warning(f"railyard: Relay unreachable ({error.code}); using direct provider")
        return None
    if status in _RELAY_POLICY_STATUS:
        raise RailyardError(
            f"Relay refused the request (HTTP {status})",
            service="relay",
            code=_RELAY_POLICY_STATUS[status],
            status=status,
            detail=truncate_detail(_error_code(payload) or status),
        )
    if status < 200 or status >= 300 or not _has_choices(payload):
        logger.warning(
            f"railyard: Relay could not serve the request (HTTP {status}, "
            f"{_error_code(payload) or 'no choices'}); using direct provider"
        )
        return None
    return RoutedChat(payload=payload, routed_via="relay")


def run_chat_payload(
    body: Mapping[str, Any],
    *,
    relay_provider: Optional[str] = None,
    provider_api_key: str = "",
    agent_id: Optional[str] = None,
    request_id: Optional[str] = None,
    env: Optional[RailyardEnv] = None,
    abacus_request_fn: Optional[RequestFn] = None,
    relay_request_fn: Optional[RequestFn] = None,
    timeout_s: float = RAILYARD_HTTP_TIMEOUT_S,
) -> Optional[RoutedChat]:
    """Send an OpenAI chat body through Abacus, then Relay.

    ``body["model"]`` is the plain upstream model id; it is rewritten to the
    TensorZero name when Relay is configured. Returns ``None`` when the caller
    should use its direct provider. Raises ``RailyardError`` only for hard
    stops (see :data:`HARD_STOP_CODES`).
    """
    env = env if env is not None else os.environ
    model = str(body.get("model", "") or "")
    routed_body = {**dict(body), "model": resolve_relay_model(model, env, relay_provider=relay_provider)}

    if is_abacus_enabled(env):
        routed = _via_abacus(
            routed_body,
            provider_api_key=provider_api_key,
            agent_id=agent_id,
            request_id=request_id,
            env=env,
            request_fn=abacus_request_fn,
        )
        if routed is not None:
            return routed
    return _via_relay(routed_body, env=env, request_fn=relay_request_fn, timeout_s=timeout_s)
