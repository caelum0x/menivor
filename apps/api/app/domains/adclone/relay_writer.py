"""The Ad Clone LLM step, routed through Railyard Relay only (Anthropic credits held by Relay).

``relay_llm()`` returns a ``prompt -> text`` callable when Relay is configured (``RELAY_URL`` /
``RAILYARD_RELAY_URL`` + key), else ``None``. Callers then use the template writer and say so
(:data:`NOT_CONFIGURED_NOTE`). There is deliberately no direct-provider fallback here: the
owner rule is that this product's LLM spend goes through Relay.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

DEFAULT_MODEL = "claude-sonnet-5"
MODEL_ENV = "ADCLONE_LLM_MODEL"
NOT_CONFIGURED_NOTE = ("writer: template lines (Relay is not configured, so the LLM step was skipped; set RELAY_URL "
                       "and RELAY_API_KEY to write new lines and other languages with Claude through Relay)")
FAILED_NOTE = "writer: template lines (the Relay LLM answer was unusable or copied the source)"

Chat = Callable[..., str]


def relay_configured(env: Mapping[str, str] | None = None) -> bool:
    try:
        from app.domains.railyard import is_relay_enabled
        from app.integrations.railyard import relay_env
    except Exception:  # noqa: BLE001 - Railyard package absent: not configured
        return False
    return bool(is_relay_enabled(relay_env(env)))


def relay_llm(env: Mapping[str, str] | None = None, *, chat: Chat | None = None) -> Callable[[str], str] | None:
    """A Relay-backed ``prompt -> text`` callable, or ``None`` when Relay is not configured."""
    if not relay_configured(env):
        return None
    from app.integrations.railyard import relay_env

    if chat is None:
        from app.domains.railyard import run_chat_text as chat
    renv = relay_env(env)
    model = ((env if env is not None else os.environ).get(MODEL_ENV) or DEFAULT_MODEL).strip()

    def call(prompt: str) -> str:
        return chat(prompt=prompt, model=model, relay_provider="anthropic", temperature=0.7, env=renv)

    return call
