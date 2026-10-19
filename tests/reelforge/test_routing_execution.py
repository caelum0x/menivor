"""Routing execution engine (M1) + actual-cost settlement (M2/M3) tests."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.catalog.seed_data import seed_default_catalog
from app.domains.reels import wallet_bridge as bridge
from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_RUNNING,
    NormalizedUsage,
    ProviderError,
    ProviderRegistry,
    ProviderRun,
    QuoteResult,
)
from app.domains.routing.policy import FALLBACK_EQUIVALENT, RoutePolicy
from app.domains.routing.runtime import execute_and_record
from app.domains.routing.service import RoutingError, RoutingService
from app.domains.wallet.service import WalletService
from app.models.db.base import Base
from app.models.db.marketplace import PaymentIntent, UsageRecord
from app.models.db.models import Job, User


class ProgAdapter:
    """A programmable adapter: sync/async, controllable failures + usage."""

    def __init__(
        self,
        key: str,
        *,
        submit_error: Exception | None = None,
        poll_to_complete: int = 0,
        usage: NormalizedUsage | None = None,
        end_state: str = RUN_COMPLETED,
    ) -> None:
        self._key = key
        self._submit_error = submit_error
        self._poll_to_complete = poll_to_complete
        self._usage = usage or NormalizedUsage(unit="seconds", quantity_units=3, cost_micros=0)
        self._end_state = end_state
        self._polls = 0

    @property
    def provider_key(self) -> str:
        return self._key

    def catalog(self):
        return []

    def quote(self, request, price_version):
        return QuoteResult(max_cost_micros=0, expires_at=None)

    def submit(self, request, snapshot, correlation_id):
        if self._submit_error is not None:
            raise self._submit_error
        if self._poll_to_complete <= 0:
            return ProviderRun(
                provider_key=self._key,
                run_id="r",
                state=self._end_state,
                usage=self._usage if self._end_state == RUN_COMPLETED else None,
            )
        return ProviderRun(provider_key=self._key, run_id="r")

    def poll(self, run):
        self._polls += 1
        if self._polls >= self._poll_to_complete:
            return ProviderRun(
                provider_key=self._key,
                run_id=run.run_id,
                state=self._end_state,
                usage=self._usage if self._end_state == RUN_COMPLETED else None,
            )
        return ProviderRun(provider_key=self._key, run_id=run.run_id, state=RUN_RUNNING)

    def cancel(self, run):
        return True

    def normalize_usage(self, payload):
        return self._usage


@pytest.fixture()
def factory():
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


@pytest.fixture()
def seeded(factory):
    """Seed the curated catalog with two broll models promoted live."""
    with factory() as s:
        seed_default_catalog(s, live_models={"pixelle/wan-i2v", "kling/v1"})
        s.commit()


def _registry(*adapters) -> ProviderRegistry:
    reg = ProviderRegistry()
    for a in adapters:
        reg.register(a)
    return reg


def _route(session, reg, *, fallback=False, quantity=None):
    policy = RoutePolicy(fallback=FALLBACK_EQUIVALENT) if fallback else RoutePolicy()
    return RoutingService(session, provider_registry=reg).resolve_route(
        capability="broll",
        model_id="pixelle/wan-i2v",
        policy=policy,
        estimated_quantity=quantity,
    )


# --------------------------------------------------------------------------- #
# M1 — execute engine
# --------------------------------------------------------------------------- #
def test_execute_sync_success_prices_and_records(factory, seeded):
    with factory() as s:
        reg = _registry(ProgAdapter("pixelle", poll_to_complete=0))
        route = _route(s, reg)
        result = RoutingService(s, provider_registry=reg).execute(
            route, {"prompt": "x"}, job_id=None, stage="broll", correlation_id="c"
        )
        s.commit()
        # 40_000 micros/sec * 3 seconds of usage = 120_000
        assert result.cost_micros == 120_000
        assert result.provider_key == "pixelle"
        assert result.usage_record_id
        rec = s.get(UsageRecord, result.usage_record_id)
        assert rec.cost_micros == 120_000
        assert rec.quantity_units == 3


def test_execute_async_polls_to_completion(factory, seeded):
    with factory() as s:
        reg = _registry(ProgAdapter("pixelle", poll_to_complete=3))
        route = _route(s, reg)
        result = RoutingService(s, provider_registry=reg).execute(
            route, {}, sleep_fn=lambda _s: None
        )
        assert result.run.state == RUN_COMPLETED
        assert result.cost_micros == 120_000


def test_execute_falls_back_on_retryable(factory, seeded):
    with factory() as s:
        primary = ProgAdapter(
            "pixelle", submit_error=ProviderError("boom", retryable=True)
        )
        fallback = ProgAdapter("kling", poll_to_complete=0)
        reg = _registry(primary, fallback)
        route = _route(s, reg, fallback=True)
        result = RoutingService(s, provider_registry=reg).execute(route, {})
        assert result.provider_key == "kling"


def test_execute_hard_error_no_fallback(factory, seeded):
    with factory() as s:
        primary = ProgAdapter(
            "pixelle", submit_error=ProviderError("bad", retryable=False)
        )
        fallback = ProgAdapter("kling", poll_to_complete=0)
        reg = _registry(primary, fallback)
        route = _route(s, reg, fallback=True)
        with pytest.raises(RoutingError) as ei:
            RoutingService(s, provider_registry=reg).execute(route, {})
        assert ei.value.status_code == 502


def test_execute_all_failed_state_raises(factory, seeded):
    with factory() as s:
        reg = _registry(ProgAdapter("pixelle", poll_to_complete=0, end_state=RUN_FAILED))
        route = _route(s, reg)
        with pytest.raises(RoutingError):
            RoutingService(s, provider_registry=reg).execute(route, {})


# --------------------------------------------------------------------------- #
# M2/M3 — execute_and_record + actual-cost settlement
# --------------------------------------------------------------------------- #
def _grant(factory, uid: str, micros: int) -> None:
    with factory() as s:
        svc = WalletService(s)
        acct = svc._repo.get_or_create_personal_account(uid)
        intent = PaymentIntent(
            account_id=acct.id,
            user_id=uid,
            idempotency_key=f"g{micros}",
            credit_micros=micros,
            total_charge_micros=micros,
            status="pending",
        )
        s.add(intent)
        s.flush()
        svc.confirm_intent(intent.id)
        s.commit()


def test_execute_and_record_then_settle_actual(factory, seeded):
    # A user with $1.00, a job that reserved the $0.24 quoted max for a 6s clip.
    with factory() as s:
        u = User(email="a@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    _grant(factory, uid, 1_000_000)

    marker = {"_wallet": {"reserved_micros": 240_000, "correlation_id": "c"}}
    with factory() as s:
        WalletService(s).reserve(uid, amount_micros=240_000, job_id="jobX")
        s.add(Job(id="jobX", user_id=uid, kind="reel", params=marker))
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(uid)
        assert bal["available_micros"] == 760_000
        assert bal["reserved_micros"] == 240_000

    # Run the provider (3s of actual usage -> $0.12) and record the cost.
    with factory() as s:
        reg = _registry(ProgAdapter("pixelle", poll_to_complete=0))
        result = execute_and_record(
            s,
            capability="broll",
            model_id="pixelle/wan-i2v",
            request={"prompt": "waves"},
            job_id="jobX",
            provider_registry=reg,
        )
        s.commit()
        assert result.cost_micros == 120_000

    # Terminal settlement charges the ACTUAL $0.12 and releases the unused $0.12.
    with factory() as s:
        job = s.get(Job, "jobX")
        assert bridge.settle_job(s, user_id=uid, job_id="jobX", params=job.params) is True
        s.commit()
    with factory() as s:
        bal = WalletService(s).balance_view(uid)
        assert bal["reserved_micros"] == 0
        # 760_000 available + 120_000 released back = 880_000 (charged 120_000).
        assert bal["available_micros"] == 880_000


def test_run_generation_job_opens_session_and_records(factory, seeded, monkeypatch):
    """The Celery task entrypoint runs the engine against its own session."""
    from contextlib import contextmanager

    import app.models.db.base as base_mod
    from app.domains.routing.runtime import run_generation_job

    # Seed a wallet job that reserved $0.24.
    with factory() as s:
        u = User(email="b@example.com", api_key_hash="h")
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    _grant(factory, uid, 1_000_000)
    marker = {"_wallet": {"reserved_micros": 240_000, "correlation_id": "c"}}
    with factory() as s:
        WalletService(s).reserve(uid, amount_micros=240_000, job_id="jobG")
        s.add(Job(id="jobG", user_id=uid, kind="reel", params=marker))
        s.commit()

    @contextmanager
    def _gs():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(base_mod, "get_session", _gs)
    reg = _registry(ProgAdapter("pixelle", poll_to_complete=0))
    out = run_generation_job(
        "jobG",
        capability="broll",
        model_id="pixelle/wan-i2v",
        request={"prompt": "x"},
        provider_registry=reg,
    )
    assert out["cost_micros"] == 120_000
    assert out["provider_key"] == "pixelle"
    assert out["usage_record_id"]
    # The actual cost was stamped onto the job marker for terminal settlement.
    with factory() as s:
        job = s.get(Job, "jobG")
        assert job.params["_wallet"]["actual_micros"] == 120_000
