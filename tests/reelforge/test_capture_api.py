"""Capture: HTTP routes + worker lifecycle on in-memory SQLite (no network, no browser)."""

from __future__ import annotations

import os

from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.capture import worker
from app.domains.capture.models import CaptureJob
from app.models.db import models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

capture_router = import_module("app.domains.capture.router")


class FakeR2:
    def __init__(self) -> None:
        self.put: list[str] = []

    def put_file(self, path, key, content_type=""):
        self.put.append(key)

    def presign_result_get(self, key, download_name=None):
        return f"https://cdn.test/{key}"


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Factory.begin() as s:
        s.add(User(id="u1", email="u1@x.com"))
        s.add(User(id="u2", email="u2@x.com"))

    @contextmanager
    def fake_session():
        with Factory.begin() as s:
            yield s

    principal = {"id": "u1"}
    dispatched: list[str] = []
    r2 = FakeR2()
    monkeypatch.setattr(capture_router, "get_session", fake_session)
    monkeypatch.setattr("app.models.db.base.get_session", fake_session)
    monkeypatch.setattr(capture_router, "require_database", lambda _rid: None)
    monkeypatch.setattr(capture_router, "resolve_principal", lambda *_a: SimpleNamespace(id=principal["id"]))
    monkeypatch.setattr(capture_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(capture_router, "dispatch_capture", lambda cid: dispatched.append(cid) or "")
    monkeypatch.setattr("app.domains.capture.views.r2_client", lambda: r2)
    monkeypatch.setattr("app.platform.storage.r2.get_r2_client", lambda: r2)

    app = FastAPI()
    app.include_router(capture_router.router)
    app.add_exception_handler(
        HttpException,
        lambda _r, exc: JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return SimpleNamespace(client=TestClient(app), factory=Factory, principal=principal, dispatched=dispatched, r2=r2)


def _create(env, **body):
    payload = {"url": "https://example.com/", "formats": ["9:16"], **body}
    return env.client.post("/api/v1/capture", json=payload)


def test_detect_classifies_without_fetching(env) -> None:
    res = env.client.post("/api/v1/capture/detect", json={"url": "https://apps.apple.com/us/app/x/id123456789"})
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["kind"] == "app_store" and data["ref"]["app_id"] == "123456789" and data["duration"] is None
    site = env.client.post("/api/v1/capture/detect", json={"url": "https://example.com"}).json()["data"]
    assert site["duration"] == {"min": 10, "default": 20, "max": 45}


def test_create_validates_and_dispatches(env) -> None:
    assert _create(env, url="http://127.0.0.1/admin").status_code == 422
    assert _create(env, formats=["4:5"]).status_code == 422
    assert _create(env, kind="web_game").status_code == 422  # removed kind
    assert _create(env, url="").status_code == 422
    res = _create(env, formats=["9:16", "16:9"], duration_s=15)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["status"] == "queued" and data["source_kind"] == "website"
    assert data["options"] == {"formats": ["9:16", "16:9"], "cursor": True, "duration_s": 15}
    assert env.dispatched == [data["id"]]


def _native(env, **native):
    return env.client.post("/api/v1/capture", json={"kind": "native_game", "formats": ["9:16"],
                                                    "native": {"platform": "ios", **native}})


def test_native_game_capture_is_operator_gated_and_validated(env, monkeypatch) -> None:
    from app.domains.capture import service as capture_service

    assert env.client.get("/api/v1/capture/native").json()["data"]["enabled"] is False
    off = _native(env, app_id="com.caelum.flowblast")
    assert off.status_code == 422 and "not enabled" in off.text

    settings = {"capture_native_game": True, "capture_native_app_ids": ["com.caelum.flowblast"]}
    monkeypatch.setattr(capture_service, "_config_value", lambda key, default: settings.get(key, default))
    status = env.client.get("/api/v1/capture/native").json()["data"]
    assert status["enabled"] is True and status["app_ids"] == ["com.caelum.flowblast"]
    assert status["duration"] == {"min": 10, "default": 30, "max": 60}
    assert _native(env, app_id="com.other.game").status_code == 422
    assert _native(env, app_id="com.caelum.flowblast", device="x; reboot").status_code == 422
    assert env.client.post("/api/v1/capture", json={"kind": "native_game"}).status_code == 422
    res = _native(env, app_id="com.caelum.flowblast", title="FlowBlast", deep_link="flowblast://play?menivor_demo=1")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["source_kind"] == "native_game" and data["source_url"] == "flowblast://play?menivor_demo=1"
    assert data["options"]["native"]["app_id"] == "com.caelum.flowblast" and data["options"]["duration_s"] == 30
    assert data["options"]["cursor"] is False


def test_native_game_capture_runs_end_to_end(env, monkeypatch, tmp_path) -> None:
    from app.domains.capture import native
    from app.domains.capture import service as capture_service
    from app.domains.capture.browser import Recording

    settings = {"capture_native_game": True}
    monkeypatch.setattr(capture_service, "_config_value", lambda key, default: settings.get(key, default))
    calls: list[tuple] = []

    def fake_record(target, duration_s, work_dir, *, capture_id):
        calls.append((target.platform, target.device, target.app_id, duration_s))
        video = os.path.join(work_dir, "native-ios.mp4")
        with open(video, "wb") as fh:
            fh.write(b"\x00" * 64)
        return Recording(video_path=video, lead_in_s=0.0, recorded_s=duration_s, screenshots=[],
                         page_meta={"title": "FlowBlast", "platform": "ios", "capture_mode": "native_ios"})

    def fake_finalize(src, out_path, aspect, *, trim_start, max_seconds):
        with open(out_path, "wb") as fh:
            fh.write(b"\x00" * 64)
        return max_seconds

    monkeypatch.setattr(native, "record_native", fake_record)
    monkeypatch.setattr(worker.encode, "finalize_recording", fake_finalize)
    monkeypatch.setattr("app.domains.adstudio.render.extract_poster", lambda *a, **k: False)
    cid = _native(env, app_id="com.caelum.flowblast", title="FlowBlast").json()["data"]["id"]
    assert worker.run_capture(cid)["ok"] is True
    assert calls == [("ios", "booted", "com.caelum.flowblast", 30.0)]
    detail = env.client.get(f"/api/v1/capture/{cid}").json()["data"]
    assert detail["status"] == "succeeded" and detail["capture_mode"] == "native_ios"
    assert detail["script_draft"]["cta"] == "Play FlowBlast on the App Store."


def test_legacy_web_game_rows_read_but_never_rerun(env) -> None:
    with env.factory.begin() as s:
        row = CaptureJob(user_id=env.principal["id"], source_url="https://g.example.com", source_kind="web_game",
                         status="failed", options={"formats": ["9:16"]}, screenshots=[], meta={}, error="old")
        s.add(row)
        s.flush()
        cid = row.id
    detail = env.client.get(f"/api/v1/capture/{cid}")
    assert detail.status_code == 200 and detail.json()["data"]["source_kind"] == "web_game"
    retry = env.client.post(f"/api/v1/capture/{cid}/retry")
    assert retry.status_code == 409 and "removed" in retry.text


def test_active_limit_and_owner_scoping(env) -> None:
    ids = [_create(env).json()["data"]["id"] for _ in range(3)]
    assert _create(env).status_code == 429
    listing = env.client.get("/api/v1/capture").json()["data"]
    assert listing["total"] == 3 and {c["id"] for c in listing["captures"]} == set(ids)
    env.principal["id"] = "u2"
    assert env.client.get(f"/api/v1/capture/{ids[0]}").status_code == 404
    assert env.client.get("/api/v1/capture").json()["data"]["total"] == 0


def test_cancel_retry_delete_lifecycle(env) -> None:
    cid = _create(env).json()["data"]["id"]
    assert env.client.post(f"/api/v1/capture/{cid}/retry").status_code == 409
    assert env.client.post(f"/api/v1/capture/{cid}/cancel").status_code == 200
    assert env.client.post(f"/api/v1/capture/{cid}/cancel").status_code == 409
    assert env.client.post(f"/api/v1/capture/{cid}/retry").status_code == 200
    assert env.dispatched.count(cid) == 2
    assert env.client.delete(f"/api/v1/capture/{cid}").status_code == 200
    assert env.client.get(f"/api/v1/capture/{cid}").status_code == 404


LISTING = {
    "store": "app_store", "url": "https://apps.apple.com/us/app/orbit/id123456789", "title": "Orbit Arcade",
    "developer": "Ereboslab", "description": "Dodge planets in orbit. Chain combos for points.",
    "icon_url": "https://is1.mzstatic.com/icon.png", "screenshots": ["https://is1.mzstatic.com/s1.png"],
    "rating": 4.6, "rating_count": 50, "price_label": "Free", "genre": "Games",
}


def _fake_store(monkeypatch, tmp_path):
    from app.domains.capture import store

    def download(url, dest, **_k):
        from PIL import Image

        Image.new("RGB", (300, 600), (20, 40, 60)).save(dest, "JPEG")
        return dest

    def render(images, segments, aspect, out_path, work_dir, **_k):
        assert len(images) == 2 and segments
        with open(out_path, "wb") as fh:
            fh.write(b"\x00" * 64)
        return 18.5

    monkeypatch.setattr(store, "fetch_app_store", lambda ref: dict(LISTING))
    monkeypatch.setattr(store, "download_image", download)
    monkeypatch.setattr("app.domains.adstudio.render.render_ad", render)
    monkeypatch.setattr("app.domains.adstudio.render.extract_poster", lambda *a, **k: False)


def test_store_capture_runs_end_to_end_and_builds_ads(env, monkeypatch, tmp_path) -> None:
    _fake_store(monkeypatch, tmp_path)
    cid = _create(env, url="https://apps.apple.com/us/app/orbit/id123456789", formats=["9:16", "16:9"]).json()["data"]["id"]
    ads_early = env.client.post(f"/api/v1/capture/{cid}/ads", json={"script": "Hi."})
    assert ads_early.status_code == 409

    result = worker.run_capture(cid)
    assert result == {"ok": True, "capture_id": cid, "outputs": 2}
    assert worker.run_capture(cid)["ok"] is False  # not queued anymore

    detail = env.client.get(f"/api/v1/capture/{cid}").json()["data"]
    assert detail["status"] == "succeeded" and detail["progress"] == 100
    assert [o["aspect"] for o in detail["outputs"]] == ["9:16", "16:9"]
    assert detail["outputs"][0]["video_url"].startswith("https://cdn.test/uploads/")
    assert detail["listing"]["title"] == "Orbit Arcade"
    assert {s["label"] for s in detail["screenshots"]} == {"icon", "store screenshot"}
    assert detail["script_draft"]["cta"] == "Get Orbit Arcade on the App Store."
    assert all(k.startswith("uploads/") for k in env.r2.put)

    res = env.client.post(
        f"/api/v1/capture/{cid}/ads",
        json={"mode": "captions", "aspects": ["16:9"], "script": detail["script_draft"]["script"]},
    )
    assert res.status_code == 200, res.text
    reqs = res.json()["data"]["requests"]
    assert len(reqs) == 1 and reqs[0]["aspect"] == "16:9"
    params = reqs[0]["job_request"]["params"]
    assert params["screen_recording_key"] == detail["outputs"][1]["key"]
    assert params["layout"] == "captions_only" and params["aspect"] == "16:9"

    avatar = env.client.post(f"/api/v1/capture/{cid}/ads", json={"mode": "avatar", "script": "Hi."})
    assert avatar.status_code == 422


def test_store_capture_failure_is_recorded(env, monkeypatch) -> None:
    from app.domains.capture import store

    def boom(ref):
        raise store.StoreError(404, "the App Store has no app with that id in this country")

    monkeypatch.setattr(store, "fetch_app_store", boom)
    cid = _create(env, url="https://apps.apple.com/us/app/orbit/id123456789").json()["data"]["id"]
    assert worker.run_capture(cid)["ok"] is False
    with env.factory.begin() as s:
        job = s.get(CaptureJob, cid)
        assert job.status == "failed" and "no app with that id" in job.error


def test_browser_capture_without_playwright_fails_cleanly(env, monkeypatch) -> None:
    from app.domains.capture import browser

    def missing(*_a, **_k):
        raise browser.CaptureBrowserError(browser.INSTALL_HINT)

    monkeypatch.setattr("app.domains.capture.website.record_website", missing)
    cid = _create(env).json()["data"]["id"]
    worker.run_capture(cid)
    detail = env.client.get(f"/api/v1/capture/{cid}").json()["data"]
    assert detail["status"] == "failed" and "playwright" in detail["error"]


def test_canceled_capture_is_not_overwritten(env, monkeypatch, tmp_path) -> None:
    _fake_store(monkeypatch, tmp_path)
    cid = _create(env, url="https://apps.apple.com/us/app/orbit/id123456789").json()["data"]["id"]
    from app.domains.capture import store

    def cancel_midway(ref):
        with env.factory.begin() as s:
            s.get(CaptureJob, cid).status = "canceled"
        return dict(LISTING)

    monkeypatch.setattr(store, "fetch_app_store", cancel_midway)
    assert worker.run_capture(cid)["ok"] is False
    with env.factory.begin() as s:
        assert s.get(CaptureJob, cid).status == "canceled"
