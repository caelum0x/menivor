"""Helpers shared by every prompt-moderation hop (OpenAI-compatible and Claude).

Env lookup, the user message wrapper, the HTTP call (429 -> ``ModerationRateLimited``)
and strict validation of the model's JSON answer ``{decision, categories[], rationale}``.
Nothing here logs prompt text or the model's rationale.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from app.core.moderation_policy import CATEGORIES
from app.core.moderation_types import DECISIONS, ModerationRateLimited, ModerationUnavailable

DEFAULT_MAX_TOKENS = 400
ALWAYS_DENY = frozenset({"minors"})
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def env(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def max_tokens() -> int:
    raw = env("MENIVOR_MODERATION_MAX_TOKENS")
    try:
        return max(128, int(raw)) if raw else DEFAULT_MAX_TOKENS
    except ValueError:
        return DEFAULT_MAX_TOKENS


def reasoning_effort() -> str:
    value = env("MENIVOR_MODERATION_REASONING_EFFORT").lower()
    return value if value in {"low", "medium", "high"} else "low"


def user_message(prompt: str) -> str:
    return f"Content to classify:\n\n{prompt}"


def _retry_after(response: Any) -> float | None:
    headers = getattr(response, "headers", None) or {}
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        return float(raw) if raw else None
    except (TypeError, ValueError, AttributeError):
        return None


def post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float) -> Any:
    """POST ``body`` and return the decoded JSON. Raises ``ModerationUnavailable``."""
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise ModerationUnavailable(f"transport: {type(exc).__name__}") from exc
    if response.status_code == 429:
        raise ModerationRateLimited("status 429", _retry_after(response))
    if response.status_code != 200:
        raise ModerationUnavailable(f"status {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ModerationUnavailable("malformed completion body") from exc


def parse_decision(content: Any) -> tuple[str, tuple[str, ...]]:
    """Validate the model's JSON answer. Raises ``ModerationUnavailable``."""
    if not isinstance(content, str) or not content.strip():
        raise ModerationUnavailable("empty model answer")
    text = content.strip()
    try:
        data = json.loads(text)
    except ValueError:
        match = _JSON_OBJECT.search(text)
        if not match:
            raise ModerationUnavailable("model answer is not JSON") from None
        try:
            data = json.loads(match.group(0))
        except ValueError as exc:
            raise ModerationUnavailable("model answer is not JSON") from exc
    if not isinstance(data, dict):
        raise ModerationUnavailable("model answer is not an object")
    decision = str(data.get("decision") or "").strip().lower()
    if decision not in DECISIONS:
        raise ModerationUnavailable(f"unexpected decision {decision[:16]!r}")
    raw_categories = data.get("categories") or []
    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]
    if not isinstance(raw_categories, list):
        raise ModerationUnavailable("categories is not a list")
    categories = tuple(
        sorted({str(c).strip().lower() for c in raw_categories} & CATEGORIES)
    )
    if ALWAYS_DENY.intersection(categories):
        decision = "deny"
    return decision, categories
