"""Personal entitlements: one answer for web plans, packs and mobile Pro.

``user_entitlements(user_id)`` answers "what may this person do with the reels
they made?" the same way for every way of paying:

* a live **web monthly plan** (Dodo or Creem ``creator_subscriptions`` row),
* a **credit pack** bought on the web or in the app store,
* a **premium voice or AI-video pack** (MV-ENT1, owner decision 2026-09-28),
  under the same grace rule as a standard pack,
* an active **RevenueCat Pro** entitlement (mobile),
* a **workspace seat**: membership of a workspace that has a live team plan or
  shared pool credits left (MG12). Membership is read from the database for
  this user only, so naming another team's workspace grants nothing.

Any one of them unlocks the clean MP4 download, share, publish, editor export
and the winner loop. Nothing else does: signup reels and the $1 card check do
not.

Fail-closed rules:

* Every source is checked independently. A source that cannot be read (DB
  error, RevenueCat outage or missing configuration) grants nothing.
* If no source grants and at least one could not be verified, the result is
  ``unavailable`` (callers answer 503, never 200), so an outage can neither
  open paid features nor be mistaken for "not paid".
* The cheap local sources (plan row, ledger) are read first; RevenueCat is only
  asked when neither grants, so status polling costs no billing request for web
  buyers.

Pack rule: a pack buyer is entitled while they have credits left, and for
``PACK_GRACE_DAYS`` after their latest pack purchase, so the reel made with the
last credit of a pack can still be downloaded clean. A pack whose payment was
refunded (``refund:<provider>:<ref>`` in the ledger) does not count. A premium
pack also stops counting once its payment is refunded (even after its credits
were spent), lost in a dispute, or while a dispute on it is open.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from loguru import logger

FREE: str = "free"
PACK: str = "pack"
SOURCE_NONE: str = "none"
SOURCE_PACK: str = "pack"
SOURCE_PREMIUM_PACK: str = "premium_pack"
SOURCE_REVENUECAT: str = "revenuecat"
SOURCE_WORKSPACE: str = "workspace"
SOURCE_COMP: str = "comp"
COMP_PLAN: str = "comp"
WORKSPACE_PLAN: str = "workspace"
_LIVE_TEAM_STATUSES: frozenset[str] = frozenset({"active", "trialing"})
REVENUECAT_PLAN: str = "pro"

#: Days a pack buyer keeps clean downloads after their latest pack purchase.
PACK_GRACE_DAYS: int = 30

_PURCHASE_PREFIX: str = "purchase:"
_REFUND_PREFIX: str = "refund:"
# Ledger refs of monthly-plan period grants (``purchase:<p>:msub:<sub>:<period>``);
# those are plan credits, not packs.
_PLAN_GRANT_MARKER: str = ":msub:"
# MG2 trail (services/billing/dodo_billing.py) for premium-pack reversals.
_DISPUTE_HOLD_PREFIX: str = "dispute_hold:"
_REVERSAL_ACTIONS: frozenset[str] = frozenset(
    {"billing.refund", "billing.dispute_lost", "billing.dispute.lost", "billing.dispute.accepted"}
)
_DISPUTE_CLEARED_ACTIONS: frozenset[str] = frozenset({"billing.dispute.won", "billing.dispute.cancelled"})


class PaidAccessDenied(RuntimeError):
    """No paid source grants this user the action (answer 402)."""


class PaidAccessUnavailable(RuntimeError):
    """No source granted and at least one could not be verified (answer 503)."""


@dataclass(frozen=True)
class UserEntitlements:
    """What a user's payments unlock right now (immutable snapshot)."""

    plan: str
    source: str
    credits_left: int
    clean_download: bool
    publish: bool
    unavailable: bool = False

    @property
    def paid(self) -> bool:
        return self.clean_download

    @property
    def watermark(self) -> bool:
        """Results are shown as watermarked previews unless paid access exists."""
        return not self.clean_download

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "watermark": self.watermark}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _granted(plan: str, source: str, credits_left: int) -> UserEntitlements:
    return UserEntitlements(
        plan=plan,
        source=source,
        credits_left=int(credits_left),
        clean_download=True,
        publish=True,
    )


# --------------------------------------------------------------------------- #
# Local sources (one DB session)
# --------------------------------------------------------------------------- #
def _plan_source(session: Any, user_id: str) -> tuple[str, str] | None:
    """``(plan_key, provider)`` for a live personal web plan, else ``None``."""
    from app.services.billing import creator_subscriptions as subs

    row = subs._row(session, user_id)
    if not subs.is_live(row):
        return None
    return (str(row.plan_key or "").strip().lower() or FREE, str(row.provider or "").strip() or "creem")


def _pack_refs(rows: Iterable[tuple[int, str, Any]]) -> tuple[bool, datetime | None]:
    """Whether a non-refunded pack purchase exists, and when the latest was made."""
    from app.services.billing.card_check import CARD_CHECK_CREDITS

    refunded = {
        str(reason)[len(_REFUND_PREFIX):]
        for delta, reason, _ in rows
        if str(reason).startswith(_REFUND_PREFIX)
    }
    latest: datetime | None = None
    found = False
    for delta, reason, created_at in rows:
        text = str(reason)
        if int(delta) <= CARD_CHECK_CREDITS or not text.startswith(_PURCHASE_PREFIX):
            continue
        if _PLAN_GRANT_MARKER in text or text[len(_PURCHASE_PREFIX):] in refunded:
            continue
        found = True
        stamp = _aware(created_at)
        if stamp is not None and (latest is None or stamp > latest):
            latest = stamp
    return found, latest


def _pack_source(session: Any, user_id: str, credits_left: int) -> bool:
    from sqlalchemy import or_, select

    from app.models.db.models import CreditLedger

    rows = session.execute(
        select(CreditLedger.delta, CreditLedger.reason, CreditLedger.created_at).where(
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
            or_(
                CreditLedger.reason.like(f"{_PURCHASE_PREFIX}%"),
                CreditLedger.reason.like(f"{_REFUND_PREFIX}%"),
            ),
        )
    ).all()
    found, latest = _pack_refs([tuple(row) for row in rows])
    if not found:
        return False
    if credits_left > 0:
        return True
    return latest is not None and _now() - latest <= timedelta(days=PACK_GRACE_DAYS)


def _premium_purchases(session: Any, user_id: str) -> tuple[dict[str, datetime | None], set[str]]:
    """``({"<provider>:<ref>": created_at}, refunded refs)`` from the premium ledger."""
    from sqlalchemy import or_, select

    from app.models.db.premium_credit import PremiumCreditLedger

    rows = session.execute(
        select(PremiumCreditLedger.delta, PremiumCreditLedger.reason, PremiumCreditLedger.created_at).where(
            PremiumCreditLedger.user_id == user_id,
            or_(
                PremiumCreditLedger.reason.like(f"{_PURCHASE_PREFIX}%"),
                PremiumCreditLedger.reason.like(f"{_REFUND_PREFIX}%"),
            ),
        )
    ).all()
    purchases: dict[str, datetime | None] = {}
    refunded: set[str] = set()
    for delta, reason, created_at in rows:
        text = str(reason)
        if text.startswith(_REFUND_PREFIX):
            refunded.add(text[len(_REFUND_PREFIX):])
        elif int(delta) > 0:
            purchases[text[len(_PURCHASE_PREFIX):]] = _aware(created_at)
    return purchases, refunded


def _reversed_payments(session: Any, user_id: str, payment_ids: list[str]) -> set[str]:
    """Payment ids refunded, lost in a dispute, or under a dispute not closed in our favor.

    Reads the MG2 trail: the audit rows ``reverse_payment`` / ``handle_dispute``
    write (a refund of already-spent credits leaves no ledger row) and the
    ``dispute_hold:<pid>`` rows in the personal credit ledger.
    """
    from sqlalchemy import select

    from app.models.db.models import AuditLog, CreditLedger

    audit = session.execute(
        select(AuditLog.action, AuditLog.target_id).where(
            AuditLog.target_type == "payment", AuditLog.target_id.in_(payment_ids)
        )
    ).all()
    reversed_ids = {str(pid) for action, pid in audit if str(action) in _REVERSAL_ACTIONS}
    cleared = {str(pid) for action, pid in audit if str(action) in _DISPUTE_CLEARED_ACTIONS}
    holds = session.execute(
        select(CreditLedger.reason).where(
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
            CreditLedger.reason.like(f"{_DISPUTE_HOLD_PREFIX}%"),
        )
    ).scalars().all()
    disputed = {str(reason).split(":")[1] for reason in holds if str(reason).count(":") >= 1}
    return reversed_ids | (disputed - cleared)


def _premium_pack_source(session: Any, user_id: str) -> bool:
    """A premium voice / AI-video pack counts as a pack (MV-ENT1, owner yes 2026-09-28).

    Same rule as a standard pack: entitled while premium credits are left, and
    for ``PACK_GRACE_DAYS`` after the latest purchase that was not refunded or
    disputed. Grants without a purchase (support adjustments, job refunds) and
    disputed or refunded purchases never count.
    """
    from app.services.billing import premium_credits

    purchases, refunded = _premium_purchases(session, user_id)
    live = {ref: stamp for ref, stamp in purchases.items() if ref not in refunded}
    if not live:
        return False
    by_payment = {ref.split(":", 1)[-1]: ref for ref in live}
    for pid in _reversed_payments(session, user_id, sorted(by_payment)):
        live.pop(by_payment.get(pid, ""), None)
    if not live:
        return False
    if any(premium_credits.balance(session, user_id, kind) > 0 for kind in premium_credits.KINDS):
        return True
    stamps = [stamp for stamp in live.values() if stamp is not None]
    return bool(stamps) and _now() - max(stamps) <= timedelta(days=PACK_GRACE_DAYS)


def _workspace_source(session: Any, user_id: str, workspace_id: str | None = None) -> str | None:
    """Plan key of a paying workspace this user is a member of, else ``None``.

    Paying = a live team subscription on a self-serve or sales plan, or shared
    pool credits left. With ``workspace_id`` only that workspace counts, and only
    if the user is a member of it (no cross-tenant grant).
    """
    from sqlalchemy import select

    from app.models.db.models import Subscription, WorkspaceMember
    from app.models.db.repositories import CreditRepository

    stmt = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    if workspace_id:
        stmt = stmt.where(WorkspaceMember.workspace_id == workspace_id)
    member_of = [str(ws) for ws in session.execute(stmt).scalars().all() if ws]
    repo = CreditRepository(session)
    for ws in member_of:
        sub = session.execute(select(Subscription).where(Subscription.workspace_id == ws)).scalars().first()
        live = sub is not None and str(sub.status or "").lower() in _LIVE_TEAM_STATUSES
        if live and str(sub.plan_key or FREE).lower() != FREE:
            return str(sub.plan_key).lower()
        if repo.workspace_balance(ws) > 0:
            return WORKSPACE_PLAN
    return None


def _comp_source(session: Any, user_id: str) -> bool:
    """Internal comp account: email listed in ``MENIVOR_COMP_EMAILS`` (explicit only).

    Used by the in-house marketing renderer and the prod smoke test, so their
    reels download clean without a fake purchase in the ledger. Empty by
    default: no domain-wide grant, every address is named on the server.
    """
    import os

    allowed = {
        e.strip().lower() for e in (os.environ.get("MENIVOR_COMP_EMAILS") or "").split(",") if e.strip()
    }
    if not allowed:
        return False
    from app.models.db.models import User

    user = session.get(User, user_id)
    return user is not None and str(user.email or "").strip().lower() in allowed


def _local(user_id: str, workspace_id: str | None = None) -> tuple[UserEntitlements | None, int, bool]:
    """``(grant or None, credits_left, verification_failed)`` from the database."""
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import CreditRepository

        with get_session() as session:
            credits_left = max(0, int(CreditRepository(session).balance(user_id)))
            plan = _plan_source(session, user_id)
            if plan is not None:
                return _granted(plan[0], plan[1], credits_left), credits_left, False
            if _pack_source(session, user_id, credits_left):
                return _granted(PACK, SOURCE_PACK, credits_left), credits_left, False
            if _premium_pack_source(session, user_id):
                return _granted(PACK, SOURCE_PREMIUM_PACK, credits_left), credits_left, False
            team = _workspace_source(session, user_id, workspace_id)
            if team is not None:
                return _granted(team, SOURCE_WORKSPACE, credits_left), credits_left, False
            if _comp_source(session, user_id):
                return _granted(COMP_PLAN, SOURCE_COMP, credits_left), credits_left, False
            return None, credits_left, False
    except Exception as exc:  # noqa: BLE001 - an unreadable source grants nothing
        logger.warning(f"entitlements: local lookup failed for user={user_id}: {type(exc).__name__}")
        return None, 0, True


def _revenuecat(user_id: str) -> tuple[bool, bool]:
    """``(active, verification_failed)`` for the mobile Pro entitlement."""
    try:
        from app.services.billing import revenuecat_client as rc
    except Exception:  # noqa: BLE001 - billing layer missing reads as unverifiable
        return False, True
    try:
        rc.require_pro_entitlement(str(user_id))
        return True, False
    except rc.RevenueCatAccessDenied:
        return False, False
    except Exception as exc:  # noqa: BLE001 - config/upstream failure fails closed
        logger.info(f"entitlements: RevenueCat unverifiable for user={user_id}: {type(exc).__name__}")
        return False, True


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def user_entitlements(user_id: str, *, workspace_id: str | None = None) -> UserEntitlements:
    """Resolve every paid source for ``user_id`` (fail-closed, never raises).

    ``workspace_id`` narrows the seat source to that one workspace (for a
    reel made inside a workspace); personal sources still count.
    """
    normalized = str(user_id or "").strip()
    if not normalized:
        return UserEntitlements(FREE, SOURCE_NONE, 0, False, False)
    grant, credits_left, local_failed = _local(normalized, str(workspace_id or "").strip() or None)
    if grant is not None:
        return grant
    active, rc_failed = _revenuecat(normalized)
    if active:
        return _granted(REVENUECAT_PLAN, SOURCE_REVENUECAT, credits_left)
    return UserEntitlements(
        plan=FREE,
        source=SOURCE_NONE,
        credits_left=credits_left,
        clean_download=False,
        publish=False,
        unavailable=local_failed or rc_failed,
    )


def require_paid_access(user_id: str, *, workspace_id: str | None = None) -> UserEntitlements:
    """Return the granting entitlements or raise a typed, fail-closed error."""
    result = user_entitlements(user_id, workspace_id=workspace_id)
    if result.clean_download:
        return result
    if result.unavailable:
        raise PaidAccessUnavailable("Paid access could not be verified right now.")
    raise PaidAccessDenied("A paid plan, credit pack, team seat or Pro subscription is required.")


def can_access_clean_result(user_id: str, *, workspace_id: str | None = None) -> bool:
    """Whether the clean (unwatermarked) MP4 may be presigned for ``user_id``."""
    return user_entitlements(user_id, workspace_id=workspace_id).clean_download


__all__ = [
    "PACK_GRACE_DAYS",
    "PaidAccessDenied",
    "PaidAccessUnavailable",
    "UserEntitlements",
    "can_access_clean_result",
    "require_paid_access",
    "user_entitlements",
]
