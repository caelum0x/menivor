"""Clipmarket router — create campaign → submit → review over the real stack."""

from __future__ import annotations

import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.db import clipmarket, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

mod = importlib.import_module("app.domains.clipmarket.router")


def _fund_wallet(session, user_id: str, micros: int) -> None:
    """Grant wallet balance so campaign budgets can be escrowed."""
    from app.domains.wallet.repository import ENTRY_GRANT, WalletRepository

    repo = WalletRepository(session)
    account = repo.get_or_create_personal_account(user_id)
    repo.append_entry(account.id, entry_type=ENTRY_GRANT, reason="test_topup",
                      available_delta=micros)
    session.flush()


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _gs():
        s = Factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    with _gs() as s:
        for uid in ("brand", "clipper"):
            s.add(User(id=uid, email=f"{uid}@x.com"))
        s.flush()
        # Campaign budgets are escrowed from the brand's wallet.
        _fund_wallet(s, "brand", 1_000_000_000)

    state = {"uid": "brand"}

    class _User:
        @property
        def id(self):
            return state["uid"]

    monkeypatch.setattr(mod, "get_session", _gs)
    monkeypatch.setattr(mod, "_require_db", lambda rid: None)
    monkeypatch.setattr(mod, "_resolve_user", lambda req, s, rid: _User())

    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app), state


def test_full_marketplace_flow(client):
    tc, state = client
    # Brand creates a campaign.
    state["uid"] = "brand"
    camp = tc.post("/api/v1/clipmarket/campaigns", json={
        "title": "Launch", "cpm_micros": 2_000_000, "budget_micros": 500_000_000,
    })
    assert camp.status_code == 200, camp.text
    cid = camp.json()["data"]["id"]

    # It appears in the active list.
    listing = tc.get("/api/v1/clipmarket/campaigns")
    assert cid in [c["id"] for c in listing.json()["data"]["campaigns"]]

    # Clipper submits.
    state["uid"] = "clipper"
    sub = tc.post(f"/api/v1/clipmarket/campaigns/{cid}/submit", json={"clip_url": "https://x"})
    assert sub.status_code == 200
    sid = sub.json()["data"]["id"]

    # The campaign's brand reviews with clean views → approved + payout.
    state["uid"] = "brand"
    review = tc.post(f"/api/v1/clipmarket/submissions/{sid}/review", json={
        "views": 50_000, "velocity_zscore": 1.0, "avg_watch_frac": 0.55,
        "engagement_rate": 0.05, "geo_concentration": 0.2, "retention_cliff": 0.2,
    })
    assert review.status_code == 200, review.text
    assert review.json()["data"]["status"] == "approved"
    assert review.json()["data"]["payable_micros"] == 100_000_000


def test_submit_unknown_campaign_422(client):
    tc, state = client
    state["uid"] = "clipper"
    resp = tc.post("/api/v1/clipmarket/campaigns/nope/submit", json={"clip_url": "https://x"})
    assert resp.status_code == 422
