"""Idempotency of the Mint hold.capture settlement path.

The wallet settles a paid-for render by capturing its hold on Mint. Terminal
settlement hooks fire at-least-once (Celery redelivery, retries after a flaky
502), so the SAME ``hold.capture`` can be issued twice with the same idem key.
It must settle EXACTLY once -- one debit off the payer's held funds, one credit
to the treasury -- or the render is double-charged (or the treasury double-paid).

Driven against the in-memory :class:`FakeMint` through a real :class:`MintClient`
(idem-key replay mirrors the live Mint). No network, no live server.
"""

from __future__ import annotations

import pytest

from tests.reelforge.conftest_mint import FakeMint, make_mint_client


@pytest.fixture()
def fake() -> FakeMint:
    return FakeMint()


@pytest.fixture()
def client(fake: FakeMint):
    return make_mint_client(fake)


def test_duplicate_capture_same_hold_settles_once(fake, client):
    payer = client.create_account()
    hold = client.create_hold(
        from_account=payer, amount_micros=600_000, idem_key="job:hold"
    )
    hold_id = hold["hold_id"]
    start_available = fake.accounts[payer]["available"]  # after the 600k hold

    first = client.capture_hold(
        hold_id, amount_micros=420_000, to=fake.treasury_id, idem_key="job:capture"
    )
    # Second, identical capture (redelivered terminal hook) -- SAME idem key.
    second = client.capture_hold(
        hold_id, amount_micros=420_000, to=fake.treasury_id, idem_key="job:capture"
    )

    assert first["captured_micros"] == 420_000
    assert first["idempotent_replay"] is False
    # The replay returns the same receipt and is flagged, not re-applied.
    assert second["idempotent_replay"] is True
    assert second["captured_micros"] == 420_000

    # Money moved exactly once: treasury credited 420k once (not 840k), the hold
    # is fully cleared, and the payer got the 180k uncaptured remainder back once.
    assert fake.accounts[fake.treasury_id]["available"] == 420_000
    assert fake.accounts[payer]["held"] == 0
    assert fake.accounts[payer]["available"] == start_available + 180_000


def test_duplicate_receipted_capture_returns_identical_attestation(fake, client):
    """The receipted path replays the same signed attestation, not a new one."""
    payer = client.create_account()
    hold = client.create_hold(
        from_account=payer, amount_micros=600_000, idem_key="job2:hold"
    )
    hold_id = hold["hold_id"]

    first_data, first_receipt = client.capture_hold_with_receipt(
        hold_id,
        amount_micros=500_000,
        to=fake.treasury_id,
        idem_key="job2:capture",
        ref="gateway_job_2",
    )
    second_data, second_receipt = client.capture_hold_with_receipt(
        hold_id,
        amount_micros=500_000,
        to=fake.treasury_id,
        idem_key="job2:capture",
        ref="gateway_job_2",
    )

    assert first_data["idempotent_replay"] is False
    assert second_data["idempotent_replay"] is True
    # Same signed evidence -> same receipt hash + signature (byte-for-byte).
    assert second_receipt["hash"] == first_receipt["hash"]
    assert second_data["attestation"] == first_data["attestation"]

    # And the ledger settled once.
    assert fake.accounts[fake.treasury_id]["available"] == 500_000
    assert fake.accounts[payer]["held"] == 0
