"""Client for Rally Send's transactional API (dispatch contract 5.2).

``POST {RALLY_TX_URL}/api/rally/v1/transactional/send`` with
``Authorization: Bearer {RALLY_TX_KEY}``. Body::

    {product, project, to, from_local, subject, html, text,
     idempotency_key, unsubscribe_url?, tags?}

``from_local`` is joined by Rally to Menivor's transactional domain
(``mail.menivor.com``); the caller never names a cold domain.

Answers: ``202 {id}`` (the same id for a repeated idempotency key), ``429``
when the per-project cap is hit (retry later), ``422`` for a suppressed
address (never retry). Unset ``RALLY_TX_URL`` means "not configured": the
caller uses its current mail path (X11 fallback). Never raises.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

SEND_PATH = "/api/rally/v1/transactional/send"
PRODUCT = "menivor"
PROJECT = "menivor"
FROM_LOCAL = "hello"
TIMEOUT_S = 10.0

SENT = "sent"
RETRY = "retry"          # 429 or a transport error: try again on a later tick
SUPPRESSED = "suppressed"  # 422: Rally holds the address as suppressed
FAILED = "failed"          # any other answer

#: ``(url, headers, json_body, timeout) -> (status_code, json)``
Transport = Callable[[str, dict[str, str], dict[str, Any], float], tuple[int, dict[str, Any]]]


@dataclass(frozen=True)
class TxResult:
    outcome: str
    message_id: str = ""
    status: int = 0


def configured() -> bool:
    return bool(_url() and _key())


def _url() -> str:
    return (os.getenv("RALLY_TX_URL") or "").strip().rstrip("/")


def _key() -> str:
    return (os.getenv("RALLY_TX_KEY") or "").strip()


def endpoint() -> str:
    base = _url()
    return base if base.endswith("/send") else f"{base}{SEND_PATH}"


def idempotency_key(user_id: str, step: str) -> str:
    """One key per user and step, so a retried tick never sends twice."""
    return f"menivor:onboarding:{user_id}:{step}"[:200]


def build_body(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    key: str,
    unsubscribe_url: str = "",
    tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "product": PRODUCT,
        "project": PROJECT,
        "to": to,
        "from_local": FROM_LOCAL,
        "subject": subject,
        "html": html,
        "text": text,
        "idempotency_key": key,
    }
    if unsubscribe_url:
        body["unsubscribe_url"] = unsubscribe_url
    if tags:
        body["tags"] = list(tags)
    return body


def _httpx_transport(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float):
    import httpx

    resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return resp.status_code, data if isinstance(data, dict) else {}


def send(body: dict[str, Any], transport: Transport | None = None) -> TxResult:
    """Send one transactional message. Never raises."""
    if not configured():
        return TxResult(FAILED)
    headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}
    try:
        status, data = (transport or _httpx_transport)(endpoint(), headers, body, TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - network trouble is a retry, not a crash
        logger.warning(f"rally tx: send failed ({type(exc).__name__}); will retry")
        return TxResult(RETRY)
    if status in (200, 202):
        return TxResult(SENT, message_id=str(data.get("id") or ""), status=status)
    if status == 429:
        return TxResult(RETRY, status=status)
    if status == 422:
        return TxResult(SUPPRESSED, status=status)
    logger.warning(f"rally tx: unexpected status {status}")
    return TxResult(FAILED, status=status)
