"""Render poll worker — sweep active jobs to terminal with real wallets (sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.wallet.repository import ENTRY_GRANT, WalletRepository
from app.domains.wallet.service import WalletService
from app.models.db import models, render  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.render_repo import RenderJobRepository
from app.services.render import envelope as env
from app.services.render.backends.runpod import RunPodBackend, register_backend
from app.services.render.poller import poll_active_jobs


class _Resp:
    def __init__(self, body):
        self.status_code = 200
        self._body = body
        self.headers = {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


class RoutingTransport:
    """Returns a per-provider_ref scripted poll result (keyed by URL suffix)."""

    def __init__(self, by_ref):
        self._by_ref = by_ref

    def request(self, method, url, *, headers=None, params=None, json=None):
        ref = url.rstrip("/").split("/")[-1]
        return _Resp(self._by_ref[ref])


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    register_backend(RunPodBackend(endpoint_id="ep", api_key="k"))
    yield s
    s.close()


def _fund(s, user_id, micros=1_000_000):
    s.add(User(id=user_id, email=f"{user_id}@x.com"))
    s.flush()
    repo = WalletRepository(s)
    acct = repo.get_or_create_personal_account(user_id)
    repo.append_entry(acct.id, entry_type=ENTRY_GRANT, reason="topup", available_delta=micros)
    return acct


def _reserve_and_create(s, repo, *, job_id, user_id, ref, held):
    # Mirror the router: reserve the hold, then persist a queued render row.
    WalletService(s).reserve(user_id, amount_micros=held, job_id=job_id)
    e = env.RenderJob(id=job_id, backend="runpod", state=env.IN_PROGRESS, provider_ref=ref)
    repo.create(e, user_id=user_id, held_cost_micros=held)


def test_sweep_completes_and_fails_independently(session):
    s = session
    _fund(s, "u1")
    _fund(s, "u2")
    repo = RenderJobRepository(s)
    _reserve_and_create(s, repo, job_id="j-ok", user_id="u1", ref="ok", held=100_000)
    _reserve_and_create(s, repo, job_id="j-bad", user_id="u2", ref="bad", held=90_000)
    s.flush()

    transport = RoutingTransport({
        "ok": {"status": "COMPLETED", "output": {"video_url": "u"}},
        "bad": {"status": "FAILED", "error": "oom"},
    })
    result = poll_active_jobs(s, transport=transport)

    assert result.scanned == 2 and result.completed == 1 and result.failed == 1
    assert repo.get("j-ok").state == "COMPLETED"
    assert repo.get("j-bad").state == "FAILED"

    # Success-only billing: u1 charged (balance < 1M), u2 fully refunded (== 1M).
    assert WalletService(s).balance_view("u1")["available_micros"] < 1_000_000
    assert WalletService(s).balance_view("u2")["available_micros"] == 1_000_000


def test_sweep_skips_when_no_active_jobs(session):
    result = poll_active_jobs(session)
    assert result.scanned == 0 and result.advanced == 0
