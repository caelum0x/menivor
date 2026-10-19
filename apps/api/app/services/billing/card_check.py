"""$1 card check that unlocks a web account's free reels (Creem).

Mirrors Rally's card-required trial: Creem has no save-card-without-charge
checkout for one-time products, so a card is verified by a real $1 one-time
payment that is credited to the buyer (1 reel credit) and, on the same
confirmation, unlocks the one-time free signup reels (``SIGNUP_GRANT``).

Every step is idempotent: the $1 credit uses the shared purchase ledger reason
``purchase:creem:<checkout_id>`` (so the signed redirect and the webhook never
both grant it) and the free reels use :func:`service.grant_signup_credits`
(ledger reason ``"signup"``, once per user for life).

A user counts as *unlocked* once they hold any signup grant (web, or mobile
before linking) or have paid for anything — so accounts that already paid or
received the free reels are never asked again.

Repeat checks (MN3): the free signup reels go to one person once. A card
fingerprint or a normalized email (Gmail dots and ``+tags`` folded) already
used for someone else's free grant still gets the paid $1 credit, but no free
reels; :func:`status` reports ``free_credits: 0`` for such an account so the
page never promises reels it will not grant.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit

from loguru import logger

from app.config import config

CARD_CHECK_KEY: str = "card_check"
CARD_CHECK_PRICE_USD: float = 1.0
# The $1 is credited 1:1 as reel credit (one reel).
CARD_CHECK_CREDITS: int = 1

# Ledger reasons that mean the account already got its free reels.
_SIGNUP_REASONS: tuple[str, ...] = (
    "signup",
    "mobile_device_signup",
    "mobile_identity_signup",
)
_PURCHASE_REASON_PREFIX: str = "purchase:"

_DEFAULT_NEXT: str = "/create"
_MAX_NEXT_LEN: int = 700


class CardCheckUnavailable(RuntimeError):
    """Creem or the card-check product is not configured on this server."""


class AlreadyUnlocked(RuntimeError):
    """The account already has its free reels (or has paid before)."""


def _creem() -> dict[str, Any]:
    section = getattr(config, "creem", None) or {}
    try:
        return dict(section)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return {}


class PaymentsPaused(RuntimeError):
    """Payments are paused: no card check is needed (free monthly reels instead)."""


def _provider() -> str:
    from app.services.billing import payments_mode

    return payments_mode.active_provider()


def product_id() -> str:
    """The Creem card-check product id (used to recognise Creem redirects)."""
    return str(_creem().get("card_check_product_id", "") or "").strip()


def is_available() -> bool:
    """True when a card check can be started with the active provider."""
    provider = _provider()
    if provider == "dodo":
        from app.services.billing import dodo_client

        return dodo_client.is_configured() and bool(dodo_client.card_check_product_id())
    if provider == "creem":
        return bool(str(_creem().get("api_key", "") or "").strip() and product_id())
    return False


def web_base_url() -> str:
    raw = str(_creem().get("web_base_url", "") or "").strip().rstrip("/")
    return raw or "https://menivor.com"


def safe_next(value: str | None) -> str:
    """A same-site relative path to continue to after paying (default /create)."""
    raw = str(value or "").strip()
    if not raw or len(raw) > _MAX_NEXT_LEN:
        return _DEFAULT_NEXT
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return _DEFAULT_NEXT
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc:
        return _DEFAULT_NEXT
    return raw


def success_url(next_path: str | None) -> str:
    """Public return URL for the card check: the onboarding page confirms the
    signed redirect and then continues to ``next``."""
    nxt = safe_next(next_path)
    return f"{web_base_url()}/onboarding?checkout=return&next={quote(nxt, safe='')}"


def is_unlocked(session: Any, user_id: str) -> bool:
    """True once the user holds a signup grant or any paid purchase."""
    from sqlalchemy import or_, select

    from app.models.db.models import CreditLedger

    stmt = (
        select(CreditLedger.id)
        .where(
            CreditLedger.user_id == user_id,
            or_(
                CreditLedger.reason.in_(_SIGNUP_REASONS),
                CreditLedger.reason.like(f"{_PURCHASE_REASON_PREFIX}%"),
            ),
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def has_signup_grant(session: Any, user_id: str) -> bool:
    """True once the user received any free signup grant (web or mobile)."""
    from sqlalchemy import select

    from app.models.db.models import CreditLedger

    stmt = (
        select(CreditLedger.id)
        .where(CreditLedger.user_id == user_id, CreditLedger.reason.in_(_SIGNUP_REASONS))
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def _grant_signals(session: Any, user_id: str, card_fingerprint: str = "") -> dict[str, str]:
    from app.models.db.models import User
    from app.services.abuse import grant_markers

    user = session.get(User, user_id)
    return grant_markers.merge(
        grant_markers.email_signals(getattr(user, "email", "") if user is not None else ""),
        {grant_markers.KIND_CARD: str(card_fingerprint or "").strip()},
    )


def signup_grant_allowed(session: Any, user_id: str, card_fingerprint: str = "") -> bool:
    """False when this email or card already funded someone else's free reels."""
    from app.services.abuse import grant_markers

    return grant_markers.grant_allowed(session, user_id, _grant_signals(session, user_id, card_fingerprint))


def status(session: Any, user_id: str) -> dict[str, Any]:
    """UI view of the unlock step for ``user_id``.

    While payments are paused the card check is not required and the account
    reports as unlocked (the caller grants the month's free reels first via
    :func:`payments_mode.grant_free_monthly`).
    """
    from app.models.db.repositories import CreditRepository
    from app.services.billing import payments_mode

    from app.services.billing import first_reel

    provider = payments_mode.active_provider()
    paused = provider == payments_mode.NONE
    unlocked = True if paused else is_unlocked(session, user_id)
    credits = int(CreditRepository(session).balance(user_id))
    return {
        "paused": paused,
        "provider": provider,
        "free_monthly_reels": payments_mode.free_monthly_reels() if paused else 0,
        "unlocked": unlocked,
        # A new account may make its free first reel before the card check.
        "first_reel_ready": first_reel.ready(session, user_id, unlocked=unlocked, credits=credits),
        "available": is_available(),
        "credits": credits,
        "price_usd": CARD_CHECK_PRICE_USD,
        "card_check_credits": CARD_CHECK_CREDITS,
        "free_credits": _free_credits_view(session, user_id, paused=paused),
    }


def _free_credits_view(session: Any, user_id: str, *, paused: bool) -> int:
    """Free reels this account has or can still get (never a false promise)."""
    from app.services.billing.plans import SIGNUP_GRANT

    if paused or has_signup_grant(session, user_id):
        return int(SIGNUP_GRANT)
    if is_unlocked(session, user_id):
        return 0  # paid the check but the free reels were withheld (repeat)
    return int(SIGNUP_GRANT) if signup_grant_allowed(session, user_id) else 0


def plan() -> dict[str, Any]:
    """The card check as a plan-shaped mapping for the Creem checkout client."""
    return {
        "key": CARD_CHECK_KEY,
        "credits": CARD_CHECK_CREDITS,
        "creem_product_id": product_id(),
    }


def start_checkout(
    user_id: str, next_path: str | None = None, user_email: str = ""
) -> dict[str, str]:
    """Open the $1 checkout with the active provider. Caller checked :func:`is_unlocked`."""
    provider = _provider()
    if provider == "none":
        raise PaymentsPaused("Payments are paused; free reels are granted monthly instead.")
    if not is_available():
        raise CardCheckUnavailable(
            f"Card check is not configured for provider {provider!r}."
        )
    if provider == "dodo":
        from app.services.billing import dodo_client

        result = dodo_client.create_checkout(
            product_id=dodo_client.card_check_product_id(),
            metadata={
                "kind": dodo_client.KIND_CARD_CHECK,
                "user_id": user_id,
                "plan_key": CARD_CHECK_KEY,
                "credits": CARD_CHECK_CREDITS,
            },
            return_url=dodo_client.return_url("/onboarding", next=safe_next(next_path)),
            customer_email=user_email,
        )
        logger.info(f"billing: card-check checkout (dodo) opened for user={user_id}")
        return {"checkout_url": result["checkout_url"], "checkout_id": result["session_id"]}
    from app.services.billing import creem_client

    result = creem_client.create_checkout_session(
        {"id": user_id}, plan(), success_url=success_url(next_path)
    )
    logger.info(f"billing: card-check checkout opened for user={user_id}")
    return {"checkout_url": result["checkout_url"], "checkout_id": result["session_id"]}


def fulfill(
    *,
    user_id: str,
    checkout_id: str,
    external_event_id: str,
    provider: str = "creem",
    card_fingerprint: str = "",
) -> int:
    """Credit the $1 and unlock the free reels, idempotently. Returns the balance.

    The $1 credit is always granted (it was paid for). The free reels are
    withheld when the card fingerprint or the normalized email already funded
    another account's free reels; the grant's signals are recorded otherwise.
    """
    from app.models.db.base import get_session
    from app.models.db.repositories import CreditRepository
    from app.services.abuse import grant_markers
    from app.services.billing import service

    service.fulfill_purchase(
        provider=provider,
        external_event_id=external_event_id,
        user_id=user_id,
        credits=CARD_CHECK_CREDITS,
        reason_ref=checkout_id,
    )
    with get_session() as session:
        if has_signup_grant(session, user_id):
            return int(CreditRepository(session).balance(user_id))
        signals = _grant_signals(session, user_id, card_fingerprint)
        if not grant_markers.grant_allowed(session, user_id, signals):
            return int(CreditRepository(session).balance(user_id))
        grant_markers.record_grant(session, user_id, signals)
    return int(service.grant_signup_credits(user_id))


__all__ = [
    "AlreadyUnlocked",
    "CARD_CHECK_CREDITS",
    "CARD_CHECK_KEY",
    "CARD_CHECK_PRICE_USD",
    "CardCheckUnavailable",
    "PaymentsPaused",
    "fulfill",
    "has_signup_grant",
    "is_available",
    "is_unlocked",
    "plan",
    "product_id",
    "safe_next",
    "signup_grant_allowed",
    "start_checkout",
    "status",
    "success_url",
]
