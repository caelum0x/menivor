"""Claude (Anthropic Messages API) hop: last resort of the moderation chain.

Same policy in the system prompt, same JSON contract ``{decision, categories[],
rationale}`` validated by ``moderation_common.parse_decision``, temperature 0.
Enabled when ``ANTHROPIC_API_KEY`` is set. Model override:
``MENIVOR_MODERATION_CLAUDE_MODEL`` (default ``claude-haiku-4-5-20251001``).
"""

from __future__ import annotations

from typing import Any

from app.core.moderation_common import env, max_tokens, parse_decision, post_json, user_message
from app.core.moderation_policy import POLICY_TEXT
from app.core.moderation_types import ModerationUnavailable

URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def api_key() -> str:
    return env("ANTHROPIC_API_KEY")


def model_id() -> str:
    return env("MENIVOR_MODERATION_CLAUDE_MODEL") or DEFAULT_MODEL


def build_body(prompt: str) -> dict[str, Any]:
    return {
        "model": model_id(),
        "max_tokens": max_tokens(),
        "temperature": 0,
        "system": POLICY_TEXT,
        "messages": [{"role": "user", "content": user_message(prompt)}],
    }


def extract_text(data: Any) -> str:
    try:
        blocks = data["content"]
    except (KeyError, TypeError) as exc:
        raise ModerationUnavailable("malformed completion body") from exc
    if not isinstance(blocks, list):
        raise ModerationUnavailable("malformed completion body")
    return "".join(
        str(b.get("text") or "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
    )


def classify(prompt: str, timeout_s: float) -> tuple[str, tuple[str, ...]]:
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key(),
        "anthropic-version": API_VERSION,
    }
    data = post_json(URL, headers, build_body(prompt), timeout_s)
    return parse_decision(extract_text(data))
