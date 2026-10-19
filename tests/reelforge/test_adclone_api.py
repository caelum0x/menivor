"""Ad Clone HTTP routes: gate, auth, brief, plan (priced per engine), render dry run, IP guard,
voice design and Midjourney tagging. No network, no spend."""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.adclone import elevenlabs, router as adclone_router, service
from app.domains.adclone.schemas import CloneBrief
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

KEY = "ad-clone-key"
H = {"x-api-key": KEY}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adclone" / "brief-tiktok-price-shock.json"
ENGINE_KEYS = ("KLING_ACCESS_KEY", "KLING_SECRET_KEY", "KLING_API_KEY", "HIGGSFIELD_API_KEY", "HIGGSFIELD_API_SECRET",
               "REPLICATE_API_TOKEN", "RUNPOD_API_KEY", "RUNPOD_WAN_ENDPOINT_ID", "MINIMAX_API_KEY",
               "ELEVENLABS_API_KEY", "ADCLONE_PAID_RENDER")


@pytest.fixture()
def api(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    monkeypatch.setattr(adclone_router, "get_session", _session)
    monkeypatch.setenv(service.ENABLED_ENV, "1")
    monkeypatch.setenv(service.LLM_ENV, "0")
    monkeypatch.setenv("ADCLONE_MJ_LIBRARY", str(tmp_path / "lib"))
    for name in ENGINE_KEYS:
        monkeypatch.delenv(name, raising=False)
    with factory() as s:
        s.add(User(email="ac@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    app = FastAPI()
    app.include_router(adclone_router.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


@pytest.fixture()
def brief() -> dict:
    return json.loads(FIXTURE.read_text())


def test_feature_is_off_by_default(api, monkeypatch):
    monkeypatch.delenv(service.ENABLED_ENV)
    assert api.get("/api/v1/ad-clone/products", headers=H).status_code == 403


def test_requires_sign_in(api):
    assert api.get("/api/v1/ad-clone/products").status_code in (401, 403)


def test_products(api):
    r = api.get("/api/v1/ad-clone/products", headers=H)
    assert r.status_code == 200
    product = r.json()["data"]["products"][0]
    assert product["id"] == "oxhan" and product["product"] == "Very Turkish Time Shirt, Drop 01"
    assert {c["key"] for c in product["characters"]} == {"H", "O", "N"}


def test_brief_route_uses_the_ingest_pipeline(api, monkeypatch, brief):
    seen = {}

    def fake(url, llm=None, **kw):
        seen["url"], seen["llm"] = url, llm
        return CloneBrief.model_validate(brief)

    monkeypatch.setattr(service, "analyze_link", fake)
    r = api.post("/api/v1/ad-clone/brief", headers=H, json={"url": "https://vt.tiktok.com/ZSbXtdskk/"})
    assert r.status_code == 200
    assert r.json()["data"]["brief"]["hook"]["pattern"] == "price_shock"
    assert seen == {"url": "https://vt.tiktok.com/ZSbXtdskk/", "llm": None}


def test_brief_route_maps_link_errors(api):
    r = api.post("/api/v1/ad-clone/brief", headers=H, json={"url": "https://example.com/video.mp4"})
    assert r.status_code == 422


def test_plan_route_returns_priced_variations(api, brief):
    r = api.post("/api/v1/ad-clone/plan", headers=H,
                 json={"brief": brief, "variations": 2, "aspect": "16:9", "language": "original"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["variations"]) == 2 and data["voice"]["engine"] == "kokoro"
    v = data["variations"][0]
    assert v["plan"]["aspect"] == "16:9" and v["engine"]["dry_run_only"]
    assert {e["engine"] for e in v["estimates"]} >= {"kling", "replicate", "runpod_wan"}
    assert v["midjourney"][0]["save_as"] == "s0.png"


def test_plan_route_validates_input(api, brief):
    bad = copy.deepcopy(brief)
    bad["beats"] = []
    assert api.post("/api/v1/ad-clone/plan", headers=H, json={"brief": bad}).status_code == 422
    assert api.post("/api/v1/ad-clone/plan", headers=H, json={"brief": brief, "variations": 5}).status_code == 422
    assert api.post("/api/v1/ad-clone/plan", headers=H, json={"brief": brief, "product": "nike"}).status_code == 400


def test_kling_becomes_default_with_keys(api, brief, monkeypatch):
    monkeypatch.setenv("KLING_ACCESS_KEY", "ak")
    monkeypatch.setenv("KLING_SECRET_KEY", "sk")
    r = api.post("/api/v1/ad-clone/plan", headers=H, json={"brief": brief})
    assert r.json()["data"]["variations"][0]["engine"]["engine"] == "kling"


def _plan(api, brief):
    return api.post("/api/v1/ad-clone/plan", headers=H, json={"brief": brief}).json()["data"]["variations"][0]["plan"]


def test_render_is_a_dry_run(api, brief):
    plan = _plan(api, brief)
    r = api.post("/api/v1/ad-clone/render", headers=H, json={"plan": plan, "engine": "kling"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["dry_run"] and len(data["requests"]) == len(plan["shots"])
    assert data["requests"][0]["i2v"]["model_name"] == "kling-v3"


def test_paid_render_stays_off(api, brief, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "t")
    plan = _plan(api, brief)
    r = api.post("/api/v1/ad-clone/render", headers=H, json={"plan": plan, "dry_run": False})
    assert r.status_code == 403


def test_render_rechecks_edited_plans_with_the_ip_guard(api, brief):
    plan = _plan(api, brief)
    plan["stills"][1]["prompt"] += " white hair, red coat and goggles"
    r = api.post("/api/v1/ad-clone/render", headers=H, json={"plan": plan})
    assert r.status_code == 422
    assert r.json()["data"]["code"] == "ip_guard" and len(r.json()["data"]["problems"]) >= 3
    plan = _plan(api, brief)
    plan["shots"][0]["refs"].append("video-src/source.mp4")
    assert api.post("/api/v1/ad-clone/render", headers=H, json={"plan": plan}).status_code == 422


def test_voice_design_needs_a_key_and_rejects_imitation(api, monkeypatch):
    r = api.post("/api/v1/ad-clone/voices/design", headers=H, json={"character": "H"})
    assert r.status_code == 503
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    r = api.post("/api/v1/ad-clone/voices/design", headers=H,
                 json={"character": "H", "description": "clone the voice of my favourite actor"})
    assert r.status_code == 422
    fake_http = lambda *a: (200, json.dumps({"previews": [{"generated_voice_id": "g1", "audio_base_64": "AA"}]}).encode())  # noqa: E731
    monkeypatch.setattr(elevenlabs.ElevenLabs, "from_env",
                        classmethod(lambda cls, env=None: cls(api_key="el", http=fake_http)))
    r = api.post("/api/v1/ad-clone/voices/design", headers=H, json={"character": "O"})
    assert r.status_code == 200 and r.json()["data"]["previews"][0]["generated_voice_id"] == "g1"


def test_mj_tag_and_scan(api, tmp_path, monkeypatch):
    r = api.post("/api/v1/ad-clone/characters/tag", headers=H, json={"key": "uploads/u/hero.png", "tag": "hero"})
    assert r.status_code == 200 and r.json()["data"]["total"] == 1
    assert api.post("/api/v1/ad-clone/characters/tag", headers=H,
                    json={"key": "uploads/u/x.png", "tag": "dante"}).status_code == 400
    inbox = tmp_path / "inbox"
    (inbox / "oxhan").mkdir(parents=True)
    (inbox / "oxhan" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    monkeypatch.setenv("ADCLONE_MJ_INBOX", str(inbox))
    r = api.post("/api/v1/ad-clone/characters/scan", headers=H)
    assert r.status_code == 200 and r.json()["data"]["imported"][0]["tag"] == "oxhan"
