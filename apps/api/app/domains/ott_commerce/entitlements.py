"""Who may watch a paid title (MV13): the channel owner, or a viewer with a live entitlement.

* SVOD: an active subscription entitlement of the channel unlocks every paid
  title of that channel until it is revoked (refund, dispute, cancellation)
  or its period ends (``expires_at`` from the creator's processor, plus a
  one-day grace for renewals in flight). A subscription grant without a
  period end is refused and logged, never stored open-ended (P-M14).
* TVOD: a purchase unlocks exactly that title until it is revoked.
* Rental: a purchase unlocks exactly that title for the offer's rental hours
  from the moment it was granted; after that it has expired.

Mint's events (``entitlement.granted`` / ``entitlement.revoked``) are applied
once each (:class:`OttMintEvent`); the ``buyer_ref`` is the channel viewer id.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.ott.models import OttChannel, OttTitle

from .models import ACTIVE, KIND_RENTAL, KIND_SVOD, REVOKED, OttEntitlement, OttMintEvent, OttOffer
from .products import channel_from_seller

RENEWAL_GRACE = timedelta(days=1)
#: P-M14 (Wave Q QM1.0): an SVOD grant without a period end is refused, never stored open-ended.
REFUSED_NO_EXPIRY = "refused:svod_no_expiry"
REVOKE_REASONS = ("refund", "dispute", "cancelled", "expired")


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def live_entitlements(session: Session, viewer_id: str, channel_id: str, *,
                      at: Optional[datetime] = None) -> list[OttEntitlement]:
    moment = at or now()
    rows = session.execute(select(OttEntitlement).where(OttEntitlement.viewer_id == viewer_id,
                                                        OttEntitlement.channel_id == channel_id,
                                                        OttEntitlement.status == ACTIVE)).scalars().all()
    return [r for r in rows if _aware(r.expires_at) is None or _aware(r.expires_at) > moment]


def can_watch(session: Session, title: OttTitle, *, viewer_id: Optional[str] = None,
              user_id: Optional[str] = None, at: Optional[datetime] = None) -> bool:
    if title.access_tier == "free":
        return True
    channel = session.get(OttChannel, title.channel_id)
    if channel is not None and user_id and str(channel.user_id) == str(user_id):
        return True
    if not viewer_id:
        return False
    for ent in live_entitlements(session, viewer_id, title.channel_id, at=at):
        if ent.kind == KIND_SVOD or ent.title_id == title.id:
            return True
    return False


def subscribed(session: Session, viewer_id: str, channel_id: str) -> bool:
    return any(e.kind == KIND_SVOD for e in live_entitlements(session, viewer_id, channel_id))


def _ms(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc) if value is not None else None
    except (TypeError, ValueError, OSError):
        return None


def _record(session: Session, event_id: str, kind: str, outcome: str) -> bool:
    try:
        with session.begin_nested():
            session.add(OttMintEvent(id=event_id, kind=kind, outcome=outcome))
        return True
    except IntegrityError:
        return False


def apply_event(session: Session, event_type: str, data: Mapping[str, Any]) -> str:
    """Apply one Mint entitlement event; returns the outcome. Idempotent on the event id."""
    from app.domains.ott_viewers.models import OttViewer

    event_id = str(data.get("id") or "").strip()
    if not event_id or len(event_id) > 64:
        return "ignored:no_id"
    if session.get(OttMintEvent, event_id) is not None:
        return "duplicate"
    kind = "granted" if event_type == "entitlement.granted" else "revoked" if event_type == "entitlement.revoked" \
        else ""
    channel_id = channel_from_seller(str(data.get("seller") or ""))
    offer = session.execute(select(OttOffer).where(OttOffer.channel_id == channel_id,
                                                   OttOffer.sku == str(data.get("sku") or ""))).scalar_one_or_none()
    viewer = session.get(OttViewer, str(data.get("buyer_ref") or ""))
    if not kind:
        outcome = "ignored:type"
    elif offer is None:
        outcome = "ignored:unknown_offer"
    elif viewer is None or viewer.channel_id != channel_id:
        outcome = "ignored:unknown_viewer"
    elif kind == "granted":
        outcome = _grant(session, event_id, offer, viewer.id, data)
    else:
        outcome = _revoke(session, event_id, offer, viewer.id, str(data.get("reason") or ""), data)
    if outcome.startswith("refused:"):
        # Not recorded: the event id stays free so a corrected redelivery can still apply.
        logger.error(f"mint entitlement {event_id}: {outcome} (seller {data.get('seller')}, sku {data.get('sku')})")
        return outcome
    if not _record(session, event_id, kind or "other", outcome):
        return "duplicate"
    if outcome in ("granted", "renewed"):
        _announce(session, offer, viewer.id, event_id)
    return outcome


def _announce(session: Session, offer: OttOffer, viewer_id: str, event_id: str) -> None:
    """Wave Q QM1.5 (U39): ott.purchase.granted to the creator's webhooks, after commit."""
    from app.domains.ott import events

    ent = session.execute(select(OttEntitlement).where(
        OttEntitlement.viewer_id == viewer_id, OttEntitlement.offer_id == offer.id, OttEntitlement.status == ACTIVE)
        .order_by(OttEntitlement.granted_at.desc())).scalars().first()
    channel = session.get(OttChannel, offer.channel_id)
    if ent is None or channel is None:
        return
    eid, payload = events.purchase_granted(channel, offer, ent, event_id)
    events.queue(session, channel.id, events.PURCHASE_GRANTED, eid, payload)


def _revoked_after(session: Session, offer: OttOffer, viewer_id: str, moment: datetime) -> bool:
    """True when a refund, dispute or cancellation for this offer was applied after ``moment``.

    Verifier fix (Wave P P3): webhooks and the reconcile job can deliver a grant
    after the revoke that cancels it (a failed grant delivery retried after the
    refund). Such a late grant must not reopen access that was refunded.
    """
    rows = session.execute(select(OttEntitlement.revoked_at).where(
        OttEntitlement.viewer_id == viewer_id, OttEntitlement.offer_id == offer.id,
        OttEntitlement.status == REVOKED, OttEntitlement.revoked_at.is_not(None))).scalars().all()
    return any(_aware(r) is not None and _aware(r) >= moment for r in rows)


def _grant(session: Session, event_id: str, offer: OttOffer, viewer_id: str, data: Mapping[str, Any]) -> str:
    granted = _ms(data.get("occurred_at_ms")) or now()
    if _revoked_after(session, offer, viewer_id, granted):
        return "ignored:revoked_later"
    if offer.kind == KIND_RENTAL:
        expires = granted + timedelta(hours=offer.rental_hours or 48)
    elif offer.kind == KIND_SVOD:
        period_end = _ms(data.get("expires_at_ms"))
        if period_end is None:
            return REFUSED_NO_EXPIRY
        expires = period_end + RENEWAL_GRACE
        # A renewal extends the running subscription instead of stacking rows.
        running = session.execute(select(OttEntitlement).where(
            OttEntitlement.viewer_id == viewer_id, OttEntitlement.offer_id == offer.id,
            OttEntitlement.status == ACTIVE)).scalars().first()
        if running is not None:
            running.expires_at = expires
            session.flush()
            return "renewed"
    else:
        expires = None
    session.add(OttEntitlement(channel_id=offer.channel_id, viewer_id=viewer_id, offer_id=offer.id, kind=offer.kind,
                               title_id=offer.title_id, status=ACTIVE, granted_event_id=event_id,
                               granted_at=granted, expires_at=expires,
                               list_price_cents=int(offer.price_cents), list_currency=offer.currency))
    session.flush()
    return "granted"


def _revoke(session: Session, event_id: str, offer: OttOffer, viewer_id: str, reason: str,
            data: Mapping[str, Any]) -> str:
    moment = now()
    why = reason if reason in REVOKE_REASONS else "other"
    result = session.execute(
        update(OttEntitlement)
        .where(OttEntitlement.viewer_id == viewer_id, OttEntitlement.offer_id == offer.id,
               OttEntitlement.status == ACTIVE)
        .values(status=REVOKED, revoked_at=moment, revoked_reason=why)
    )
    if result.rowcount:
        session.flush()
        return "revoked"
    # Nothing active yet: the grant may still be in flight. Keep a revoked marker so a grant that
    # happened before this revoke and arrives later stays closed (see _revoked_after).
    occurred = _ms(data.get("occurred_at_ms")) or moment
    session.add(OttEntitlement(channel_id=offer.channel_id, viewer_id=viewer_id, offer_id=offer.id, kind=offer.kind,
                               title_id=offer.title_id, status=REVOKED, granted_event_id=event_id,
                               granted_at=occurred, revoked_at=moment, revoked_reason=why))
    session.flush()
    return "revoked:none_active"


def viewer_entitlements(session: Session, viewer_id: str) -> list[dict[str, Any]]:
    rows = session.execute(select(OttEntitlement, OttOffer).join(OttOffer, OttOffer.id == OttEntitlement.offer_id)
                           .where(OttEntitlement.viewer_id == viewer_id)
                           .order_by(OttEntitlement.granted_at.desc())).all()
    moment = now()
    out = []
    for ent, offer in rows:
        expired = ent.status == ACTIVE and _aware(ent.expires_at) is not None and _aware(ent.expires_at) <= moment
        out.append({"id": ent.id, "offer": offer.name, "kind": ent.kind, "title_id": ent.title_id,
                    "status": "expired" if expired else ent.status,
                    "expires_at": ent.expires_at.isoformat() if ent.expires_at else None})
    return out


@dataclass(frozen=True)
class ReturnState:
    """Where the buyer landed back from the creator's hosted checkout (QM1.3)."""

    done: bool
    cancelled: bool


def return_state(url: str) -> ReturnState:
    """``?purchase=done`` means the hosted checkout finished; the grant event unlocks the title.

    The page then re-reads ``/entitlements`` until the grant has landed; it
    never unlocks from the URL alone.
    """
    value = (parse_qs(urlsplit(str(url or "")).query).get("purchase") or [""])[0]
    return ReturnState(done=value == "done", cancelled=value == "cancelled")


def forget_viewer(session: Session, viewer_id: str) -> int:
    """A deleted viewer's entitlements end and lose the link to the person (the creator keeps the count)."""
    result = session.execute(update(OttEntitlement).where(OttEntitlement.viewer_id == viewer_id).values(
        viewer_id="deleted", status=REVOKED, revoked_at=now(), revoked_reason="viewer_deleted"))
    return int(result.rowcount or 0)


__all__ = ["REFUSED_NO_EXPIRY", "REVOKE_REASONS", "ReturnState", "return_state", "apply_event", "can_watch", "forget_viewer", "live_entitlements", "subscribed",
           "viewer_entitlements"]
