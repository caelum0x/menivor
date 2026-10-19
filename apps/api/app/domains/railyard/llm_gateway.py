"""Railyard LLM gateway (Python mirror of ``railyard/gtm-llm.ts``).

ReelForge's script / terms / social-metadata generators all share one shape: an
OpenAI-compatible ``chat.completions`` call. This module centralizes the OPT-IN
Railyard hop for exactly that shape so each call site stays a one-line change:

* RELAY  configured  → route through the OpenAI SDK pointed at
  ``${RELAY_URL}/openai/v1``, with the model rewritten to its TensorZero name
  (``tensorzero::model_name::openai::gpt-4o-mini``).
* ABACUS configured  → wrap the request through ``POST /v1/proxy`` so a per-key
  spend cap is enforced first; a cap breach (HTTP 402) surfaces as
  ``RailyardError(code="cap_exceeded")`` which STOPS this project's LLM spend
  (the caller degrades to its direct path — never a silent retry past the cap).
  When Abacus fronts Relay, the model still uses the TensorZero name, so mapping
  keys off RELAY being on.
* NEITHER configured → :func:`railyard_llm_enabled` is ``False`` and the caller
  keeps its existing direct-provider path completely unchanged.

Nothing here logs an API key. It only raises a ``RailyardError`` the caller
already knows how to fall back from.
"""

from __future__ import annotations

import os
from typing import Any, Callable, List, Mapping, Optional

from loguru import logger

from .abacus import create_abacus_client
from .config import (
    RailyardEnv,
    get_abacus_config,
    is_abacus_enabled,
    is_relay_enabled,
)
from .errors import RailyardError, truncate_detail
from .relay import create_relay_target, to_tensorzero_model_name

# Factory for an OpenAI-SDK-shaped client: ``(api_key, base_url) -> client`` with
# ``client.chat.completions.create(...)``. Injectable for tests.
OpenAIFactory = Callable[[str, Optional[str]], Any]

Messages = List[Mapping[str, Any]]


def railyard_llm_enabled(env: Optional[RailyardEnv] = None) -> bool:
    """True when the Railyard LLM hop is opt-in-configured (Relay OR Abacus).

    When ``False`` the caller MUST keep its existing direct-provider path as-is.
    """
    return is_relay_enabled(env) or is_abacus_enabled(env)


def resolve_relay_model(
    model: str,
    env: Optional[RailyardEnv] = None,
    *,
    relay_provider: Optional[str] = None,
) -> str:
    """The model string to send: a TensorZero name when RELAY is the (eventual)
    gateway, else the plain id.

    Keying off RELAY — not the transport — is deliberate: Abacus fronting Relay
    still needs the TensorZero name, while Abacus fronting a provider directly
    needs the plain id. ``relay_provider`` (see ``relay_provider_for``) names the
    real upstream; ``None`` keeps the legacy inference from the model id.
    """
    if not is_relay_enabled(env):
        return model
    return to_tensorzero_model_name(model, provider=relay_provider)


def resolve_provider_key(fallback_api_key: str, env: Optional[RailyardEnv] = None) -> str:
    """Resolve the upstream provider credential Abacus forwards (never logged).

    Prefers the caller's configured provider key, then ``RELAY_API_KEY``, then a
    harmless placeholder a no-auth Relay upstream ignores.
    """
    env = env if env is not None else os.environ
    relay_key = env.get("RELAY_API_KEY")
    relay_key = relay_key.strip() if isinstance(relay_key, str) else ""
    return (fallback_api_key or "").strip() or relay_key or "railyard-relay"


def _default_openai_factory(api_key: str, base_url: Optional[str]) -> Any:
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": api_key or "railyard-relay"}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _content_from_choices(choices: Any) -> Optional[str]:
    """Extract ``choices[0].message.content`` from an SDK object or a dict."""
    if not choices:
        return None
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    if message is None:
        return None
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    return content if isinstance(content, str) else None


#: Relay statuses that are policy decisions (spend cap / rate limit): the caller
#: must stop, never retry the same spend on its direct provider.
_POLICY_STATUS_CODES = {402: "cap_exceeded", 429: "rate_limited"}
#: Relay statuses meaning "Relay cannot serve this" (e.g. 503
#: ``provider_not_configured``): the caller falls back to its direct provider.
_UNAVAILABLE_STATUSES = frozenset({502, 503, 504})


def _relay_error_code(body: Any) -> Optional[str]:
    """``error.code`` from an OpenAI-style error body, if present."""
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and code else None


def _translate_relay_failure(error: Exception) -> Optional[RailyardError]:
    """Map an OpenAI-SDK failure from the Relay hop onto a ``RailyardError``.

    402/429 → hard-stop codes; 502/503/504 and connection failures → fallback
    codes; anything else → ``None`` (the original error propagates unchanged).
    """
    import openai

    if isinstance(error, openai.APIStatusError):
        status = error.status_code
        if status in _POLICY_STATUS_CODES:
            code = _POLICY_STATUS_CODES[status]
        elif status in _UNAVAILABLE_STATUSES:
            code = _relay_error_code(error.body) or "unavailable"
        else:
            return None
        return RailyardError(
            f"Relay refused the request (HTTP {status})",
            service="relay",
            code=code,
            status=status,
            detail=truncate_detail(_relay_error_code(error.body) or status),
        )
    if isinstance(error, openai.APIConnectionError):
        return RailyardError(
            "Relay is unreachable", service="relay", code="unavailable"
        )
    return None


def run_chat_text(
    *,
    prompt: str,
    model: str,
    relay_provider: Optional[str] = None,
    provider_api_key: str = "",
    provider_base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    agent_id: Optional[str] = None,
    request_id: Optional[str] = None,
    env: Optional[RailyardEnv] = None,
    openai_factory: Optional[OpenAIFactory] = None,
    abacus_request_fn: Optional[Callable] = None,
) -> str:
    """Run one chat completion through the configured Railyard transport.

    Precondition: only call when :func:`railyard_llm_enabled` is ``True``. On any
    failure it raises (``RailyardError`` for Railyard-origin failures, or the SDK
    error) so the caller can fall back to its direct path. A cap breach is a
    ``RailyardError(code="cap_exceeded")`` and is NOT retried on another
    transport.

    ``provider_api_key`` / ``provider_base_url`` are the caller's existing direct
    provider credentials, used verbatim when Relay is not configured.
    ``relay_provider`` is the Relay provider namespace for ``model`` (groq,
    openrouter, anthropic, openai); ``None`` keeps the legacy inference.

    Relay HTTP failures surface as ``RailyardError``: 402 → ``cap_exceeded`` and
    429 → ``rate_limited`` (hard stops); 502/503/504 → the Relay error code
    (e.g. ``provider_not_configured``) or ``unavailable`` (fall back).
    """
    env = env if env is not None else os.environ
    messages: Messages = [{"role": "user", "content": prompt}]
    on_wire_model = resolve_relay_model(model, env, relay_provider=relay_provider)

    # ── Abacus (per-key spend cap in front of the gateway) ───────────────────
    if is_abacus_enabled(env):
        resolved_agent = agent_id or get_abacus_config(env).agent_id
        # Abacus needs a per-key identity; without one, fall through to
        # Relay/direct rather than losing the LLM entirely to a misconfiguration.
        if resolved_agent:
            body: dict[str, Any] = {"model": on_wire_model, "messages": messages}
            if temperature is not None:
                body["temperature"] = temperature
            try:
                abacus = create_abacus_client(env=env, request_fn=abacus_request_fn)
                response = abacus.proxy_chat(
                    body,
                    provider_key=resolve_provider_key(provider_api_key, env),
                    agent_id=resolved_agent,
                    request_id=request_id,
                )
                content = _content_from_choices(response.get("choices"))
                if content is None:
                    raise RailyardError(
                        "Abacus returned no assistant content",
                        service="abacus",
                        code="bad_response",
                    )
                return content
            except RailyardError as error:
                # A spent cap must stop this project's LLM spend — never retry.
                if error.code == "cap_exceeded":
                    raise
                # A missing/misconfigured gate falls through to Relay/direct.
                if error.code != "not_configured":
                    raise
                logger.debug(f"Abacus gate skipped ({error.code}); falling through to Relay/direct.")

    # ── Relay (OpenAI-compatible gateway) or the caller's direct provider ────
    target = create_relay_target(
        fallback_api_key=provider_api_key,
        fallback_base_url=provider_base_url,
        env=env,
    )
    factory = openai_factory or _default_openai_factory
    client = factory(target.api_key or "", target.base_url)
    create_kwargs: dict[str, Any] = {
        "model": target.map_model(model, provider=relay_provider),
        "messages": messages,
    }
    if temperature is not None:
        create_kwargs["temperature"] = temperature
    try:
        completion = client.chat.completions.create(**create_kwargs)
    except Exception as error:  # noqa: BLE001 - translated or re-raised as-is
        translated = _translate_relay_failure(error) if target.via_relay else None
        if translated is None:
            raise
        raise translated from error
    content = _content_from_choices(getattr(completion, "choices", None))
    if content is None:
        raise RailyardError(
            "Relay/direct returned no assistant content",
            service="relay",
            code="bad_response",
        )
    return content
