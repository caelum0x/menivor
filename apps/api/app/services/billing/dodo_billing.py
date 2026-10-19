"""Dodo Payments fulfilment: packs, the $1 card check, monthly plans, refunds.

Idempotency mirrors the Creem path: a one-time purchase is credited under the
ledger reason ``purchase:dodo:<payment_id>`` whether it arrives via the webhook
(``payment.succeeded``) or the browser return (``POST /billing/dodo/confirm``,
verified server-side with ``GET /payments/{id}``), so it is granted once.

Monthly plans go through :mod:`creator_subscriptions` (``subscription.*``
events).

Money reversals follow ``gtm/policy/MONEY-REVERSALS.md`` (MG2):

* ``refund.succeeded``: a pack, pool pack or card check is debited in full
  (pro rata for a partial refund) even if already spent; the shortfall is
  ``owed`` (the balance goes below 0 and every debit is refused until a later
  grant settles it). A plan refund ends that period's included reels now (the
  whole year for yearly plans) and stops renewal; a full refund ends the plan.
* ``dispute.opened`` moves the spendable personal and premium balance into a
  hold (no spending of any class), alerts the owner, and keeps later top-ups
  frozen. ``dispute.won`` / ``.cancelled`` release it. ``dispute.lost`` /
  ``.accepted`` release it and reverse the payment exactly like a full refund.
* Every path is idempotent per payment id (``refund:dodo:<payment_id>``), a
  refund after a lost dispute changes nothing, and each event writes an audit
  row and a Rally event. No money event deletes any data.
"""

from __future__ import annotations

from typing import Any, Mapping

from loguru import logger

from app.services.billing import dodo_client

PROVIDER: str = "dodo"
_REFUND_REASON_PREFIX: str = "refund:dodo"


class ConfirmError(ValueError):
    """The return cannot be confirmed (not ours, not this user's, unknown product)."""


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
def open_pack_checkout(user: Mapping[str, Any], plan: Any, *, workspace_id: str | None) -> dict:
    product = dodo_client.pack_product_id(plan.key) or getattr(plan, "dodo_product_id", "")
    if not product:
        raise ValueError(
            f"Dodo product for the {plan.key} pack is not configured: "
            f"set DODO_PRODUCT_ID_{plan.key.upper()}."
        )
    return dodo_client.create_checkout(
        product_id=product,
        metadata={
            "kind": dodo_client.KIND_PACK,
            "user_id": user["id"],
            "plan_key": plan.key,
            "credits": int(plan.credits),
            "workspace_id": workspace_id or "",
        },
        return_url=dodo_client.return_url("/billing"),
        customer_email=str(user.get("email", "") or ""),
    )


def open_premium_checkout(user: Mapping[str, Any], pack: Any) -> dict:
    """Hosted checkout for a premium voice / AI-video credit pack."""
    product = dodo_client.pack_product_id(pack.key)
    if not product:
        raise ValueError(
            f"Dodo product for the {pack.key} pack is not configured: "
            f"set DODO_PRODUCT_ID_{pack.key.upper()}."
        )
    return dodo_client.create_checkout(
        product_id=product,
        metadata={
            "kind": dodo_client.KIND_PREMIUM_PACK,
            "user_id": user["id"],
            "pack_key": pack.key,
            "credits": int(pack.credits),
        },
        return_url=dodo_client.return_url("/billing"),
        customer_email=str(user.get("email", "") or ""),
    )


# --------------------------------------------------------------------------- #
# metadata.kind routing for MN4 (team plans, wallet top-ups)
# --------------------------------------------------------------------------- #
KIND_WALLET: str = "wallet_topup"


def _apply_team_event(event: Any) -> dict[str, Any]:
    from app.services import subscriptions

    from app.services.billing import workspace_plans as wp

    result = subscriptions.process_provider_event(wp.DODO, event)
    if result is None and wp.parse_dodo_event(event) is not None:
        _alert_owner("A Dodo team-plan event arrived but subscription_providers does not route "
                     "Dodo yet; the seat plan was not applied. Replay it after the wiring lands.")
        raise RuntimeError("Dodo team plans are not wired into subscription_providers")
    return result or {}


def _apply_wallet_payment(data: Mapping[str, Any], event_id: str) -> dict[str, Any]:
    """Grant a Dodo wallet top-up once. A payment that does not bind to its
    intent is refused (no credit) and reported to the owner, not retried."""
    from app.domains.wallet import webhooks as wallet_webhooks
    from app.domains.wallet.service import WalletError
    from app.models.db.base import get_session

    try:
        with get_session() as session:
            return wallet_webhooks.process_dodo_wallet_payment(session, dict(data), correlation_id=event_id)
    except (ValueError, WalletError) as exc:
        if int(getattr(exc, "status_code", 400) or 400) >= 500:
            raise  # settlement rail down: let Dodo retry (the grant is idempotent)
        _alert_owner(f"Dodo wallet payment {data.get('payment_id', '?')} refused: {exc}")
        return {"status": "rejected"}


# --------------------------------------------------------------------------- #
# One-time payment fulfilment
# --------------------------------------------------------------------------- #
def _pack_for(view: Mapping[str, Any]):
    """The locked catalog pack for a payment (product id first, then metadata)."""
    from app.services.billing.plans import get_plan, list_plans

    for product_id in view.get("product_ids") or []:
        for plan in list_plans(purchasable_only=True):
            configured = dodo_client.pack_product_id(plan.key) or plan.dodo_product_id
            if configured and configured == product_id:
                return plan
    # No product id on the event (older payload shape): trust our own server-set
    # metadata only when it is explicitly a Menivor pack.
    metadata = view.get("metadata", {}) or {}
    if view.get("product_ids") or metadata.get("kind") != dodo_client.KIND_PACK:
        return None
    plan = get_plan(str(metadata.get("plan_key", "") or ""))
    return plan if plan is not None and plan.is_purchasable else None


def _premium_pack_for(view: Mapping[str, Any]):
    """The premium pack for a payment (product id first, then our own metadata)."""
    from app.services.billing import premium_credits

    products = list(view.get("product_ids") or [])
    pack = premium_credits.pack_for_products(products)
    if pack is not None or products:
        return pack
    metadata = view.get("metadata", {}) or {}
    if metadata.get("kind") != dodo_client.KIND_PREMIUM_PACK:
        return None
    return premium_credits.get_pack(str(metadata.get("pack_key", "") or ""))


def _is_card_check(view: Mapping[str, Any]) -> bool:
    card_product = dodo_client.card_check_product_id()
    products = view.get("product_ids") or []
    if card_product and card_product in products:
        return True
    kind = str(view.get("metadata", {}).get("kind", "") or "")
    return not products and kind == dodo_client.KIND_CARD_CHECK


def fulfill_payment(view: Mapping[str, Any], *, external_event_id: str) -> dict[str, Any] | None:
    """Credit a succeeded one-time payment. ``None`` when it is not ours to grant."""
    from app.services.billing import card_check, service

    payment_id = str(view.get("payment_id", "") or "")
    metadata = view.get("metadata") or {}
    user_id = str(metadata.get("user_id", "") or "").strip()
    if not payment_id or not user_id:
        logger.warning(f"dodo: payment {payment_id or '?'} has no user metadata; ignoring")
        return None
    if view.get("subscription_id"):
        # Subscription charges are granted by the subscription.* events.
        return None
    if _is_card_check(view):
        balance = card_check.fulfill(
            user_id=user_id,
            checkout_id=payment_id,
            external_event_id=external_event_id,
            provider=PROVIDER,
        )
        rehold_if_frozen(user_id, tag=f"top:{payment_id}")
        return {
            "plan_key": card_check.CARD_CHECK_KEY,
            "credits": card_check.CARD_CHECK_CREDITS,
            "balance": int(balance),
            "checkout_id": payment_id,
            "workspace_id": None,
            "unlocked": True,
        }
    premium = _premium_pack_for(view)
    if premium is not None:
        from app.services.billing import premium_credits

        granted = premium_credits.grant_purchase_once(
            user_id, premium, provider=PROVIDER, reference=payment_id
        )
        rehold_if_frozen(user_id, tag=f"top:{payment_id}")
        return {
            "plan_key": premium.key,
            "kind": premium.kind,
            "credits": int(premium.credits),
            "granted": int(granted),
            "balance": int(premium_credits.balances(user_id).get(premium.kind, 0)),
            "checkout_id": payment_id,
            "workspace_id": None,
            "unlocked": False,
        }
    plan = _pack_for(view)
    if plan is None:
        logger.warning(f"dodo: payment {payment_id} is not a Menivor pack; ignoring")
        return None
    workspace_id = str(metadata.get("workspace_id", "") or "").strip() or None
    balance = service.fulfill_purchase(
        provider=PROVIDER,
        external_event_id=external_event_id,
        user_id=user_id,
        credits=int(plan.credits),
        reason_ref=payment_id,
        workspace_id=workspace_id,
    )
    if not workspace_id:
        rehold_if_frozen(user_id, tag=f"top:{payment_id}")
    return {
        "plan_key": plan.key,
        "credits": int(plan.credits),
        "balance": int(balance),
        "checkout_id": payment_id,
        "workspace_id": workspace_id,
        "unlocked": not workspace_id,
    }


# --------------------------------------------------------------------------- #
# Money reversals (gtm/policy/MONEY-REVERSALS.md): refunds and disputes
# --------------------------------------------------------------------------- #
# Ledger conventions (no schema change; provenance rides in ``reason``):
#   refund:dodo:<pid>            full reversal of a payment (refund or dispute lost)
#   refund:dodo:<pid>:<refund>   one partial refund
#   dispute_hold:<pid>[:<n>]     spendable balance moved out while a dispute is open
#   dispute_release:<pid>        hold returned (won / cancelled / before a loss)
# A reversal debits the full amount even when it was already spent, so the
# personal balance (or workspace pool) may go below 0. That negative part is
# ``owed`` (M4): every debit is refused until a later grant settles it.
DISPUTE_OPENED: str = "dispute.opened"
DISPUTE_RELEASE_EVENTS: frozenset[str] = frozenset({"dispute.won", "dispute.cancelled"})
DISPUTE_LOST_EVENTS: frozenset[str] = frozenset({"dispute.lost", "dispute.accepted"})
DISPUTE_NOTE_EVENTS: frozenset[str] = frozenset({"dispute.challenged", "dispute.expired"})
_HOLD: str = "dispute_hold"
_RELEASE: str = "dispute_release"


def _fit(reason: str) -> str:
    """Reasons keep their prefix (lookups use LIKE); long tails are cut at 80."""
    return reason[:80]


def _full_reason(pid: str) -> str:
    return _fit(f"{_REFUND_REASON_PREFIX}:{pid}")


def _rows(session: Any, *, user_id: str | None, workspace_id: str | None, prefix: str) -> list:
    """Ledger ``(reason, delta)`` rows whose reason is ``prefix`` or ``prefix:...``.

    A prefix ending in ``:`` matches any tail. Otherwise the next character must
    be ``:`` (or the end), so ``pay_1`` never matches ``pay_12``.
    """
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    stmt = select(CreditLedger.reason, CreditLedger.delta).where(CreditLedger.reason.like(f"{prefix}%"))
    if workspace_id:
        stmt = stmt.where(CreditLedger.workspace_id == workspace_id)
    else:
        stmt = stmt.where(CreditLedger.user_id == user_id, CreditLedger.workspace_id.is_(None))
    rows = session.execute(stmt).all()
    if prefix.endswith(":"):
        return list(rows)
    return [(r, d) for r, d in rows if len(str(r)) == len(prefix) or str(r)[len(prefix)] == ":"]


def _append(session: Any, *, user_id: str | None, workspace_id: str | None, delta: int, reason: str) -> int:
    """Append one row that may take the balance below 0 (owed). Returns the new balance."""
    from app.models.db.repositories import CreditRepository

    repo = CreditRepository(session)
    if workspace_id:
        current = repo._locked_workspace_balance(workspace_id)
        repo._append_workspace(
            workspace_id=workspace_id, user_id=user_id, delta=int(delta), reason=reason,
            balance_after=current + int(delta), job_id=None,
        )
    else:
        current = repo._locked_balance(str(user_id))
        repo._append(
            user_id=str(user_id), delta=int(delta), reason=reason,
            balance_after=current + int(delta), job_id=None,
        )
    return current + int(delta)


def _payment_record(pid: str) -> dict[str, Any]:
    """Dodo's own payment record (``{}`` when Dodo is unreachable)."""
    try:
        return dodo_client.get_payment(pid) or {}
    except Exception as exc:  # noqa: BLE001 - ledger-only fallback below
        logger.warning(f"dodo: payment {pid} lookup failed: {type(exc).__name__}")
        return {}


def resolve_payment(pid: str) -> dict[str, Any]:
    """What a Dodo payment bought, found by payment id (M1), never by balance."""
    from sqlalchemy import select

    from app.models.db.models import CreditLedger
    from app.services.billing import service

    out: dict[str, Any] = {"payment_id": pid, "kind": "unknown", "user_id": "", "workspace_id": None,
                           "credits": 0, "subscription_id": "", "total": 0, "metadata": {}}
    record = _payment_record(pid)
    view = dodo_client.payment_view(record) if record else {"metadata": {}, "product_ids": []}
    out["total"] = int(record.get("total_amount") or 0) if record else 0
    out["subscription_id"] = str(view.get("subscription_id", "") or "")
    out["metadata"] = dict(view.get("metadata") or {})
    grant_reason = service._fit_reason(f"purchase:{PROVIDER}:{pid}", PROVIDER, pid)
    with _session() as session:
        grant = session.execute(
            select(CreditLedger.user_id, CreditLedger.delta, CreditLedger.workspace_id)
            .where(CreditLedger.reason == grant_reason, CreditLedger.delta > 0).limit(1)
        ).first()
    if grant is not None:
        out.update(user_id=str(grant[0] or ""), credits=int(grant[1]), workspace_id=grant[2] or None)
        card = record and _is_card_check(view)
        out["kind"] = "workspace_pack" if grant[2] else ("card_check" if card else "pack")
        return out
    metadata = view.get("metadata") or {}
    out["user_id"] = str(metadata.get("user_id", "") or "").strip()
    kind = str(metadata.get("kind", "") or "")
    if out["subscription_id"]:
        out["kind"] = "workspace_plan" if metadata.get("workspace_id") else "plan"
        out["workspace_id"] = str(metadata.get("workspace_id", "") or "") or None
    elif kind == "wallet_topup":
        out["kind"] = "wallet"
    elif kind == dodo_client.KIND_PREMIUM_PACK or _premium_pack_for(view) is not None:
        out["kind"] = "premium"
    if not out["user_id"] and out["subscription_id"]:
        out["user_id"] = _plan_owner(out["subscription_id"])
    return out


def _session():
    from app.models.db.base import get_session

    return get_session()


def _plan_owner(subscription_id: str) -> str:
    from sqlalchemy import select

    from app.models.db.creator_subscription import CreatorSubscription

    with _session() as session:
        owner = session.execute(
            select(CreatorSubscription.user_id).where(CreatorSubscription.provider_ref == subscription_id)
        ).scalar()
    return str(owner or "")


def _share(credits: int, refund: Mapping[str, Any], total: int) -> int:
    """Credits covered by a (possibly partial) refund, pro rata to the payment."""
    amount = int(refund.get("amount") or 0)
    if not refund.get("is_partial") or amount <= 0 or total <= 0 or amount >= total:
        return int(credits)
    return max(1, min(int(credits), (int(credits) * amount + total // 2) // total))


def _reverse_credits(info: Mapping[str, Any], reason: str, refund: Mapping[str, Any]) -> dict[str, int]:
    """Debit a paid grant (pack, pool pack, card check) once per ``reason``."""
    user_id, workspace_id, pid = info["user_id"], info["workspace_id"], info["payment_id"]
    full = reason == _full_reason(pid)
    with _session() as session:
        from app.services.billing import service

        if workspace_id:
            from app.models.db.repositories import CreditRepository

            CreditRepository(session)._locked_workspace_balance(workspace_id)
        else:
            service._lock_user_row(session, user_id)
        done = _rows(session, user_id=user_id, workspace_id=workspace_id, prefix=f"{_REFUND_REASON_PREFIX}:{pid}")
        if any(r == reason or r == _full_reason(pid) for r, _ in done):
            return {"debited": 0, "duplicate": 1}
        already = -sum(int(d) for _, d in done if int(d) < 0)
        target = int(info["credits"]) if full else _share(int(info["credits"]), refund, int(info["total"]))
        amount = max(0, min(target, int(info["credits"]) - already))
        if info["kind"] == "card_check" and full:
            trial = session.execute(_signup_stmt(user_id)).scalar()
            amount += int(trial or 0)
        balance = _append(session, user_id=user_id, workspace_id=workspace_id, delta=-amount, reason=reason)
    return {"debited": amount, "balance": balance, "owed": max(0, -balance)}


def _signup_stmt(user_id: str):
    from sqlalchemy import func, select

    from app.models.db.models import CreditLedger

    return select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
        CreditLedger.user_id == user_id, CreditLedger.workspace_id.is_(None),
        CreditLedger.reason.in_(("signup", "mobile_device_signup", "mobile_identity_signup")),
        CreditLedger.delta > 0,
    )


def _reverse_plan(info: Mapping[str, Any], reason: str, *, full: bool) -> dict[str, int]:
    """A refunded plan payment ends that period's allowance now (yearly: the year)."""
    from app.services.billing import creator_subscriptions

    user_id, sub_id = info["user_id"], info["subscription_id"]
    with _session() as session:
        from app.services.billing import service

        service._lock_user_row(session, user_id)
        if service._ledger_has_reason(session, user_id, reason) or service._ledger_has_reason(
            session, user_id, _full_reason(info["payment_id"])
        ):
            return {"debited": 0, "duplicate": 1}
    expired = creator_subscriptions.expire_leftover(user_id)
    try:
        dodo_client.cancel_subscription(sub_id)  # no charge after a refunded period
    except Exception as exc:  # noqa: BLE001 - local state still ends; owner alerted
        _alert_owner(f"Could not stop renewal of refunded subscription {sub_id}: {exc}")
    if full:
        creator_subscriptions.apply_update(
            {"provider": PROVIDER, "provider_ref": sub_id, "user_id": user_id, "plan_key": "",
             "interval": "", "status": "canceled", "cancel_at_period_end": True,
             "period_end": None, "expire_now": True, "grant_allowed": False}
        )
    with _session() as session:
        balance = _append(session, user_id=user_id, workspace_id=None, delta=0, reason=reason)
    return {"debited": int(expired), "balance": balance, "owed": max(0, -balance)}


def _reverse_workspace_plan(info: Mapping[str, Any], reason: str) -> dict[str, int]:
    """Workspace plan refund: remove that period's unused pool credits once."""
    from app.services.billing import workspace_plans as wp

    workspace_id = str(info["workspace_id"])
    metadata = info.get("metadata") or {}
    plan = wp.get_workspace_plan(str(metadata.get("plan_key", "") or ""))
    with _session() as session:
        from app.models.db.repositories import CreditRepository

        pool = CreditRepository(session)._locked_workspace_balance(workspace_id)
        done = _rows(session, user_id=None, workspace_id=workspace_id, prefix=f"{_REFUND_REASON_PREFIX}:{info['payment_id']}")
        if done:
            return {"debited": 0, "duplicate": 1}
        period = plan.period_credits(str(metadata.get("interval", "") or wp.MONTH)) if plan else 0
        amount = max(0, min(period, pool))
        balance = _append(session, user_id=info["user_id"] or None, workspace_id=workspace_id, delta=-amount, reason=reason)
    return {"debited": amount, "balance": balance, "owed": 0}


def reverse_payment(pid: str, *, refund: Mapping[str, Any] | None = None, cause: str = "refund") -> dict[str, Any]:
    """Apply MONEY-REVERSALS section 2 for one payment. Idempotent per reversal (M3)."""
    refund = dict(refund or {})
    info = resolve_payment(pid)
    partial = bool(refund.get("is_partial")) and cause == "refund"
    refund_id = str(refund.get("refund_id", "") or "")
    reason = _fit(f"{_REFUND_REASON_PREFIX}:{pid}:{refund_id}") if partial and refund_id else _full_reason(pid)
    kind = info["kind"]
    if kind in ("pack", "workspace_pack", "card_check"):
        result = _reverse_credits(info, reason, refund)
    elif kind == "plan" and info["user_id"]:
        result = _reverse_plan(info, reason, full=not partial)
    elif kind == "workspace_plan" and info["workspace_id"]:
        result = _reverse_workspace_plan(info, reason)
    elif kind == "wallet":
        result = _reverse_wallet(pid, info, cause)
    else:
        from app.services.billing import premium_credits

        result = {"debited": premium_credits.clawback_by_reference(PROVIDER, pid)}
        kind = "premium" if result["debited"] else kind
    out = {"payment_id": pid, "kind": kind, "cause": cause, "partial": partial, **result}
    if not result.get("duplicate") and info["user_id"]:
        _record(info, f"billing.{cause}", out)
    return out


def _reverse_wallet(pid: str, info: Mapping[str, Any], cause: str) -> dict[str, int]:
    try:
        from app.domains.wallet import webhooks as wallet_webhooks

        result = dict(wallet_webhooks.reverse_dodo_payment(pid, cause=cause))
    except Exception as exc:  # noqa: BLE001 - owner reconciles by hand
        logger.error(f"dodo: wallet reversal for {pid} failed: {exc}")
        result = {"debited": 0, "failed": 1}
    if result.get("failed") or result.get("owed_micros") or result.get("mint"):
        _alert_owner(f"Wallet top-up {pid} was reversed ({cause}) but not fully debited: {result}.")
    return result


def clawback_refund(payment_id: str) -> int:
    """Full reversal of a refunded payment (kept for callers). Returns credits removed."""
    return int(reverse_payment((payment_id or "").strip()).get("debited", 0)) if payment_id else 0


# ----------------------------- disputes ------------------------------------ #
def open_disputes(session: Any, user_id: str) -> list[str]:
    """Payment ids with an open dispute hold on this user's personal ledger."""
    rows = _rows(session, user_id=user_id, workspace_id=None, prefix=f"{_HOLD}:")
    released = {r.split(":")[1] for r, _ in _rows(session, user_id=user_id, workspace_id=None, prefix=f"{_RELEASE}:")}
    return sorted({r.split(":")[1] for r, _ in rows} - released)


def spending_frozen(user_id: str) -> bool:
    """True while any Dodo dispute on this account is open (no spending of any class)."""
    with _session() as session:
        return bool(open_disputes(session, user_id))


def owed(user_id: str) -> int:
    """Credits owed after reversals (M4): the negative part of the personal balance."""
    from app.models.db.repositories import CreditRepository

    with _session() as session:
        return max(0, -int(CreditRepository(session).balance(user_id)))


def _hold(session: Any, user_id: str, pid: str, tag: str = "") -> int:
    """Move the spendable personal + premium balance into the dispute hold."""
    from app.models.db.repositories import CreditRepository
    from app.services.billing import premium_credits as pc

    reason = _fit(f"{_HOLD}:{pid}{':' + tag if tag else ''}")
    if any(r == reason for r, _ in _rows(session, user_id=user_id, workspace_id=None, prefix=reason)):
        return 0
    spendable = max(0, CreditRepository(session)._locked_balance(user_id))
    _append(session, user_id=user_id, workspace_id=None, delta=-spendable, reason=reason)
    for kind in pc.KINDS:
        held = pc.balance(session, user_id, kind)
        if held > 0 and not pc.has_reason(session, user_id, reason + ":" + kind):
            pc.debit(session, user_id, kind, held, reason + ":" + kind)
    return spendable


def _release(session: Any, user_id: str, pid: str) -> int:
    """Return one dispute's hold; if another dispute is open, move it there."""
    from sqlalchemy import select

    from app.models.db.premium_credit import PremiumCreditLedger
    from app.services.billing import premium_credits as pc

    if pid not in open_disputes(session, user_id):
        return 0
    held = -sum(int(d) for _, d in _rows(session, user_id=user_id, workspace_id=None, prefix=f"{_HOLD}:{pid}"))
    _append(session, user_id=user_id, workspace_id=None, delta=held, reason=_fit(f"{_RELEASE}:{pid}"))
    premium = session.execute(
        select(PremiumCreditLedger.kind, PremiumCreditLedger.delta).where(
            PremiumCreditLedger.user_id == user_id, PremiumCreditLedger.reason.like(f"{_HOLD}:{pid}:%")
        )
    ).all()
    for kind, delta in premium:
        if int(delta) < 0:
            pc.grant(session, user_id, kind, -int(delta), f"{_RELEASE}:{pid}:{kind}")
    others = open_disputes(session, user_id)
    if others:
        _hold(session, user_id, others[0], tag=f"from:{pid}")
    return held


def rehold_if_frozen(user_id: str, tag: str) -> int:
    """Keep new credit frozen while a dispute is open (call after any grant)."""
    with _session() as session:
        open_ids = open_disputes(session, user_id) if user_id else []
        return _hold(session, user_id, open_ids[0], tag=tag) if open_ids else 0


def handle_dispute(etype: str, data: Mapping[str, Any]) -> dict[str, Any]:
    pid = str(data.get("payment_id", "") or "").strip()
    info = resolve_payment(pid) if pid else {"user_id": ""}
    user_id = str(info.get("user_id") or "")
    out: dict[str, Any] = {"payment_id": pid, "event": etype, "user_id": bool(user_id)}
    if not user_id:
        _alert_owner(f"Dodo {etype} for payment {pid or '?'} matches no Menivor account.")
        return out
    if etype == DISPUTE_OPENED:
        with _session() as session:
            out["held"] = _hold(session, user_id, pid)
    elif etype in DISPUTE_RELEASE_EVENTS or etype in DISPUTE_LOST_EVENTS:
        with _session() as session:
            out["released"] = _release(session, user_id, pid)
        if etype in DISPUTE_LOST_EVENTS:
            out["reversal"] = reverse_payment(pid, cause="dispute_lost")
            rehold_if_frozen(user_id, tag=f"after:{pid}")
    _record(info, f"billing.{etype}", out)
    _alert_owner(f"Dodo {etype}: payment {pid}, user {user_id}, amount {data.get('amount', '?')}.")
    if etype != DISPUTE_OPENED and etype not in DISPUTE_NOTE_EVENTS:
        won = etype in DISPUTE_RELEASE_EVENTS
        _notify_user(user_id, "Your payment dispute is closed",
                     "The dispute on your payment is closed in our favor. Rendering is back on."
                     if won else "The dispute on your payment is closed and the payment was returned "
                     "to you. The credit it bought has been removed from your balance.")
    return out


# ------------------------ audit, alerts, notices, Rally ---------------------- #
def _record(info: Mapping[str, Any], action: str, detail: Mapping[str, Any]) -> None:
    """One audit row (M7) and one Rally event (M8). Never raises."""
    user_id = str(info.get("user_id") or "")
    try:
        from app.services import audit

        with _session() as session:
            audit.record(session, actor_user_id=user_id, action=action[:60],
                         workspace_id=info.get("workspace_id") or None, target_type="payment",
                         target_id=str(info.get("payment_id") or "")[:64],
                         metadata={k: v for k, v in detail.items() if isinstance(v, (int, str, bool))})
    except Exception as exc:  # noqa: BLE001 - audit never blocks a reversal
        logger.warning(f"dodo: audit {action} failed: {exc}")
    try:
        from app.integrations.rally import hooks

        event = "payment_disputed" if "dispute" in action else "payment_refunded"
        hooks._emit(event=event, user_id=user_id,
                    idempotency_key=f"{action}:{info.get('payment_id')}:{detail.get('partial', '')}",
                    properties={"provider": PROVIDER, "kind": str(detail.get("kind", info.get("kind", ""))),
                                "event": action.removeprefix("billing.")})
    except Exception as exc:  # noqa: BLE001 - lifecycle events never block money
        logger.debug(f"rally {action} skipped: {exc}")


def _alert_owner(text: str) -> None:
    """Owner alert: log + optional ntfy topic + optional email (free channels only)."""
    import os

    logger.error(f"owner alert: {text}")
    topic = (os.environ.get("MENIVOR_OWNER_NTFY_URL") or "").strip()
    if topic:
        try:
            import requests

            requests.post(topic, data=text.encode("utf-8"), timeout=5,
                          headers={"Title": "Menivor billing", "User-Agent": dodo_client.USER_AGENT})
        except Exception as exc:  # noqa: BLE001 - alerting is best effort
            logger.warning(f"owner ntfy alert failed: {type(exc).__name__}")
    to = (os.environ.get("MENIVOR_OWNER_ALERT_EMAIL") or "").strip()
    if to:
        try:
            from app.services import mailer

            mailer.send_email(to=to, subject="Menivor billing alert", text=text)
        except Exception as exc:  # noqa: BLE001 - an SMTP outage must not fail a processed webhook
            logger.warning(f"owner email alert failed: {type(exc).__name__}")


def _notify_user(user_id: str, subject: str, text: str) -> None:
    """Transactional notice (refund confirmation, dispute outcome; outside L1)."""
    try:
        from app.models.db.models import User
        from app.services import mailer

        with _session() as session:
            user = session.get(User, user_id)
            email = str(getattr(user, "email", "") or "")
        if "@" in email and not email.endswith(".invalid"):
            mailer.send_email(to=email, subject=subject, text=text)
    except Exception as exc:  # noqa: BLE001 - a notice never blocks money
        logger.warning(f"dodo: user notice failed: {type(exc).__name__}")


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
def handle_webhook(payload: bytes, headers: Mapping[str, Any]) -> dict[str, Any]:
    """Verify + apply a Dodo webhook. Signature errors propagate (caller -> 400)."""
    from app.services.billing import creator_dodo, creator_subscriptions

    event = dodo_client.verify_and_parse_webhook(payload, headers)
    etype = dodo_client.event_type(event)
    ours, theirs = dodo_client.brand_id(), dodo_client.event_brand(event)
    if ours and theirs and theirs != ours:
        # Shared Dodo business: another brand's event (vcpeer, bidstage, ...).
        return {"type": etype, "handled": "other_brand"}
    event_id = dodo_client.event_id(event)
    data = dodo_client.event_data(event)

    from app.services.billing import workspace_plans as wp

    if wp.is_dodo_team_event(event):
        result = _apply_team_event(event)
        return {"type": etype, "handled": "team_subscription", "granted": bool(result.get("granted"))}

    personal = creator_dodo.parse_event(event)
    if personal is not None:
        result = creator_subscriptions.apply_update(personal) or {}
        return {"type": etype, "handled": "subscription", "granted": result.get("granted", 0)}

    if etype == dodo_client.PAYMENT_SUCCEEDED:
        view = dodo_client.payment_view(data)
        if view["metadata"].get("kind") == KIND_WALLET and not view.get("subscription_id"):
            result = _apply_wallet_payment(data, event_id or view["payment_id"])
            return {"type": etype, "handled": "wallet", "status": result.get("status", "")}
        result = fulfill_payment(view, external_event_id=event_id or view["payment_id"])
        if result:  # Wave P PM1.5: Mint ledger mirror of the credit or pack payment (record only)
            from app.integrations.railyard.meters import mirror_now

            mirror_now("payment", view, result)
        return {"type": etype, "handled": "payment" if result else "ignored"}

    if etype == dodo_client.REFUND_SUCCEEDED:
        payment_id = str(data.get("payment_id", "") or "").strip()
        result = reverse_payment(payment_id, refund=data) if payment_id else {"debited": 0}
        if payment_id and result.get("debited"):  # Wave P PM1.5: Mint ledger mirror of the refund
            from app.integrations.railyard.meters import mirror_now

            mirror_now("refund", payment_id, result)
        if result.get("kind") == "unknown" and not result.get("debited"):
            _alert_owner(f"Dodo refund for payment {payment_id or '?'} matched nothing; check it by hand.")
        elif not result.get("duplicate") and result.get("kind") != "unknown":
            user_id = resolve_payment(payment_id)["user_id"]
            _notify_user(user_id, "Your refund is done",
                         "Your refund is done. The credit that payment bought has been removed "
                         "from your balance.")
        return {"type": etype, "handled": "refund", "removed": int(result.get("debited", 0))}

    if etype == DISPUTE_OPENED or etype in DISPUTE_RELEASE_EVENTS or etype in DISPUTE_LOST_EVENTS \
            or etype in DISPUTE_NOTE_EVENTS:
        return {"type": etype, "handled": "dispute", **handle_dispute(etype, data)}

    logger.info(f"dodo: webhook {etype or '?'} acknowledged (no action)")
    return {"type": etype, "handled": "ignored"}


# --------------------------------------------------------------------------- #
# Browser return (server-verified; idempotent with the webhook)
# --------------------------------------------------------------------------- #
def confirm_return(
    *, user_id: str, payment_id: str = "", subscription_id: str = ""
) -> dict[str, Any]:
    """Confirm a Dodo return for ``user_id`` by reading Dodo's own record."""
    from app.services.billing import creator_dodo, creator_plan_actions
    from app.services.billing import creator_plans as cp

    if subscription_id:
        view = creator_dodo.fetch_subscription_view(subscription_id)
        owner = str(view["metadata"].get("user_id", "") or "")
        if owner != user_id:
            raise ConfirmError("This subscription does not belong to your account.")
        mapped = cp.plan_for_product(view["product_ref"], PROVIDER)
        if mapped is None:
            raise ConfirmError("This subscription is not a Menivor plan on this server.")
        if view["status"] not in ("active", "trialing"):
            return {"pending": True}
        return creator_plan_actions.confirm_redirect(
            {
                "user_id": user_id,
                "subscription_id": view["provider_ref"],
                "customer_id": view["customer_ref"],
                "checkout_id": view["provider_ref"],
                "provider": PROVIDER,
            },
            mapped[0],
            mapped[1],
        )

    if not payment_id:
        raise ConfirmError("payment_id or subscription_id is required.")
    view = dodo_client.payment_view(dodo_client.get_payment(payment_id))
    owner = str(view["metadata"].get("user_id", "") or "")
    if owner != user_id:
        raise ConfirmError("This payment does not belong to your account.")
    if view["status"] != "succeeded":
        return {"pending": True}
    if view.get("subscription_id"):
        return confirm_return(user_id=user_id, subscription_id=view["subscription_id"])
    result = fulfill_payment(view, external_event_id=f"return:{view['payment_id']}")
    if result is None:
        raise ConfirmError("This payment is not a Menivor purchase on this server.")
    return result


__all__ = [
    "ConfirmError",
    "KIND_WALLET",
    "handle_dispute",
    "open_disputes",
    "owed",
    "rehold_if_frozen",
    "resolve_payment",
    "reverse_payment",
    "spending_frozen",
    "open_premium_checkout",
    "PROVIDER",
    "clawback_refund",
    "confirm_return",
    "fulfill_payment",
    "handle_webhook",
    "open_pack_checkout",
]
