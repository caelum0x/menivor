"""LLM port: ``complete(system, prompt) -> str`` through Relay on Claude credits only.

The agent uses an LLM only when Railyard Relay is configured (``RELAY_URL`` /
``RAILYARD_RELAY_URL``), so every call is billed to the Anthropic credits behind
Relay and capped by Relay. No direct paid provider is ever called from here.
When Relay is not configured :func:`get_port` returns ``None`` and the agent runs
its deterministic path (site facts + templates), which costs nothing.

Model: ``BRAND_AGENT_LLM_MODEL`` (default ``claude-haiku-4-5-20251001``).
"""

from __future__ import annotations

import os
from typing import Protocol

from loguru import logger

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_PROMPT_CHARS = 24_000


class LLMPort(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class RelayLLM:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("BRAND_AGENT_LLM_MODEL") or DEFAULT_MODEL

    def complete(self, system: str, prompt: str) -> str:
        from app.domains.railyard import run_chat_text
        from app.integrations.railyard import relay_env

        text = f"{system}\n\n{prompt}"[:MAX_PROMPT_CHARS]
        try:
            return run_chat_text(prompt=text, model=self.model, relay_provider="anthropic", env=relay_env()) or ""
        except Exception as exc:  # noqa: BLE001 - the agent falls back to its deterministic path
            logger.warning(f"brand agent relay call failed: {type(exc).__name__}")
            return ""


def relay_configured() -> bool:
    try:
        from app.domains.railyard import is_relay_enabled
        from app.integrations.railyard import relay_env

        return bool(is_relay_enabled(relay_env()))
    except Exception:  # noqa: BLE001 - unknown == not configured
        return False


def get_port() -> LLMPort | None:
    return RelayLLM() if relay_configured() else None


__all__ = ["DEFAULT_MODEL", "LLMPort", "RelayLLM", "get_port", "relay_configured"]
