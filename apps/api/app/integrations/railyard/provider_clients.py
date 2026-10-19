"""The only module that imports model-provider SDKs (Wave P PM1.5, the Relay boundary).

Every LLM call reaches a model through Relay on Claude credits. Code that
needs an OpenAI-shaped client, the Gemini client, DashScope or LiteLLM gets
it here; with ``RAILYARD_LIVE=1`` (production) a client for an LLM that does
not point at Relay is refused with :class:`DirectProviderBlocked`, and the
caller falls back to its deterministic path. Speech providers (text to
speech) are not LLM calls and stay allowed with ``purpose=SPEECH``.

With ``RAILYARD_LIVE`` unset (development, self-hosting) every client is built
exactly as before. ``tests/reelforge/test_wp_pm1_5_railyard.py`` fails when any
module under ``app/`` imports a provider SDK outside this file and
``app/domains/railyard/``.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from openai.types.chat import ChatCompletion

from .contract import railyard_live, relay_url

LLM = "llm"
SPEECH = "speech"


class DirectProviderBlocked(RuntimeError):
    """A direct LLM client was asked for while Relay is the only allowed path."""


def relay_only() -> bool:
    return railyard_live(os.environ) or (os.environ.get("MENIVOR_LLM_RELAY_ONLY") or "").strip().lower() in {
        "1", "true", "yes", "on"}


def _points_at_relay(base_url: Optional[str]) -> bool:
    relay = relay_url(os.environ)
    return bool(relay and base_url and str(base_url).rstrip("/").startswith(relay))


def check(purpose: str, base_url: Optional[str], provider: str) -> None:
    if purpose == LLM and relay_only() and not _points_at_relay(base_url):
        raise DirectProviderBlocked(
            f"{provider}: LLM calls go through Relay in production (RAILYARD_LIVE=1); "
            "set RELAY_URL or use the deterministic fallback"
        )


def OpenAI(*, api_key: Any = None, base_url: Optional[str] = None, purpose: str = LLM, **kwargs: Any) -> Any:  # noqa: N802
    check(purpose, base_url, "openai-compatible")
    from openai import OpenAI as _OpenAI

    return _OpenAI(api_key=api_key, base_url=base_url, **kwargs)


def AzureOpenAI(**kwargs: Any) -> Any:  # noqa: N802
    check(kwargs.pop("purpose", LLM), None, "azure")
    from openai import AzureOpenAI as _AzureOpenAI

    return _AzureOpenAI(**kwargs)


def genai_modules(*, purpose: str = LLM, base_url: Optional[str] = None) -> tuple[Any, Any]:
    """``(google.genai, google.genai.types)``."""
    check(purpose, base_url, "gemini")
    from google import genai
    from google.genai import types

    return genai, types


def dashscope_modules() -> tuple[Any, Any]:
    """``(dashscope, GenerationResponse)``."""
    check(LLM, None, "qwen")
    import dashscope
    from dashscope.api_entities.dashscope_response import GenerationResponse

    return dashscope, GenerationResponse


def litellm_module() -> Any:
    check(LLM, None, "litellm")
    import litellm

    return litellm


__all__ = [
    "LLM", "SPEECH", "AzureOpenAI", "ChatCompletion", "DirectProviderBlocked", "OpenAI", "check",
    "dashscope_modules", "genai_modules", "litellm_module", "relay_only",
]
