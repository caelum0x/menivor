"""Rago meters and the Mint mirror for Menivor, through one outbox (contract 5.3).

Every usage event is written to ``railyard_meter_outbox`` in the contract
shape (``contract.rago_event``) with its ``<product>:<meter>:<source id>``
transaction id as the unique key, so a repeated event is a no-op here and in
Rago. :func:`flush` sends pending rows only when ``RAILYARD_LIVE=1`` and the
target is configured; failures keep the row with its attempt count and error
for the next beat (``tasks.py``, every 5 minutes).

Emitters:
* :func:`on_render_settled` (called from ``metering.meter_render`` for every
  settled render): ``menivor.reel.rendered`` and, for a render a preset tile
  started, ``menivor.preset.render``;
* :func:`lora_train` (My characters training start): ``menivor.lora.train``;
* :func:`mirror_dodo_payment` and :func:`mirror_dodo_refund` (the Dodo
  webhook): Mint ledger entries, channel ``mint``. They are records only:
  nothing here mints tokens, moves balances or pays anyone out.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import JSON, DateTime, Integer, String, Text, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.db.base import Base

from . import contract

CHANNEL_RAGO = "rago"
CHANNEL_MINT = "mint"
SEND_TIMEOUT_S = 5.0
Post = Callable[[str, Mapping[str, Any], Mapping[str, str]], int]


class MeterOutbox(Base):
    __tablename__ = "railyard_meter_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default=CHANNEL_RAGO)
    transaction_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")


def _insert(session: Session, channel: str, transaction: str, payload: Mapping[str, Any]) -> bool:
    """Queue one row in a savepoint. Never raises: metering never fails the paid action around it."""
    try:
        with session.begin_nested():
            exists = session.execute(
                select(MeterOutbox.id).where(MeterOutbox.transaction_id == transaction)
            ).first()
            if exists is not None:
                return False
            session.add(MeterOutbox(channel=channel, transaction_id=transaction, payload=dict(payload)))
        return True
    except IntegrityError:
        return False
    except SQLAlchemyError as exc:
        logger.warning(f"railyard meters: {transaction} not queued: {type(exc).__name__}")
        return False


def record(
    session: Session,
    *,
    code: str,
    source_id: str,
    customer: str,
    properties: Optional[Mapping[str, Any]] = None,
    transaction: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> bool:
    """Queue one Rago event; ``False`` when that transaction id is already queued."""
    event = contract.rago_event(code=code, source_id=source_id, customer=customer, timestamp=timestamp,
                                properties=properties, transaction=transaction)
    return _insert(session, CHANNEL_RAGO, event["transaction_id"], event)


def _default_post(url: str, body: Mapping[str, Any], headers: Mapping[str, str]) -> int:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_S) as response:  # noqa: S310 - configured Railyard URL
        return int(response.status)


def _target(channel: str, env: Mapping[str, Optional[str]]) -> tuple[str, dict[str, str]] | None:
    if channel == CHANNEL_MINT:
        url, key, path = contract.mint_target(env)
        if not (url and key and path):
            return None
        return f"{url}/{path.lstrip('/')}", {"Authorization": f"Bearer {key}"}
    url, key = contract.rago_target(env)
    if not (url and key):
        return None
    return f"{url}{contract.RAGO_EVENTS_PATH}", {"Authorization": f"Bearer {key}"}


def flush(
    session: Session,
    *,
    post: Optional[Post] = None,
    env: Optional[Mapping[str, Optional[str]]] = None,
    channel: str = CHANNEL_RAGO,
    limit: int = 200,
) -> int:
    """Send pending rows of ``channel``; returns how many were delivered."""
    env = env if env is not None else os.environ
    if not contract.railyard_live(env):
        return 0
    target = _target(channel, env)
    if target is None:
        return 0
    url, headers = target
    send = post or _default_post
    rows = session.execute(
        select(MeterOutbox).where(MeterOutbox.channel == channel, MeterOutbox.sent_at.is_(None))
        .order_by(MeterOutbox.id).limit(limit)
    ).scalars().all()
    delivered = 0
    for row in rows:
        body = {"event": row.payload} if channel == CHANNEL_RAGO else row.payload
        try:
            status = int(send(url, body, headers))
            if not 200 <= status < 300:
                raise RuntimeError(f"HTTP {status}")
        except Exception as exc:  # noqa: BLE001 - keep the row for the next beat
            row.attempts = int(row.attempts or 0) + 1
            row.last_error = f"{type(exc).__name__}: {exc}"[:500]
            continue
        row.sent_at = datetime.now(timezone.utc)
        row.attempts = int(row.attempts or 0) + 1
        row.last_error = ""
        delivered += 1
    session.flush()
    return delivered


# --------------------------------------------------------------------------- #
# Emitters
# --------------------------------------------------------------------------- #
def on_render_settled(*, job_id: str, owner_key: Optional[str], job_kind: Optional[str] = None) -> int:
    """Queue the contract events for one settled render. Best-effort; never raises."""
    if not str(job_id or "").strip():
        return 0
    try:
        from app.models.db.base import get_session
        from app.models.db.models import Job

        with get_session() as session:
            job = session.get(Job, job_id)
            params = dict(job.params or {}) if job is not None else {}
            customer = str(owner_key or (job.user_id if job is not None else "") or "")
            kind = str(job_kind or (job.kind if job is not None else "") or "")
            count = int(record(session, code=contract.REEL_RENDERED, source_id=job_id, customer=customer,
                               properties={"job_kind": kind}))
            run = params.get("preset_run")
            if isinstance(run, Mapping) and run.get("preset_id"):
                count += int(record(session, code=contract.PRESET_RENDER, source_id=job_id, customer=customer,
                                    properties={"preset_id": str(run["preset_id"])}))
            return count
    except Exception as exc:  # noqa: BLE001 - metering never fails a render
        logger.warning(f"railyard meters: render {job_id} not queued: {type(exc).__name__}: {exc}")
        return 0


def lora_train(session: Session, *, job_id: str, customer: str, credits: int) -> bool:
    return record(session, code=contract.LORA_TRAIN, source_id=job_id, customer=customer,
                  properties={"ai_video_credits": int(credits)})


def mirror_dodo_payment(session: Session, view: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    """A Mint ledger entry for a Dodo credit or pack payment (record only)."""
    payment_id = str(view.get("payment_id") or "").strip()
    if not payment_id:
        return False
    metadata = view.get("metadata") or {}
    entry = {
        "entry_id": f"{contract.PRODUCT}:dodo:{payment_id}",
        "type": "payment.succeeded",
        "external_customer_id": str(metadata.get("user_id") or ""),
        "amount_cents": int(view.get("total_amount") or view.get("amount") or 0),
        "currency": str(view.get("currency") or "USD"),
        "credits": int(result.get("credits") or 0),
        "product": str(result.get("plan_key") or ""),
        "source": "dodo",
    }
    return _insert(session, CHANNEL_MINT, entry["entry_id"], entry)


def mirror_dodo_refund(session: Session, payment_id: str, result: Mapping[str, Any]) -> bool:
    pid = str(payment_id or "").strip()
    if not pid:
        return False
    entry = {
        "entry_id": f"{contract.PRODUCT}:dodo:{pid}:refund",
        "type": "refund.succeeded",
        "external_customer_id": str(result.get("user_id") or ""),
        "credits_reversed": int(result.get("debited") or 0),
        "payment_entry_id": f"{contract.PRODUCT}:dodo:{pid}",
        "source": "dodo",
    }
    return _insert(session, CHANNEL_MINT, entry["entry_id"], entry)


def mirror_now(kind: str, *args: Any) -> bool:
    """Webhook-side helper: record a mirror entry in its own session; never raises."""
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            fn = mirror_dodo_payment if kind == "payment" else mirror_dodo_refund
            return fn(session, *args)
    except Exception as exc:  # noqa: BLE001 - the payment rail stays the record of truth
        logger.warning(f"mint mirror ({kind}) not recorded: {type(exc).__name__}: {exc}")
        return False
