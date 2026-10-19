"""Camera-motion + VFX preset catalog — pure validation + endpoints."""

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

from app.domains.catalog import presets
from app.models.db.base import Base
from app.models.exception import HttpException
from app.utils import utils

catalog_mod = importlib.import_module("app.domains.catalog.router")


# --------------------------------------------------------------------------- #
# Pure validation
# --------------------------------------------------------------------------- #
def test_catalog_has_expected_presets():
    cam_ids = {m["id"] for m in presets.CAMERA_MOTIONS}
    assert {"dolly_in", "crash_zoom_in", "bullet_time", "fpv_drone", "none"} <= cam_ids
    vfx_ids = {v["id"] for v in presets.VFX_PRESETS}
    assert {"explosion", "disintegration", "datamosh"} <= vfx_ids


def test_validate_camera_motion():
    assert presets.validate_camera_motion(None) == "none"
    assert presets.validate_camera_motion("dolly_in") == "dolly_in"
    with pytest.raises(presets.PresetError):
        presets.validate_camera_motion("teleport")


def test_validate_effects_stack_dedup_and_cap():
    assert presets.validate_effects_stack(None) == []
    # Order-preserving dedup.
    assert presets.validate_effects_stack(["glitch", "glitch", "rain"]) == ["glitch", "rain"]
    with pytest.raises(presets.PresetError):
        presets.validate_effects_stack(["not_a_vfx"])
    with pytest.raises(presets.PresetError):
        presets.validate_effects_stack(
            ["explosion", "smoke", "rain", "snow", "glitch"]  # 5 > max 4
        )


# --------------------------------------------------------------------------- #
# Endpoints (static; no DB needed but router is import-safe)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
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

    monkeypatch.setattr(catalog_mod, "get_session", _gs)
    monkeypatch.setattr(catalog_mod, "_DB_IMPORT_ERROR", None)
    app = FastAPI()
    app.include_router(catalog_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app)


def test_motion_presets_endpoint(client):
    resp = client.get("/api/v1/catalog/motion-presets")
    assert resp.status_code == 200, resp.text
    ids = {m["id"] for m in resp.json()["data"]["camera_motions"]}
    assert "crash_zoom_in" in ids


def test_vfx_presets_endpoint(client):
    resp = client.get("/api/v1/catalog/vfx-presets")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["max_stack"] == presets.MAX_EFFECTS_STACK
    assert any(v["id"] == "explosion" for v in data["vfx"])
