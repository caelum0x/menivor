"""Mint entitlement reconcile (MV13, Wave P PM3.2): every 15 minutes, catch up events a webhook missed.

For each channel that sells something, read the recent entitlement events from
Mint and apply the ones not seen yet (each event id is applied once, so this
never double-grants). Never raises.
"""

from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app

RECONCILE_TASK = "app.domains.ott_commerce.tasks.reconcile_task"
BEAT_SCHEDULE: dict[str, dict] = {"menivor-ott-mint-reconcile": {"task": RECONCILE_TASK, "schedule": 15 * 60.0}}


def reconcile(session, mint) -> dict[str, int]:
    from sqlalchemy import distinct, select

    from . import entitlements, products
    from .models import OttMintEvent, OttOffer

    counts = {"channels": 0, "applied": 0}
    for channel_id in session.execute(select(distinct(OttOffer.channel_id))).scalars().all():
        counts["channels"] += 1
        try:
            events = mint.entitlements(products.seller_id(channel_id))
        except products.CommerceError as exc:
            logger.warning(f"ott reconcile: channel {channel_id} skipped: {exc.code}")
            continue
        for event in sorted(events, key=lambda e: int(e.get("occurred_at_ms") or 0)):
            if session.get(OttMintEvent, str(event.get("id") or "")) is not None:
                continue
            kind = "entitlement.granted" if event.get("kind") == "granted" else "entitlement.revoked"
            outcome = entitlements.apply_event(session, kind, event)
            if outcome != "duplicate" and not outcome.startswith(("ignored", "refused")):
                counts["applied"] += 1
    session.flush()
    return counts


def run() -> dict[str, int]:
    from app.domains.ott import flags
    from app.models.db.base import get_session

    from .products import MintSellers

    if not flags.enabled("commerce"):
        return {"channels": 0, "applied": 0}
    mint = MintSellers()
    if not mint.configured:
        return {"channels": 0, "applied": 0}
    with get_session() as session:
        return reconcile(session, mint)


@celery_app.task(name=RECONCILE_TASK)
def reconcile_task() -> dict[str, int]:
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - a beat tick never crashes the worker
        logger.error(f"ott mint reconcile failed: {exc}")
        return {"channels": 0, "applied": 0}


__all__ = ["BEAT_SCHEDULE", "RECONCILE_TASK", "reconcile", "reconcile_task", "run"]
