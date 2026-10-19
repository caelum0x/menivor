"""Referral credit system — the ReelForge growth loop (Phase 7).

Pure business logic layered on top of the existing persistence primitives
(``app.models.db.models`` + ``app.models.db.repositories.CreditRepository``).
This module deliberately owns **no** schema: it never mutates the ORM models
and references the DB-team-owned ``User.referral_code`` column *defensively*
via :func:`getattr`, so it keeps working whether or not that column has landed
yet.

Design invariants
-----------------
* **Stable codes.** :func:`generate_referral_code` is a pure, deterministic
  function of the ``user_id`` — the same user always yields the same URL-safe
  code, so no code has to be persisted for the loop to work.
* **Append-only credits.** Both sides of a redemption are granted through
  :class:`CreditRepository.grant`, which writes immutable ledger rows. We never
  touch ``credit_ledger`` rows in place.
* **Idempotent redemption.** A user may redeem at most once. The durable guard
  is the ledger itself: a pre-existing ``referral_redeem`` row for the new user
  blocks any second redemption, mirroring the billing service's
  ledger-reason dedupe (no Redis dependency required).

The three public entry points are :func:`generate_referral_code`,
:func:`redeem_referral` and :func:`referral_stats`.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db.models import CreditLedger, User
from app.models.db.repositories import CreditRepository

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
#: Length (characters) of a generated referral code. ~8 chars of base32 gives
#: 40 bits of entropy — plenty for a per-user handle while staying easy to type.
REFERRAL_CODE_LENGTH: int = 8

#: Ledger ``reason`` written for the *referrer* (the inviting user).
REASON_REFERRAL_BONUS: str = "referral_bonus"

#: Ledger ``reason`` written for the *referee* (the invited/new user). Its
#: presence is ALSO the durable double-redeem guard for the referee.
REASON_REFERRAL_REDEEM: str = "referral_redeem"

#: Default grant amounts (credits). Callers may override per-campaign.
DEFAULT_REFERRER_GRANT: int = 10
DEFAULT_REFEREE_GRANT: int = 5


# --------------------------------------------------------------------------- #
# Code generation
# --------------------------------------------------------------------------- #
def generate_referral_code(user_id: str) -> str:
    """Return a stable, URL-safe ~8-char referral code for ``user_id``.

    The code is a deterministic function of the user id (SHA-256 → base32),
    so it is reproducible without being stored and never collides for distinct
    ids in practice. base32 (RFC 4648) uses only ``A-Z2-7`` — inherently
    URL-safe and unambiguous when spoken aloud.

    Args:
        user_id: The owning user's primary-key id. Must be non-empty.

    Returns:
        An uppercase base32 code of length :data:`REFERRAL_CODE_LENGTH`.

    Raises:
        ValueError: If ``user_id`` is empty/whitespace.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required to generate a referral code")

    digest = hashlib.sha256(str(user_id).encode("utf-8")).digest()
    # base32 avoids the '-'/'_'/'=' characters of urlsafe_b64 and the visual
    # ambiguity of base62; strip padding and take a fixed-width prefix.
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=")
    return encoded[:REFERRAL_CODE_LENGTH].upper()


def _normalize_code(code: str) -> str:
    """Normalize an inbound code for comparison (trim + uppercase)."""
    return (code or "").strip().upper()


# --------------------------------------------------------------------------- #
# Referrer lookup (defensive against the optional User.referral_code column)
# --------------------------------------------------------------------------- #
def _stored_code_for(user: Any) -> str:
    """Return the persisted ``referral_code`` for a user, or ``""``.

    Read defensively via :func:`getattr` so this works before the DB team's
    ``User.referral_code`` migration has landed.
    """
    value = getattr(user, "referral_code", None)
    return _normalize_code(value) if value else ""


def code_for_user(session: Session, user_id: str) -> str:
    """Resolve the canonical referral code for a user.

    Prefers a persisted ``User.referral_code`` (if the column exists and is
    populated) so an externally-assigned code is honored; otherwise falls back
    to the deterministic :func:`generate_referral_code`.
    """
    user = session.get(User, user_id)
    stored = _stored_code_for(user) if user is not None else ""
    return stored or generate_referral_code(user_id)


def _find_referrer_id(session: Session, code: str) -> str | None:
    """Find the user id that owns ``code``, or ``None`` if unknown.

    Two lookup strategies, tried in order:

    1. **Column query** — when ``User.referral_code`` exists, match it directly
       (case-insensitive). Wrapped in a try/except so a model that declares the
       attribute while the physical column is still absent degrades gracefully.
    2. **Deterministic scan** — because :func:`generate_referral_code` is a pure
       function of the id, we can recompute each user's code and compare. This
       keeps the loop working before the column migration and catches users
       whose code was never persisted.
    """
    target = _normalize_code(code)
    if not target:
        return None

    column = getattr(User, "referral_code", None)
    if column is not None:
        try:
            stmt = (
                select(User.id)
                .where(func.upper(column) == target)
                .limit(1)
            )
            row = session.execute(stmt).first()
            if row is not None:
                return row[0]
        except Exception as exc:  # column declared but not yet migrated, etc.
            logger.debug(f"referral_code column lookup unavailable: {exc}")

    # Deterministic fallback: recompute the code for each user id.
    for (uid,) in session.execute(select(User.id)).all():
        if generate_referral_code(uid) == target:
            return uid
    return None


# --------------------------------------------------------------------------- #
# Redemption
# --------------------------------------------------------------------------- #
def _has_redeemed(session: Session, user_id: str) -> bool:
    """True if ``user_id`` already has a ``referral_redeem`` ledger row.

    This is the durable, Redis-free double-redeem guard: the append-only
    ledger is the single source of truth for whether a user has ever redeemed.
    """
    stmt = (
        select(CreditLedger.id)
        .where(
            CreditLedger.user_id == user_id,
            CreditLedger.reason == REASON_REFERRAL_REDEEM,
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def redeem_referral(
    session: Session,
    new_user_id: str,
    code: str,
    referrer_grant: int = DEFAULT_REFERRER_GRANT,
    referee_grant: int = DEFAULT_REFEREE_GRANT,
) -> dict:
    """Redeem ``code`` on behalf of ``new_user_id``, granting both parties.

    Guards, in order:

    * **Validation** — ``new_user_id`` and ``code`` must be non-empty; grants
      must be positive.
    * **Unknown code** — the code must resolve to an existing referrer.
    * **Self-referral** — a user cannot redeem their own code.
    * **Double-redeem** — a user may redeem at most once (durable ledger guard).

    On success the referrer is granted ``referrer_grant`` credits with reason
    ``referral_bonus`` and the referee (``new_user_id``) is granted
    ``referee_grant`` credits with reason ``referral_redeem``.

    Args:
        session: Active SQLAlchemy session (transaction owned by the caller /
            ``get_session``). Grants are flushed but not committed here.
        new_user_id: The redeeming (invited) user's id.
        code: The referral code being redeemed.
        referrer_grant: Credits granted to the inviting user (must be > 0).
        referee_grant: Credits granted to the invited user (must be > 0).

    Returns:
        A JSON-serializable result envelope. On success::

            {"ok": True, "referrer_id": ..., "referee_id": ...,
             "referrer_grant": int, "referee_grant": int,
             "referee_balance": int}

        The referrer's post-grant balance is intentionally omitted — it is
        another user's private financial data and must not be disclosed to the
        redeeming caller.

        On any guarded failure::

            {"ok": False, "error": <slug>, "message": <human text>}

        where ``error`` is one of ``invalid_input``, ``invalid_code``,
        ``self_referral`` or ``already_redeemed``.
    """
    if not new_user_id or not str(new_user_id).strip():
        return _error("invalid_input", "new_user_id is required")
    if not code or not str(code).strip():
        return _error("invalid_input", "referral code is required")
    if referrer_grant <= 0 or referee_grant <= 0:
        return _error("invalid_input", "grant amounts must be positive")

    referrer_id = _find_referrer_id(session, code)
    if referrer_id is None:
        return _error("invalid_code", "referral code not recognized")

    if referrer_id == new_user_id:
        return _error("self_referral", "cannot redeem your own referral code")

    # Fast, unlocked pre-check: short-circuits obvious re-redemptions without
    # taking a row lock. NOT authoritative on its own — see the locked re-check
    # below.
    if _has_redeemed(session, new_user_id):
        return _error(
            "already_redeemed", "this user has already redeemed a referral"
        )

    credits = CreditRepository(session)
    # Close the TOCTOU double-redeem race: acquire the ``FOR UPDATE`` lock on
    # the referee's User row, then re-run the durable ledger guard *under* that
    # held lock. Two concurrent redemptions for the same ``new_user_id`` now
    # serialize here — the first commits its ``referral_redeem`` row, and the
    # second blocks on the lock, then observes that committed row and is
    # rejected instead of racing past a stale (pre-lock) read.
    credits._locked_balance(new_user_id)
    if _has_redeemed(session, new_user_id):
        return _error(
            "already_redeemed", "this user has already redeemed a referral"
        )

    # Grant the referee first: its ``referral_redeem`` row is the durable
    # double-redeem marker, so writing it before the referrer bonus means a
    # crash between the two grants can never silently drop the guard.
    referee_entry = credits.grant(
        new_user_id, referee_grant, REASON_REFERRAL_REDEEM
    )
    credits.grant(referrer_id, referrer_grant, REASON_REFERRAL_BONUS)

    logger.info(
        f"referral redeemed: referrer={referrer_id} (+{referrer_grant}) "
        f"referee={new_user_id} (+{referee_grant})"
    )
    return {
        "ok": True,
        "referrer_id": referrer_id,
        "referee_id": new_user_id,
        "referrer_grant": referrer_grant,
        "referee_grant": referee_grant,
        # Only the caller's own (referee) balance is disclosed. The referrer's
        # post-grant balance is deliberately NOT returned: it is another user's
        # private financial data and must never leak to the redeeming party.
        "referee_balance": referee_entry.balance_after,
    }


def _error(error: str, message: str) -> dict:
    """Build a uniform failure envelope for :func:`redeem_referral`."""
    return {"ok": False, "error": error, "message": message}


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def referral_stats(session: Session, user_id: str) -> dict:
    """Return a user's referral code and lifetime referral performance.

    ``referred_count`` and ``credits_earned`` are derived purely from the
    append-only ledger: every successful redemption writes exactly one
    ``referral_bonus`` row for the referrer, so counting/summing those rows is
    an exact, self-healing measure of the growth loop.

    Args:
        session: Active SQLAlchemy session.
        user_id: The user whose stats to compute. Must be non-empty.

    Returns:
        ``{"code": str, "referred_count": int, "credits_earned": int}``.

    Raises:
        ValueError: If ``user_id`` is empty/whitespace.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError("user_id is required for referral stats")

    stmt = select(
        func.count(CreditLedger.id),
        func.coalesce(func.sum(CreditLedger.delta), 0),
    ).where(
        CreditLedger.user_id == user_id,
        CreditLedger.reason == REASON_REFERRAL_BONUS,
    )
    referred_count, credits_earned = session.execute(stmt).one()

    return {
        "code": code_for_user(session, user_id),
        "referred_count": int(referred_count or 0),
        "credits_earned": int(credits_earned or 0),
    }


__all__ = [
    "REFERRAL_CODE_LENGTH",
    "REASON_REFERRAL_BONUS",
    "REASON_REFERRAL_REDEEM",
    "code_for_user",
    "generate_referral_code",
    "redeem_referral",
    "referral_stats",
]
