"""Characters + gateway HTTP surfaces over the real DB (sqlite)."""

from __future__ import annotations

import importlib
from contextlib import contextmanager

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.db import characters, gateway, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils


def _mount(module_path, monkeypatch):
    mod = importlib.import_module(module_path)
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
        s.add(User(id="u1", email="u@x.com"))

    class _U:
        id = "u1"

    monkeypatch.setattr(mod, "get_session", _gs)
    monkeypatch.setattr(mod, "_require_db", lambda rid: None)
    monkeypatch.setattr(mod, "_resolve_user", lambda req, s, rid: _U())

    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app)


def test_characters_save_dedupe_and_shot_prompt(monkeypatch):
    tc = _mount("app.domains.characters.router", monkeypatch)
    body = {"name": "Nova", "descriptors": ["silver hair"], "style": "3D"}
    a = tc.post("/api/v1/characters", json=body)
    assert a.status_code == 200
    cid = a.json()["data"]["id"]
    # Saving the same identity dedupes.
    b = tc.post("/api/v1/characters", json=body)
    assert b.json()["data"].get("deduped") is True and b.json()["data"]["id"] == cid

    # Shot prompt is identity-locked.
    sp = tc.post(f"/api/v1/characters/{cid}/shot-prompt", json={"action": "runs", "shot_index": 1})
    assert sp.status_code == 200 and sp.json()["data"]["prompt"].startswith("Nova, silver hair")

    lst = tc.get("/api/v1/characters")
    assert len(lst.json()["data"]["characters"]) == 1


def test_gateway_key_mint_list_quote(monkeypatch):
    tc = _mount("app.domains.gateway.router", monkeypatch)
    made = tc.post("/api/v1/gateway/keys", json={
        "label": "acme", "daily_cap_micros": 1_000_000, "markup_bps": 2000,
    })
    assert made.status_code == 200
    data = made.json()["data"]
    assert data["secret"].startswith("rf_pk_")  # shown once
    kid = data["id"]

    # List never returns secrets.
    keys = tc.get("/api/v1/gateway/keys").json()["data"]["keys"]
    assert keys and "secret" not in keys[0]

    # Quote applies markup + reports remaining allowance.
    q = tc.post(f"/api/v1/gateway/keys/{kid}/quote", json={"base_cost_micros": 100_000})
    assert q.status_code == 200
    assert q.json()["data"]["customer_price_micros"] == 120_000  # +20%
    assert q.json()["data"]["would_allow"] is True
