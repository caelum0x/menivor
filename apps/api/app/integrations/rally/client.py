"""Tiny server-to-server client for Rally's lifecycle event API.

``POST {RALLY_EVENTS_URL}/api/autogtm/events`` with ``Authorization: Bearer
rly_evt_...``. Body is one event or ``{"batch": [...]}`` (max 100). Event shape
(see vcglass ``lib/autogtm/journeys/ingest.ts``)::

    {"event": "signed_up", "userId": "u_1", "email": "a@b.com",
     "traits": {...}, "properties": {...},
     "consent": {"email": true, "source": "..."},   # only when explicitly known
     "idempotencyKey": "signed_up:u_1", "timestamp": "2026-09-25T10:00:00+00:00",
     "source": "menivor"}

Rules: OFF unless configured; fire-and-forget from a small background pool;
every failure is logged and swallowed so Rally can never block or fail a user
action. Never call this from browsers or mobile clients (the key is secret).
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .settings import Env, RallySettings, load_settings

MAX_BATCH = 100

Transport = Callable[[str, Dict[str, str], Dict[str, Any], float], int]

_LOCK = threading.Lock()
_executor: Optional[ThreadPoolExecutor] = None
_pending: List[Future] = []


def build_event(
    *,
    event: str,
    user_id: str,
    idempotency_key: str,
    source: str,
    email: Optional[str] = None,
    traits: Optional[Dict[str, Any]] = None,
    properties: Optional[Dict[str, Any]] = None,
    consent: Optional[bool] = None,
    consent_source: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build one event dict (pure). ``consent=None`` leaves Rally consent unchanged."""
    ts = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
    body: Dict[str, Any] = {
        "event": event,
        "userId": str(user_id),
        "idempotencyKey": idempotency_key[:200],
        "timestamp": ts.isoformat(),
        "source": source,
    }
    if email:
        body["email"] = email.strip().lower()
    if traits:
        body["traits"] = dict(traits)
    if properties:
        body["properties"] = dict(properties)
    if consent is not None:
        body["consent"] = {"email": bool(consent), **({"source": consent_source} if consent_source else {})}
    return body


def _httpx_transport(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> int:
    import httpx

    resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
    return int(resp.status_code)


def send_events(
    events: List[Dict[str, Any]],
    *,
    settings: Optional[RallySettings] = None,
    transport: Optional[Transport] = None,
) -> bool:
    """Send events synchronously. Returns True on HTTP 2xx; never raises."""
    settings = settings or load_settings()
    if not settings.enabled or not events:
        return False
    send = transport or _httpx_transport
    headers = {"Authorization": f"Bearer {settings.key}", "Content-Type": "application/json"}
    ok = True
    try:
        for start in range(0, len(events), MAX_BATCH):
            chunk = events[start : start + MAX_BATCH]
            body = chunk[0] if len(chunk) == 1 else {"batch": chunk}
            status = send(settings.events_url, headers, body, settings.timeout_s)
            if status < 200 or status >= 300:
                ok = False
                logger.warning(f"rally events: HTTP {status} for {len(chunk)} event(s)")
    except Exception as exc:  # noqa: BLE001 - best-effort only
        logger.warning(f"rally events: send failed: {type(exc).__name__}: {exc}")
        return False
    return ok


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _LOCK:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rally-events")
        return _executor


def submit(job: Callable[[], Any], *, sync: bool = False) -> None:
    """Run ``job`` off-thread (or inline when ``sync``); swallow every error."""

    def _safe() -> None:
        try:
            job()
        except Exception as exc:  # noqa: BLE001 - best-effort only
            logger.warning(f"rally events: job failed: {type(exc).__name__}: {exc}")

    if sync:
        _safe()
        return
    try:
        fut = _pool().submit(_safe)
    except Exception as exc:  # noqa: BLE001 - pool shut down at interpreter exit
        logger.debug(f"rally events: could not queue: {exc}")
        return
    with _LOCK:
        _pending[:] = [f for f in _pending if not f.done()]
        _pending.append(fut)


def flush(timeout: float = 10.0) -> None:
    """Wait for queued sends (tests / graceful shutdown)."""
    with _LOCK:
        pending = list(_pending)
    for fut in pending:
        try:
            fut.result(timeout=timeout)
        except Exception:  # noqa: BLE001
            pass


def reset_for_tests() -> None:
    global _executor
    flush()
    with _LOCK:
        _pending.clear()
        if _executor is not None:
            _executor.shutdown(wait=True)
        _executor = None


def enabled(env: Optional[Env] = None) -> bool:
    return load_settings(env).enabled
