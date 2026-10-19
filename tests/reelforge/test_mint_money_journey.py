"""Golden Menivor money journey: checkout -> webhook -> render settlement.

This deliberately crosses the wallet service boundaries that used to disagree
about the source of truth.  The production checkout/webhook/bridge code talks
through the real ``MintClient`` HTTP encoding to the in-memory Mint transport;
only Creem's hosted page and the network socket are replaced.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.reels.wallet_bridge import WalletIntent, reserve_for_job, settle_job_actual
from app.domains.wallet.service import WalletService
from app.domains.wallet.webhooks import process_creem_wallet_webhook
from app.models.db.base import Base
from app.models.db.models import User
from tests.reelforge.conftest_mint import FakeMint, make_mint_client


def test_paid_checkout_funds_the_same_account_rendering_settles(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    fake = FakeMint(default_balance=0)
    mint = make_mint_client(fake)

    from app.domains.wallet import mint_client as mint_client_mod
    from app.domains.wallet import mint_stage

    monkeypatch.setattr(mint_stage, "should_use_mint", lambda _owner: True)
    monkeypatch.setattr(mint_client_mod, "mint_client_from_config", lambda: mint)

    with sessions() as session:
        user = User(email="journey@example.com", api_key_hash="h")
        session.add(user)
        session.flush()
        user_id = str(user.id)

        provider_metadata: dict[str, object] = {}

        def create_provider_session(intent):
            provider_metadata.update(intent.meta)
            return {
                "checkout_url": "https://checkout.example/mint-journey",
                "session_id": "checkout_mint_journey",
            }

        checkout = WalletService(session).create_checkout(
            user_id,
            amount_usd="20.00",
            provider="creem",
            idempotency_key="journey-checkout",
            session_factory=create_provider_session,
        )
        session.commit()

        mint_account_id = str(provider_metadata["mint_account_id"])
        assert checkout["settlement_rail"] == "mint"
        assert fake.accounts[mint_account_id]["available"] == 0

        event = {
            "eventType": "checkout.completed",
            "object": {
                "id": "checkout_mint_journey",
                "metadata": {
                    "payment_intent_id": checkout["payment_intent_id"],
                    "account_id": mint_account_id,
                    "mint_account_id": mint_account_id,
                },
            },
        }
        process_creem_wallet_webhook(
            session,
            b"{}",
            "valid-signature",
            verify_fn=lambda _payload, _signature: event,
            mint_client=mint,
        )
        session.commit()
        assert fake.accounts[mint_account_id]["available"] == 20_000_000

        marker = reserve_for_job(
            session,
            user_id=user_id,
            intent=WalletIntent(
                profile="production",
                quote={"quote_id": "quote_journey"},
                max_cost_micros=10_000_000,
            ),
            job_id="render_journey",
            request_id="request_journey",
        )
        assert fake.accounts[mint_account_id]["available"] == 10_000_000
        assert fake.accounts[mint_account_id]["held"] == 10_000_000

        assert settle_job_actual(
            session,
            user_id=user_id,
            job_id="render_journey",
            params=marker,
            actual_micros=7_000_000,
        )
        session.commit()

        # The user pays exactly measured render cost, unused reservation returns,
        # and Menivor's old local wallet never receives a competing cash credit.
        assert fake.accounts[mint_account_id]["available"] == 13_000_000
        assert fake.accounts[mint_account_id]["held"] == 0
        assert fake.accounts[fake.treasury_id]["available"] == 7_000_000
        wallet = WalletService(session)
        assert wallet.balance_view(user_id)["available_micros"] == 13_000_000
        assert wallet._repo.get_personal_account(user_id).available_micros == 0
