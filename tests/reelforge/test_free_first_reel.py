"""Free first reel (MENIVOR_FREE_FIRST_REEL): one reel before the $1 card check.

The biggest funnel drop is sign-up -> card check: a new account had to pay $1
before seeing a single reel. With the flag on, a new web account gets exactly
one reel credit (ledger reason ``free_first_reel``) the first time it asks for
its unlock status, so the first value comes before the card.

* flag off: nothing changes (locked, 0 credits);
* flag on: 1 credit once, ``first_reel_ready`` true while it is unspent;
* never for accounts that are already unlocked, and never while paused;
* one per person: a second account with the same normalized email gets none;
* the card check still unlocks the full signup grant afterwards.
"""

from __future__ import annotations

from app.models.db.models import User
from app.models.db.repositories import CreditRepository
from app.services.billing import card_check, first_reel
from app.services.billing.plans import SIGNUP_GRANT
from tests.reelforge.test_card_check import _balance, _hash, env  # noqa: F401

STATUS = "/api/v1/billing/card-check"
HEADERS = {"x-api-key": "rk_web"}


def _status(client, headers=HEADERS):
    resp = client.get(STATUS, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_flag_off_keeps_the_card_check_first(env, monkeypatch):
    client, Factory, user_id, _ = env
    monkeypatch.delenv("MENIVOR_FREE_FIRST_REEL", raising=False)
    data = _status(client)
    assert data["unlocked"] is False
    assert data["credits"] == 0
    assert data["first_reel_ready"] is False
    assert _balance(Factory, user_id) == 0


def test_flag_on_grants_one_reel_once(env, monkeypatch):
    client, Factory, user_id, _ = env
    monkeypatch.setenv("MENIVOR_FREE_FIRST_REEL", "1")
    data = _status(client)
    assert data["unlocked"] is False
    assert data["credits"] == first_reel.FIRST_REEL_CREDITS == 1
    assert data["first_reel_ready"] is True
    # Asking again never grants twice.
    again = _status(client)
    assert again["credits"] == 1
    assert _balance(Factory, user_id) == 1


def test_spent_first_reel_sends_the_account_to_the_card_check(env, monkeypatch):
    client, Factory, user_id, _ = env
    monkeypatch.setenv("MENIVOR_FREE_FIRST_REEL", "1")
    _status(client)
    with Factory() as s:
        CreditRepository(s).debit(user_id, 1, "job_test", "render")
        s.commit()
    data = _status(client)
    assert data["credits"] == 0
    assert data["first_reel_ready"] is False
    assert data["unlocked"] is False
    # The card check still promises (and grants) the full free reels.
    assert data["free_credits"] == SIGNUP_GRANT


def test_unlocked_accounts_get_no_first_reel(env, monkeypatch):
    client, Factory, user_id, _ = env
    monkeypatch.setenv("MENIVOR_FREE_FIRST_REEL", "1")
    with Factory() as s:
        CreditRepository(s).grant(user_id, SIGNUP_GRANT, "signup")
        s.commit()
    data = _status(client)
    assert data["unlocked"] is True
    assert data["credits"] == SIGNUP_GRANT
    assert data["first_reel_ready"] is False


def test_one_first_reel_per_person(env, monkeypatch):
    client, Factory, user_id, _ = env
    monkeypatch.setenv("MENIVOR_FREE_FIRST_REEL", "1")
    _status(client)
    with Factory() as s:
        # The same mailbox once the +tag is folded away.
        s.add(User(email="web+2@example.com", display_name="Twin", api_key_hash=_hash("rk_twin")))
        s.commit()
    data = _status(client, {"x-api-key": "rk_twin"})
    assert data["credits"] == 0
    assert data["first_reel_ready"] is False


def test_card_check_after_first_reel_still_unlocks_free_reels(env, monkeypatch):
    _, Factory, user_id, _ = env
    monkeypatch.setenv("MENIVOR_FREE_FIRST_REEL", "1")
    assert first_reel.maybe_grant(user_id) is True
    balance = card_check.fulfill(user_id=user_id, checkout_id="ch_ffr", external_event_id="evt_ffr")
    assert balance == first_reel.FIRST_REEL_CREDITS + card_check.CARD_CHECK_CREDITS + SIGNUP_GRANT
    with Factory() as s:
        assert card_check.is_unlocked(s, user_id) is True


def test_no_first_reel_while_payments_are_paused(env, monkeypatch):
    _, _, user_id, _ = env
    monkeypatch.setenv("MENIVOR_FREE_FIRST_REEL", "1")
    monkeypatch.setenv("MENIVOR_PAYMENTS_PAUSED", "1")
    assert first_reel.maybe_grant(user_id) is False
