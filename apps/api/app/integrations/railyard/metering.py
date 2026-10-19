"""Usage metering from Menivor to Railyard Rago (per render, per LLM call).

Rago is Railyard's Lago-compatible billing engine. Each settled render and each
Relay-routed LLM call becomes one usage event (``POST /api/v1/events``) so Rago
can rate it: for our own portfolio against one internal subscription, and for
customers against their own subscription (see ``settings.subscription_for``).

Rules:

* OFF unless ``RAILYARD_RAGO_URL`` + ``RAILYARD_RAGO_API_KEY`` are set; then
  every call is a cheap no-op returning ``False``.
* Best-effort: failures are logged and swallowed; metering never fails a render
  or an LLM call. The money rail (Mint / local ledger) stays the source of truth.
* Non-blocking by default: events are sent from a small background pool so a
  slow Rago never adds latency to settlement. ``sync=True`` sends inline.
* Idempotent: a render's ``transaction_id`` is ``<job_id>:render``, so a job
  settled twice is metered once (Rago dedupes on subscription + transaction id).

The event transport reuses ``app.domains.wallet.rago_client.RagoClient``.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol, Tuple

from loguru import logger

from .settings import Env, RailyardSettings, load_settings

MICROS_PER_CENT = 10_000


class EventSink(Protocol):
    def record_event(
        self,
        *,
        code: str,
        transaction_id: str,
        external_subscription_id: str,
        properties: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
        precise_total_amount_cents: Optional[str] = None,
    ) -> Any: ...


@dataclass(frozen=True)
class UsageEvent:
    code: str
    transaction_id: str
    external_subscription_id: str
    properties: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    precise_total_amount_cents: Optional[str] = None


_LOCK = threading.Lock()
_clients: Dict[Tuple[str, str, float], EventSink] = {}
_executor: Optional[ThreadPoolExecutor] = None
_pending: List[Future] = []


def _client_for(settings: RailyardSettings) -> EventSink:
    from app.domains.wallet.rago_client import RagoClient

    key = (settings.rago_url or "", settings.rago_api_key or "", settings.timeout_s)
    with _LOCK:
        client = _clients.get(key)
        if client is None:
            client = RagoClient(key[0], key[1], timeout=settings.timeout_s)
            _clients[key] = client
        return client


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _LOCK:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="railyard-meter")
        return _executor


def _send(sink: EventSink, event: UsageEvent) -> bool:
    try:
        sink.record_event(
            code=event.code,
            transaction_id=event.transaction_id,
            external_subscription_id=event.external_subscription_id,
            properties=event.properties,
            timestamp=event.timestamp,
            precise_total_amount_cents=event.precise_total_amount_cents,
        )
        logger.debug(f"railyard metering: sent {event.code} {event.transaction_id}")
        return True
    except Exception as exc:  # noqa: BLE001 - metering must never fail the caller
        logger.warning(
            f"railyard metering: {event.code} {event.transaction_id} not recorded (ignored): {exc}"
        )
        return False


def emit(
    event: UsageEvent,
    *,
    settings: Optional[RailyardSettings] = None,
    sink: Optional[EventSink] = None,
    sync: bool = False,
) -> bool:
    """Send one usage event. Returns ``True`` when it was sent (sync) or queued."""
    settings = settings or load_settings()
    if not settings.metering_enabled:
        return False
    try:
        target = sink or _client_for(settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"railyard metering: client unavailable (ignored): {exc}")
        return False
    if sync:
        return _send(target, event)
    future = _pool().submit(_send, target, event)
    with _LOCK:
        _pending[:] = [f for f in _pending if not f.done()]
        _pending.append(future)
    return True


def flush(timeout: float = 5.0) -> None:
    """Wait for queued events (tests, graceful shutdown)."""
    with _LOCK:
        pending = list(_pending)
    deadline = time.monotonic() + timeout
    for future in pending:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            future.result(timeout=remaining)
        except Exception:  # noqa: BLE001 - already logged in _send
            pass


def meter_render(
    *,
    job_id: str,
    owner_key: Optional[str],
    credits_micros: int,
    rail: str = "local",
    job_kind: Optional[str] = None,
    env: Optional[Env] = None,
    sink: Optional[EventSink] = None,
    sync: bool = False,
) -> bool:
    """Meter one settled render (reel / media job) and the credits it consumed.

    Rago binds each event code to one metric, so this sends two events:

    * ``render_metric`` (count, default ``reel_generated``), transaction
      ``<job_id>:render``;
    * ``credits_metric`` (sum of ``credits`` micros, default
      ``reel_ai_credits``), transaction ``<job_id>:settle`` -- the same id the
      legacy ``RAGO_URL`` settlement meter uses, so running both against one
      Rago subscription still counts the credits once.

    Returns ``True`` when both events were sent (sync) or queued.

    Wave P PM1.5: the contract events (``menivor.reel.rendered`` and, for a
    preset tile's render, ``menivor.preset.render``) are queued in the meter
    outbox first, whatever the legacy settings say; they are sent when
    ``RAILYARD_LIVE=1``.
    """
    from .meters import on_render_settled

    on_render_settled(job_id=job_id, owner_key=owner_key, job_kind=job_kind)
    settings = load_settings(env)
    if not settings.metering_enabled or not str(job_id or "").strip():
        return False
    subscription = settings.subscription_for(owner_key)
    if not subscription:
        logger.debug(f"railyard metering: no subscription for render {job_id}; skipped")
        return False
    micros = max(0, int(credits_micros or 0))
    common: Dict[str, Any] = {
        "job_id": str(job_id),
        "settlement_rail": str(rail),
        "owner": str(owner_key or ""),
    }
    if job_kind:
        common["job_kind"] = str(job_kind)
    render = UsageEvent(
        code=settings.render_metric,
        transaction_id=f"{job_id}:render",
        external_subscription_id=subscription,
        properties={**common, "renders": 1},
    )
    credits = UsageEvent(
        code=settings.credits_metric,
        transaction_id=f"{job_id}:settle",
        external_subscription_id=subscription,
        properties={**common, "credits": micros},
        precise_total_amount_cents=format(Decimal(micros) / Decimal(MICROS_PER_CENT), "f"),
    )
    sent_render = emit(render, settings=settings, sink=sink, sync=sync)
    sent_credits = emit(credits, settings=settings, sink=sink, sync=sync)
    return sent_render and sent_credits


def meter_llm_call(
    *,
    model: str,
    provider: str,
    prompt_chars: int,
    completion_chars: int,
    routed_via: str,
    owner_key: Optional[str] = None,
    request_id: Optional[str] = None,
    env: Optional[Env] = None,
    sink: Optional[EventSink] = None,
    sync: bool = False,
) -> bool:
    """Meter one LLM call. Token counts are recorded by Relay itself; this
    event gives Rago the per-product call count and payload sizes."""
    settings = load_settings(env)
    if not settings.metering_enabled:
        return False
    subscription = settings.subscription_for(owner_key)
    if not subscription:
        return False
    event = UsageEvent(
        code=settings.llm_metric,
        transaction_id=f"llm:{request_id or uuid.uuid4().hex}",
        external_subscription_id=subscription,
        properties={
            "calls": 1,
            "model": str(model),
            "provider": str(provider),
            "prompt_chars": max(0, int(prompt_chars)),
            "completion_chars": max(0, int(completion_chars)),
            "routed_via": str(routed_via),
        },
    )
    return emit(event, settings=settings, sink=sink, sync=sync)


def reset_for_tests() -> None:
    """Drop cached clients and pending futures."""
    with _LOCK:
        _clients.clear()
        _pending.clear()
