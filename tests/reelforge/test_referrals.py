"""Unit tests for the referral credit system (Phase-7 growth loop).

Runs against an in-memory SQLite DB built from the live ORM metadata, so the
tests exercise the real :class:`CreditRepository.grant` append-only ledger
path — no fakes for the money-touching code. Covered behaviour:

* stable / URL-safe code generation,
* referrer + referee both credited with the contract reasons,
* self-referral rejected,
* double-redeem rejected (durable ledger guard),
* unknown / empty code and empty user rejected,
* ``referral_stats`` derives count + credits from the ledger.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import CreditLedger, User
from app.models.db.repositories import CreditRepository
from app.services import referrals


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def session_factory():
    """In-memory SQLite session factory sharing one connection (StaticPool)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@contextmanager
def _session(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_user(session, email: str) -> str:
    user = User(email=email, credits=0)
    session.add(user)
    session.flush()
    return user.id


# --------------------------------------------------------------------------- #
# generate_referral_code
# --------------------------------------------------------------------------- #
def test_generate_referral_code_is_stable_and_url_safe():
    code_a = referrals.generate_referral_code("user-123")
    code_b = referrals.generate_referral_code("user-123")

    assert code_a == code_b  # deterministic / stable
    assert len(code_a) == referrals.REFERRAL_CODE_LENGTH
    # base32 alphabet only -> inherently URL-safe, no padding.
    assert set(code_a) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def test_generate_referral_code_differs_per_user():
    assert referrals.generate_referral_code("user-1") != referrals.generate_referral_code(
        "user-2"
    )


def test_generate_referral_code_rejects_empty():
    with pytest.raises(ValueError):
        referrals.generate_referral_code("")


# --------------------------------------------------------------------------- #
# redeem_referral — happy path
# --------------------------------------------------------------------------- #
def test_redeem_referral_grants_both_parties(session_factory):
    with _session(session_factory) as s:
        referrer_id = _make_user(s, "referrer@example.com")
        referee_id = _make_user(s, "referee@example.com")
        code = referrals.generate_referral_code(referrer_id)

        result = referrals.redeem_referral(s, referee_id, code)

        assert result["ok"] is True
        assert result["referrer_id"] == referrer_id
        assert result["referee_id"] == referee_id
        assert result["referrer_grant"] == referrals.DEFAULT_REFERRER_GRANT
        assert result["referee_grant"] == referrals.DEFAULT_REFEREE_GRANT

        credits = CreditRepository(s)
        assert credits.balance(referrer_id) == referrals.DEFAULT_REFERRER_GRANT
        assert credits.balance(referee_id) == referrals.DEFAULT_REFEREE_GRANT

        reasons = {
            row.user_id: row.reason
            for row in s.query(CreditLedger).all()
        }
        assert reasons[referrer_id] == referrals.REASON_REFERRAL_BONUS
        assert reasons[referee_id] == referrals.REASON_REFERRAL_REDEEM


def test_redeem_referral_does_not_leak_referrer_balance(session_factory):
    """The success envelope must not disclose the referrer's credit balance.

    When user A redeems user B's code, the response is returned to A. Exposing
    B's post-grant balance would leak another user's private financial data.
    """
    with _session(session_factory) as s:
        referrer_id = _make_user(s, "owner@example.com")
        referee_id = _make_user(s, "guest@example.com")
        code = referrals.generate_referral_code(referrer_id)

        result = referrals.redeem_referral(s, referee_id, code)

        assert result["ok"] is True
        # Caller may see their own balance...
        assert result["referee_balance"] == referrals.DEFAULT_REFEREE_GRANT
        # ...but never the referrer's.
        assert "referrer_balance" not in result


def test_redeem_referral_locks_referee_row_before_guard(session_factory, monkeypatch):
    """The double-redeem guard must be re-checked under the FOR UPDATE lock.

    Regression guard for the TOCTOU race: ``_locked_balance(new_user_id)`` must
    be acquired *before* the authoritative ``_has_redeemed`` re-check so two
    concurrent redemptions serialize on the referee row instead of both racing
    past a stale pre-lock read.
    """
    events: list[str] = []
    real_locked = CreditRepository._locked_balance
    real_has_redeemed = referrals._has_redeemed

    def spy_locked(self, user_id):
        events.append(f"lock:{user_id}")
        return real_locked(self, user_id)

    def spy_has_redeemed(session, user_id):
        events.append(f"guard:{user_id}")
        return real_has_redeemed(session, user_id)

    monkeypatch.setattr(CreditRepository, "_locked_balance", spy_locked)
    monkeypatch.setattr(referrals, "_has_redeemed", spy_has_redeemed)

    with _session(session_factory) as s:
        referrer_id = _make_user(s, "lock-ref@example.com")
        referee_id = _make_user(s, "lock-new@example.com")
        code = referrals.generate_referral_code(referrer_id)

        result = referrals.redeem_referral(s, referee_id, code)

    assert result["ok"] is True
    # A lock acquisition on the referee row must occur, and a guard re-check on
    # that same referee row must follow it (authoritative check under the lock).
    lock_idx = events.index(f"lock:{referee_id}")
    guard_after = [
        i
        for i, e in enumerate(events)
        if e == f"guard:{referee_id}" and i > lock_idx
    ]
    assert guard_after, f"guard not re-checked after lock; events={events}"


def test_redeem_referral_custom_grant_amounts(session_factory):
    with _session(session_factory) as s:
        referrer_id = _make_user(s, "r@example.com")
        referee_id = _make_user(s, "e@example.com")
        code = referrals.generate_referral_code(referrer_id)

        result = referrals.redeem_referral(
            s, referee_id, code, referrer_grant=25, referee_grant=7
        )

        assert result["ok"] is True
        assert CreditRepository(s).balance(referrer_id) == 25
        assert CreditRepository(s).balance(referee_id) == 7


# --------------------------------------------------------------------------- #
# redeem_referral — guards
# --------------------------------------------------------------------------- #
def test_redeem_referral_rejects_self_referral(session_factory):
    with _session(session_factory) as s:
        user_id = _make_user(s, "solo@example.com")
        code = referrals.generate_referral_code(user_id)

        result = referrals.redeem_referral(s, user_id, code)

        assert result["ok"] is False
        assert result["error"] == "self_referral"
        # No credits were granted to anyone.
        assert CreditRepository(s).balance(user_id) == 0
        assert s.query(CreditLedger).count() == 0


def test_redeem_referral_rejects_double_redeem(session_factory):
    with _session(session_factory) as s:
        referrer_id = _make_user(s, "ref@example.com")
        referee_id = _make_user(s, "new@example.com")
        code = referrals.generate_referral_code(referrer_id)

        first = referrals.redeem_referral(s, referee_id, code)
        second = referrals.redeem_referral(s, referee_id, code)

        assert first["ok"] is True
        assert second["ok"] is False
        assert second["error"] == "already_redeemed"

        # Referee balance unchanged after the blocked second redemption.
        assert CreditRepository(s).balance(referee_id) == referrals.DEFAULT_REFEREE_GRANT
        # Exactly two ledger rows total (one per party), no extras.
        assert s.query(CreditLedger).count() == 2


def test_redeem_referral_second_code_still_blocked(session_factory):
    """A user who redeemed once cannot redeem a *different* valid code."""
    with _session(session_factory) as s:
        ref_a = _make_user(s, "a@example.com")
        ref_b = _make_user(s, "b@example.com")
        referee_id = _make_user(s, "c@example.com")

        first = referrals.redeem_referral(
            s, referee_id, referrals.generate_referral_code(ref_a)
        )
        second = referrals.redeem_referral(
            s, referee_id, referrals.generate_referral_code(ref_b)
        )

        assert first["ok"] is True
        assert second["ok"] is False
        assert second["error"] == "already_redeemed"
        assert CreditRepository(s).balance(ref_b) == 0


def test_redeem_referral_rejects_unknown_code(session_factory):
    with _session(session_factory) as s:
        referee_id = _make_user(s, "x@example.com")

        result = referrals.redeem_referral(s, referee_id, "ZZZZZZZZ")

        assert result["ok"] is False
        assert result["error"] == "invalid_code"


def test_redeem_referral_rejects_empty_inputs(session_factory):
    with _session(session_factory) as s:
        referee_id = _make_user(s, "y@example.com")

        assert referrals.redeem_referral(s, "", "CODE")["error"] == "invalid_input"
        assert referrals.redeem_referral(s, referee_id, "")["error"] == "invalid_input"
        assert (
            referrals.redeem_referral(s, referee_id, "CODE", referrer_grant=0)["error"]
            == "invalid_input"
        )


# --------------------------------------------------------------------------- #
# referral_stats
# --------------------------------------------------------------------------- #
def test_referral_stats_counts_and_sums_bonuses(session_factory):
    with _session(session_factory) as s:
        referrer_id = _make_user(s, "influencer@example.com")
        code = referrals.generate_referral_code(referrer_id)

        for i in range(3):
            referee_id = _make_user(s, f"fan{i}@example.com")
            assert referrals.redeem_referral(s, referee_id, code)["ok"] is True

        stats = referrals.referral_stats(s, referrer_id)

        assert stats["code"] == code
        assert stats["referred_count"] == 3
        assert stats["credits_earned"] == 3 * referrals.DEFAULT_REFERRER_GRANT


def test_referral_stats_zero_for_new_user(session_factory):
    with _session(session_factory) as s:
        user_id = _make_user(s, "fresh@example.com")

        stats = referrals.referral_stats(s, user_id)

        assert stats["code"] == referrals.generate_referral_code(user_id)
        assert stats["referred_count"] == 0
        assert stats["credits_earned"] == 0


def test_referral_stats_rejects_empty_user():
    with pytest.raises(ValueError):
        referrals.referral_stats(object(), "")  # type: ignore[arg-type]
