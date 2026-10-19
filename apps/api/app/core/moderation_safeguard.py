"""gpt-oss-safeguard provider: policy-following safety classification.

Default provider (``MENIVOR_MODERATION_PROVIDER=safeguard``). The Menivor policy
(``moderation_policy.POLICY_TEXT``) goes in the system message, the collected
prompt text in the user message, and the model answers with a JSON decision
``{decision, categories[], rationale}`` that is validated strictly.

Hop order (a rate limit, outage or invalid answer on one falls through to the next):

1. ``relay``      - Railyard Relay (``RAILYARD_RELAY_URL``/``RELAY_URL`` + ``*_API_KEY``)
   at ``<relay>/openai/v1/chat/completions``, TensorZero model
   ``tensorzero::model_name::groq::openai/gpt-oss-safeguard-20b``.
2. ``groq``       - Groq direct (``GROQ_API_KEY``).
3. ``openrouter`` - OpenRouter (``OPENROUTER_API_KEY``), same model
   (``MENIVOR_MODERATION_OPENROUTER_MODEL`` overrides), with OpenRouter-side
   model fallback to ``openai/gpt-oss-120b``
   (``MENIVOR_MODERATION_OPENROUTER_FALLBACKS``, comma list or ``off``).
4. ``claude``     - Anthropic Messages API (``ANTHROPIC_API_KEY``),
   ``claude-haiku-4-5-20251001`` (``moderation_claude``).

A hop that answers 429 is skipped for ~60s (``moderation_cooldown``). Every hop
outcome is counted in ``moderation_hop_total{hop,outcome}``; the answering hop
is recorded in ``ModerationResult.provider`` (``safeguard:<hop>``).

Env overrides: ``MENIVOR_MODERATION_MODEL`` (Groq id),
``MENIVOR_MODERATION_RELAY_MODEL``, ``MENIVOR_MODERATION_MAX_TOKENS``,
``MENIVOR_MODERATION_REASONING_EFFORT`` (low|medium|high, default low).

Neither the prompt nor the model's rationale is ever logged (the rationale may
paraphrase user content); only categories and the decision leave this module.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from loguru import logger

from app.core import moderation_claude, moderation_cooldown
from app.core.moderation_common import (  # noqa: F401 - parse_decision re-exported
    env as _env,
    max_tokens,
    parse_decision,
    post_json,
    reasoning_effort,
    user_message,
)
from app.core.moderation_policy import POLICY_TEXT
from app.core.moderation_types import ModerationRateLimited, ModerationResult, ModerationUnavailable

NAME = "safeguard"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-safeguard-20b"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-safeguard-20b"
DEFAULT_OPENROUTER_FALLBACK = "openai/gpt-oss-120b"
HOPS = ("relay", "groq", "openrouter", "claude")


def model_id() -> str:
    return _env("MENIVOR_MODERATION_MODEL") or DEFAULT_MODEL


def relay_model_id() -> str:
    return _env("MENIVOR_MODERATION_RELAY_MODEL") or f"tensorzero::model_name::groq::{model_id()}"


def openrouter_model_id() -> str:
    return _env("MENIVOR_MODERATION_OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL


def openrouter_fallback_models() -> list[str]:
    raw = _env("MENIVOR_MODERATION_OPENROUTER_FALLBACKS")
    if raw.lower() in {"off", "none", "0"}:
        return []
    names = [m.strip() for m in (raw or DEFAULT_OPENROUTER_FALLBACK).split(",") if m.strip()]
    return [m for m in names if m != openrouter_model_id()][:2]


def relay_url() -> str:
    return _env("RAILYARD_RELAY_URL", "RELAY_URL").rstrip("/")


def relay_key() -> str:
    return _env("RAILYARD_RELAY_API_KEY", "RELAY_API_KEY")


def groq_key() -> str:
    return _env("GROQ_API_KEY")


def openrouter_key() -> str:
    return _env("OPENROUTER_API_KEY")


def configured() -> bool:
    return any(_ENABLED[hop]() for hop in HOPS)


def build_body(prompt: str, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens(),
        "reasoning_effort": reasoning_effort(),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": POLICY_TEXT},
            {"role": "user", "content": user_message(prompt)},
        ],
    }


def build_openrouter_body(prompt: str) -> dict[str, Any]:
    body = build_body(prompt, openrouter_model_id())
    fallbacks = openrouter_fallback_models()
    if fallbacks:
        # OpenRouter-side model fallback: safeguard-20b has a single upstream (Groq),
        # so a 5xx/429 there is retried on gpt-oss-120b (several upstreams) in-hop.
        body["models"] = [openrouter_model_id(), *fallbacks]
    # OpenRouter normalizes reasoning effort as ``reasoning.effort``; keep it out of the answer.
    body.pop("reasoning_effort")
    body["reasoning"] = {"effort": reasoning_effort(), "exclude": True}
    return body


def _chat_content(url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float) -> Any:
    data = post_json(url, headers, body, timeout_s)
    error = data.get("error") if isinstance(data, dict) else None
    if error:
        # OpenRouter reports upstream failures as HTTP 200 + {"error": {"code": ...}}.
        code = error.get("code") if isinstance(error, dict) else None
        if str(code) == "429":
            raise ModerationRateLimited("upstream 429")
        raise ModerationUnavailable(f"upstream error {str(code)[:16]}")
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModerationUnavailable("malformed completion body") from exc
    return message.get("content") if isinstance(message, dict) else None


def _result(hop: str, decision: str, categories: tuple[str, ...]) -> ModerationResult:
    return ModerationResult(decision=decision, categories=categories, provider=f"{NAME}:{hop}")


def _via_relay(prompt: str, timeout_s: float) -> ModerationResult:
    headers = {"content-type": "application/json"}
    if relay_key():
        headers["authorization"] = f"Bearer {relay_key()}"
    content = _chat_content(
        f"{relay_url()}/openai/v1/chat/completions",
        headers,
        build_body(prompt, relay_model_id()),
        timeout_s,
    )
    return _result("relay", *parse_decision(content))


def _via_groq(prompt: str, timeout_s: float) -> ModerationResult:
    headers = {"content-type": "application/json", "authorization": f"Bearer {groq_key()}"}
    content = _chat_content(GROQ_URL, headers, build_body(prompt, model_id()), timeout_s)
    return _result("groq", *parse_decision(content))


def _via_openrouter(prompt: str, timeout_s: float) -> ModerationResult:
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {openrouter_key()}",
        "HTTP-Referer": "https://menivor.com",
        "X-Title": "Menivor moderation",
    }
    content = _chat_content(OPENROUTER_URL, headers, build_openrouter_body(prompt), timeout_s)
    return _result("openrouter", *parse_decision(content))


def _via_claude(prompt: str, timeout_s: float) -> ModerationResult:
    return _result("claude", *moderation_claude.classify(prompt, timeout_s))


def _direct_allowed() -> bool:
    """Direct hops are off in production (``RAILYARD_LIVE=1``): Relay only, failing closed (Wave P PM1.5)."""
    from app.integrations.railyard.provider_clients import relay_only

    return not relay_only()


_ENABLED: dict[str, Callable[[], bool]] = {
    "relay": lambda: bool(relay_url()),
    "groq": lambda: bool(groq_key()) and _direct_allowed(),
    "openrouter": lambda: bool(openrouter_key()) and _direct_allowed(),
    "claude": lambda: bool(moderation_claude.api_key()) and _direct_allowed(),
}
_CALL: dict[str, Callable[[str, float], ModerationResult]] = {
    "relay": lambda p, t: _via_relay(p, t),
    "groq": lambda p, t: _via_groq(p, t),
    "openrouter": lambda p, t: _via_openrouter(p, t),
    "claude": lambda p, t: _via_claude(p, t),
}


def _record(hop: str, outcome: str, seconds: float | None = None) -> None:
    try:
        from app.telemetry.metrics import record_moderation_hop

        record_moderation_hop(hop, outcome, seconds)
    except Exception:  # noqa: BLE001 - metrics are best-effort
        pass


def _try_hop(hop: str, prompt: str, timeout_s: float, external_id: str) -> ModerationResult:
    start = time.perf_counter()
    try:
        result = _CALL[hop](prompt, timeout_s)
    except ModerationRateLimited as exc:
        window = moderation_cooldown.trip(hop, exc.retry_after_s)
        _record(hop, "rate_limited", time.perf_counter() - start)
        logger.warning(
            f"moderation hop={hop} rate limited, cooling down {window:.0f}s "
            f"request_id={external_id}"
        )
        raise
    except ModerationUnavailable as exc:
        _record(hop, "error", time.perf_counter() - start)
        logger.warning(f"moderation hop={hop} failed request_id={external_id}: {exc}")
        raise
    _record(hop, result.decision, time.perf_counter() - start)
    return result


def check(prompt: str, *, external_id: str = "", timeout_s: float) -> ModerationResult:
    """Classify ``prompt`` via the first healthy hop. Raises ``ModerationUnavailable``."""
    errors: list[str] = []
    for hop in HOPS:
        if not _ENABLED[hop]():
            continue
        if moderation_cooldown.active(hop):
            _record(hop, "cooldown_skip")
            errors.append(f"{hop}: cooling down")
            continue
        try:
            return _try_hop(hop, prompt, timeout_s, external_id)
        except ModerationUnavailable as exc:
            errors.append(f"{hop}: {exc}")
    if not errors:
        raise ModerationUnavailable(
            "no moderation transport configured "
            "(Relay, GROQ_API_KEY, OPENROUTER_API_KEY or ANTHROPIC_API_KEY)"
        )
    raise ModerationUnavailable("; ".join(errors))
