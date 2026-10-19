"""Premium voice and AI-video credits: the SKUs standard credits never pay for.

Pricing rule (owner decision, 2026-09-27): a standard reel credit covers the
script LLM (Claude via Relay), free voices, captions, footage and the render.
It never pays for ElevenLabs or for AI-video / AI-presenter provider calls.

* **Premium voice credit** - one reel narrated with a premium (ElevenLabs)
  voice. A job without one is narrated with a free voice instead.
* **AI-video credit** - 1 credit = 1 US cent, spent at ``AI_VIDEO_MARKUP`` (3x)
  the provider cost. Admission reserves 3x the estimate; success settles to 3x
  the measured cost and returns the surplus; failure returns everything.

Balances live in ``premium_credit_ledger`` (one balance per user and kind).
Every write locks the user's row first, so concurrent debits cannot overdraw.
Purchases are Dodo one-time products (``premium_voice_25``, ``ai_video_2000``),
credited once per payment under ``purchase:dodo:<payment_id>``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.models.db.premium_credit import KIND_AI_VIDEO, KIND_PREMIUM_VOICE, KINDS

AI_VIDEO_MARKUP: int = 3
CENTS_PER_USD: int = 100
_REASON_MAX_LEN: int = 80

DEBIT_REASON: str = "premium_debit"
REFUND_REASON: str = "premium_refund"
SETTLE_REASON: str = "ai_video_settle"


class InsufficientPremiumCredits(ValueError):
    """The user does not hold enough credits of ``kind`` for this action."""

    def __init__(self, kind: str, needed: int, available: int) -> None:
        super().__init__(f"{kind}: needs {needed}, has {available}")
        self.kind = kind
        self.needed = int(needed)
        self.available = int(available)


# --------------------------------------------------------------------------- #
# Catalog (config-overridable prices; credits are fixed per pack)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PremiumPack:
    key: str
    kind: str
    credits: int
    price_usd: float
    label: str

    def as_dict(self) -> dict[str, Any]:
        from app.services.billing import dodo_client

        return {
            "key": self.key,
            "kind": self.kind,
            "credits": self.credits,
            "price_usd": self.price_usd,
            "label": self.label,
            "available": bool(dodo_client.pack_product_id(self.key)),
        }


# (key, kind, credits, default price, label)
_PACK_BASELINES: tuple[tuple[str, str, int, float, str], ...] = (
    ("premium_voice_25", KIND_PREMIUM_VOICE, 25, 9.00, "25 premium voice reels"),
    ("ai_video_2000", KIND_AI_VIDEO, 2000, 20.00, "$20 of AI video and presenter time"),
)


def _price(key: str, default: float) -> float:
    try:
        from app.config import config

        raw = (getattr(config, "billing", {}) or {}).get(f"{key}_price_usd")
        return float(raw) if raw not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def list_packs() -> list[PremiumPack]:
    return [
        PremiumPack(key, kind, credits, _price(key, price), label)
        for key, kind, credits, price, label in _PACK_BASELINES
    ]


def get_pack(key: str | None) -> PremiumPack | None:
    wanted = str(key or "").strip().lower()
    return next((pack for pack in list_packs() if pack.key == wanted), None)


def pack_for_products(product_ids: list[str] | tuple[str, ...]) -> PremiumPack | None:
    from app.services.billing import dodo_client

    for pack in list_packs():
        configured = dodo_client.pack_product_id(pack.key)
        if configured and configured in (product_ids or []):
            return pack
    return None


def ai_video_credits_for_usd(provider_usd: float) -> int:
    """AI-video credits for a provider cost: ``ceil(3 x cost in cents)``."""
    cost = max(0.0, float(provider_usd or 0.0))
    if not math.isfinite(cost) or cost <= 0:
        return 0
    return int(math.ceil(round(cost * AI_VIDEO_MARKUP * CENTS_PER_USD, 6)))


# --------------------------------------------------------------------------- #
# Ledger primitives (caller's session)
# --------------------------------------------------------------------------- #
def _fit(reason: str) -> str:
    return reason[:_REASON_MAX_LEN]


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown premium credit kind {kind!r}")
    return kind


def _lock_user(session: Any, user_id: str) -> None:
    from app.services.billing import service

    service._lock_user_row(session, user_id)


def balance(session: Any, user_id: str, kind: str) -> int:
    from sqlalchemy import select

    from app.models.db.premium_credit import PremiumCreditLedger

    latest = session.execute(
        select(PremiumCreditLedger.balance_after)
        .where(PremiumCreditLedger.user_id == user_id, PremiumCreditLedger.kind == _check_kind(kind))
        .order_by(PremiumCreditLedger.id.desc())
        .limit(1)
    ).scalars().first()
    return int(latest) if latest is not None else 0


def _append(session: Any, user_id: str, kind: str, delta: int, reason: str, job_id: str | None) -> int:
    from app.models.db.premium_credit import PremiumCreditLedger

    after = balance(session, user_id, kind) + int(delta)
    if after < 0:
        raise InsufficientPremiumCredits(kind, -int(delta), after - int(delta))
    session.add(
        PremiumCreditLedger(
            user_id=user_id,
            kind=kind,
            delta=int(delta),
            reason=_fit(reason),
            job_id=job_id,
            balance_after=after,
        )
    )
    session.flush()
    return after


def grant(session: Any, user_id: str, kind: str, amount: int, reason: str, job_id: str | None = None) -> int:
    if int(amount) <= 0:
        raise ValueError("grant amount must be positive")
    _lock_user(session, user_id)
    return _append(session, user_id, _check_kind(kind), int(amount), reason, job_id)


def debit(session: Any, user_id: str, kind: str, amount: int, reason: str, job_id: str | None = None) -> int:
    """Take ``amount`` credits of ``kind``; raises :class:`InsufficientPremiumCredits`."""
    if int(amount) <= 0:
        raise ValueError("debit amount must be positive")
    _lock_user(session, user_id)
    return _append(session, user_id, _check_kind(kind), -int(amount), reason, job_id)


def has_reason(session: Any, user_id: str, reason: str) -> bool:
    from sqlalchemy import select

    from app.models.db.premium_credit import PremiumCreditLedger

    return session.execute(
        select(PremiumCreditLedger.id)
        .where(PremiumCreditLedger.user_id == user_id, PremiumCreditLedger.reason == _fit(reason))
        .limit(1)
    ).first() is not None


def job_net_debit(session: Any, job_id: str, kind: str) -> tuple[str | None, int]:
    """``(user_id, credits still held)`` for a job: debits minus returns."""
    from sqlalchemy import select

    from app.models.db.premium_credit import PremiumCreditLedger

    rows = session.execute(
        select(PremiumCreditLedger.user_id, PremiumCreditLedger.delta).where(
            PremiumCreditLedger.job_id == job_id, PremiumCreditLedger.kind == kind
        )
    ).all()
    if not rows:
        return None, 0
    return str(rows[0][0]), max(0, -sum(int(delta) for _, delta in rows))


# --------------------------------------------------------------------------- #
# Own-session operations (purchases, refunds, settlement, reads)
# --------------------------------------------------------------------------- #
def grant_purchase_once(user_id: str, pack: PremiumPack, *, provider: str, reference: str) -> int:
    """Credit a paid pack once per payment. Returns credits granted (0 if already)."""
    from app.models.db.base import get_session

    reason = _fit(f"purchase:{provider}:{reference}")
    with get_session() as session:
        _lock_user(session, user_id)
        if has_reason(session, user_id, reason):
            return 0
        _append(session, user_id, pack.kind, pack.credits, reason, None)
    logger.info(f"premium credits: granted {pack.credits} {pack.kind} user={user_id} ref={reference}")
    return pack.credits


def clawback_by_reference(provider: str, reference: str) -> int:
    """Remove a refunded premium pack's unspent credits once (bounded by balance).

    Returns the credits removed; 0 when the payment was not a premium pack, was
    already clawed back, or its credits are already spent.
    """
    from sqlalchemy import select

    from app.models.db.base import get_session
    from app.models.db.premium_credit import PremiumCreditLedger

    ref = str(reference or "").strip()
    if not ref:
        return 0
    purchase = _fit(f"purchase:{provider}:{ref}")
    refund = _fit(f"refund:{provider}:{ref}")
    with get_session() as session:
        row = session.execute(
            select(PremiumCreditLedger.user_id, PremiumCreditLedger.kind, PremiumCreditLedger.delta)
            .where(PremiumCreditLedger.reason == purchase, PremiumCreditLedger.delta > 0)
            .limit(1)
        ).first()
        if row is None:
            return 0
        user_id, kind, granted = str(row[0]), str(row[1]), int(row[2])
        _lock_user(session, user_id)
        if has_reason(session, user_id, refund):
            return 0
        amount = min(granted, balance(session, user_id, kind))
        if amount <= 0:
            logger.warning(f"premium refund {ref}: user={user_id} already spent the credits")
            return 0
        _append(session, user_id, kind, -amount, refund, None)
    logger.info(f"premium credits: clawed back {amount} {kind} for refunded payment {ref}")
    return amount


def refund_job_once(job_id: str, reason: str = REFUND_REASON) -> dict[str, int]:
    """Return every premium credit a job still holds (idempotent, never raises)."""
    refunded = {kind: 0 for kind in KINDS}
    if not job_id:
        return refunded
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            for kind in KINDS:
                user_id, held = job_net_debit(session, job_id, kind)
                if user_id is None or held <= 0:
                    continue
                _lock_user(session, user_id)
                user_id, held = job_net_debit(session, job_id, kind)
                if held > 0:
                    _append(session, str(user_id), kind, held, f"{reason}:{job_id}", job_id)
                    refunded[kind] = held
    except Exception as exc:  # noqa: BLE001 - a refund failure must not mask the caller
        logger.error(f"premium refund failed for job {job_id}: {exc}")
    return refunded


def settle_ai_video_once(job_id: str, measured_provider_usd: float) -> int:
    """Keep 3x the measured cost (never more than reserved); return the surplus."""
    if not job_id:
        return 0
    try:
        from app.models.db.base import get_session

        final = ai_video_credits_for_usd(measured_provider_usd)
        with get_session() as session:
            user_id, held = job_net_debit(session, job_id, KIND_AI_VIDEO)
            if user_id is None or held <= final:
                return 0
            _lock_user(session, user_id)
            user_id, held = job_net_debit(session, job_id, KIND_AI_VIDEO)
            surplus = held - final
            if surplus <= 0:
                return 0
            _append(session, str(user_id), KIND_AI_VIDEO, surplus, f"{SETTLE_REASON}:{job_id}", job_id)
        logger.info(f"ai video settle job={job_id} measured=${measured_provider_usd:.4f} returned={surplus}")
        return surplus
    except Exception as exc:  # noqa: BLE001 - settlement must never break the pipeline
        logger.error(f"ai video settle failed for job {job_id}: {exc}")
        return 0


def balances(user_id: str) -> dict[str, Any]:
    """``{premium_voice, ai_video, unavailable}`` for display (never raises)."""
    out: dict[str, Any] = {kind: 0 for kind in KINDS}
    out["unavailable"] = False
    try:
        from app.models.db.base import get_session

        with get_session() as session:
            for kind in KINDS:
                out[kind] = balance(session, user_id, kind)
    except Exception as exc:  # noqa: BLE001 - display only
        logger.warning(f"premium balances unavailable for user={user_id}: {type(exc).__name__}")
        out["unavailable"] = True
    return out


__all__ = [
    "AI_VIDEO_MARKUP",
    "InsufficientPremiumCredits",
    "KIND_AI_VIDEO",
    "KIND_PREMIUM_VOICE",
    "PremiumPack",
    "ai_video_credits_for_usd",
    "balance",
    "balances",
    "clawback_by_reference",
    "debit",
    "get_pack",
    "grant",
    "grant_purchase_once",
    "list_packs",
    "pack_for_products",
    "refund_job_once",
    "settle_ai_video_once",
]
