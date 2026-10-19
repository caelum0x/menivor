"""Creem Moderation API provider (kept available, not the default).

Selected with ``MENIVOR_MODERATION_PROVIDER=creem``. Needs ``CREEM_API_KEY``
(``creem_`` live, ``creem_test_`` sandbox); ``CREEM_MODERATION_URL`` overrides
the endpoint. See https://docs.creem.io/features/moderation.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.core.moderation_types import DECISIONS, ModerationResult, ModerationUnavailable

LIVE_URL = "https://api.creem.io/v1/moderation/prompt"
SANDBOX_URL = "https://test-api.creem.io/v1/moderation/prompt"
NAME = "creem"


def api_key() -> str:
    return (os.getenv("CREEM_API_KEY") or "").strip()


def configured() -> bool:
    return bool(api_key())


def endpoint(key: str) -> str:
    override = (os.getenv("CREEM_MODERATION_URL") or "").strip()
    if override:
        return override
    return SANDBOX_URL if key.startswith("creem_test_") else LIVE_URL


def check(prompt: str, *, external_id: str = "", timeout_s: float) -> ModerationResult:
    """Call the Creem Moderation API once. Raises ``ModerationUnavailable``."""
    key = api_key()
    if not key:
        raise ModerationUnavailable("CREEM_API_KEY is not configured")
    payload: dict[str, Any] = {"prompt": prompt}
    if external_id:
        payload["external_id"] = external_id[:128]
    try:
        response = httpx.post(
            endpoint(key),
            headers={"x-api-key": key, "content-type": "application/json"},
            json=payload,
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        raise ModerationUnavailable(f"transport: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise ModerationUnavailable(f"status {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ModerationUnavailable("non-json body") from exc
    decision = str((data or {}).get("decision") or "").lower()
    if decision not in DECISIONS:
        raise ModerationUnavailable(f"unexpected decision {decision!r}")
    return ModerationResult(
        decision=decision, moderation_id=str(data.get("id") or ""), provider=NAME
    )
