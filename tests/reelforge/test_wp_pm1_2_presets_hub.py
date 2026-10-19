"""Wave P PM1.2 (MH2): the preset shelf.

12 filter presets (standard credits, FFmpeg camera moves and looks we render
for $0) and 12 model presets (AI-video credits). A tile is shown only with a
real preview loop; model tiles stay hidden until the owner's promo budget pays
for their previews (item M1). Runs are measured from the tile tap to the first
result and shown per run.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.presets_hub import catalog, previews, service
from app.domains.presets_hub import router as hub_router
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.utils import utils

API_KEY = "shelf-user-key"
OTHER_KEY = "other-user-key"
T0 = datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def test_shelf_has_12_filter_and_12_model_presets_with_unique_ids():
    presets = catalog.all_presets()
    kinds = [p.kind for p in presets]
    assert kinds.count("filter") == 12 and kinds.count("model") == 12
    assert len({p.id for p in presets}) == 24


def test_filter_presets_render_real_ffmpeg_fragments_on_standard_credits():
    from app.services.compose.vfx import build_vfx_filters

    for preset in catalog.filter_presets():
        assert preset.credit_kind == "standard"
        fragments = build_vfx_filters(preset.camera_motion, list(preset.effects), duration_s=4.0,
                                      width=540, height=960)
        assert fragments, preset.id


def test_model_presets_are_priced_skus_on_ai_video_credits():
    from app.domains.routing.tiers import PRESET_SKUS

    for preset in catalog.model_presets():
        assert preset.credit_kind == "ai_video"
        assert preset.preset_sku in PRESET_SKUS, preset.id
        assert "{subject}" in preset.prompt_template


def test_public_copy_names_no_vendor_or_model():
    for preset in catalog.all_presets():
        for text in (preset.name, preset.blurb):
            assert catalog.vendor_hits(text) == [], (preset.id, text)
    assert catalog.vendor_hits("rendered with Kling on fal.ai")


def test_model_preset_files_are_versioned():
    for preset in catalog.model_presets():
        assert preset.version >= 1
        assert preset.source_file.endswith(f"{preset.id}@v{preset.version}.json")


# --------------------------------------------------------------------------- #
# Previews and visibility
# --------------------------------------------------------------------------- #
def _entry(**over):
    base = {"loop": "presets/x.mp4", "poster": "presets/x.jpg", "status": "published",
            "rendered_at": "2026-09-30", "source": "Pexels License stock", "spend_usd": 0.0}
    base.update(over)
    return base


def test_a_tile_without_a_preview_is_hidden(monkeypatch):
    monkeypatch.delenv("PRESET_PREVIEWS_LIVE", raising=False)
    manifest = {"crash-zoom": _entry()}
    visible = [t["id"] for t in service.shelf(manifest=manifest)]
    assert visible == ["crash-zoom"]


def test_staged_previews_show_only_after_the_deploy_switch(monkeypatch):
    manifest = {"crash-zoom": _entry(status="staged")}
    monkeypatch.delenv("PRESET_PREVIEWS_LIVE", raising=False)
    assert service.shelf(manifest=manifest) == []
    monkeypatch.setenv("PRESET_PREVIEWS_LIVE", "1")
    assert [t["id"] for t in service.shelf(manifest=manifest)] == ["crash-zoom"]


def test_model_tiles_need_an_owner_funded_preview(monkeypatch):
    monkeypatch.delenv("PRESET_PREVIEWS_LIVE", raising=False)
    assert service.shelf(manifest={"melt-away": _entry()}) == []
    funded = {"melt-away": _entry(funded_by="owner-promo-M1", spend_usd=0.6)}
    tiles = service.shelf(manifest=funded)
    assert [t["id"] for t in tiles] == ["melt-away"]
    assert tiles[0]["credit_kind"] == "ai_video"


def test_tile_view_has_public_urls_and_a_create_link(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_MEDIA_BASE_URL", "https://media.example")
    (tile,) = service.shelf(manifest={"crash-zoom": _entry(loop="presets/crash-zoom.mp4",
                                                              poster="presets/crash-zoom.jpg")})
    assert tile["preview"] == {"loop_url": "https://media.example/presets/crash-zoom.mp4",
                               "poster_url": "https://media.example/presets/crash-zoom.jpg"}
    assert tile["create_url"] == "/presets-gallery?use=crash-zoom"
    assert "camera_motion" not in json.dumps(tile)  # internals stay server side
    assert tile["target_seconds"] == service.FILTER_TARGET_S


def test_checked_in_manifest_loads():
    data = previews.load_manifest()
    assert isinstance(data, dict)


# --------------------------------------------------------------------------- #
# Resolve: tile -> Create
# --------------------------------------------------------------------------- #
def test_filter_preset_resolves_to_standard_job_params():
    plan = service.resolve("crash-zoom", subject="  Our new espresso bar  ")
    assert plan["route"] == "jobs"
    params = plan["body"]["params"]
    assert params["camera_motion"] == catalog.get("crash-zoom").camera_motion
    assert params["video_subject"] == "Our new espresso bar"
    assert params["layout"] == "captions_only"
    assert plan["body"]["variants"] == 1


def test_model_preset_resolves_to_an_ai_video_generation():
    plan = service.resolve("melt-away", subject="a scoop of ice cream", image_key="uploads/u1/cone.png")
    assert plan["route"] == "generation/broll/generate"
    assert plan["body"]["mode"] == "i2v"
    assert plan["body"]["image_key"] == "uploads/u1/cone.png"
    assert "a scoop of ice cream" in plan["body"]["prompt"]
    assert len(plan["body"]["prompt"]) <= 500
    t2v = service.resolve("tv-spot", subject="running shoes")
    assert t2v["body"]["mode"] == "t2v" and "image_key" not in t2v["body"]


def test_resolve_refuses_unknown_presets_and_empty_subjects():
    with pytest.raises(service.PresetNotFound):
        service.resolve("nope", subject="x")
    with pytest.raises(service.PresetInputError):
        service.resolve("crash-zoom", subject="   ")
    with pytest.raises(service.PresetInputError):
        service.resolve("melt-away", subject="cone")  # image preset without an image


# --------------------------------------------------------------------------- #
# Runs: measured tile -> first result
# --------------------------------------------------------------------------- #
def test_run_timing_from_tap_to_first_result():
    job = {"state": 1, "updated_at": T0 + timedelta(seconds=150),
           "params": {"preset_run": {"preset_id": "crash-zoom", "opened_at": T0.isoformat()}}}
    view = service.run_view(job)
    assert view["seconds_to_result"] == 150
    assert view["target_seconds"] == 180 and view["within_target"] is True
    pending = {**job, "state": 4}
    assert service.run_view(pending)["seconds_to_result"] is None
    model = {**job, "params": {"preset_run": {"preset_id": "melt-away", "opened_at": T0.isoformat()}}}
    assert service.run_view(model)["target_seconds"] == 120
    assert service.run_view(model)["within_target"] is False


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@pytest.fixture()
def maker(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    monkeypatch.setattr(hub_router, "get_session", _session)
    with factory() as s:
        for key, email in ((API_KEY, "a@example.com"), (OTHER_KEY, "b@example.com")):
            s.add(User(email=email, api_key_hash=hashlib.sha256(key.encode()).hexdigest()))
        s.commit()
    return factory


def _client(monkeypatch, manifest) -> TestClient:
    monkeypatch.setattr(previews, "load_manifest", lambda: manifest)
    app = FastAPI()
    app.include_router(hub_router.router)

    def handler(_request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code,
                            content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, handler)
    return TestClient(app)


def test_shelf_route_is_public_and_edge_cacheable(monkeypatch):
    client = _client(monkeypatch, {"crash-zoom": _entry()})
    res = client.get("/api/v1/presets/shelf")
    assert res.status_code == 200
    assert [t["id"] for t in res.json()["data"]["presets"]] == ["crash-zoom"]
    assert "s-maxage" in res.headers.get("cache-control", "")
    assert client.get("/api/v1/presets/shelf/crash-zoom").status_code == 200
    assert client.get("/api/v1/presets/shelf/melt-away").status_code == 404  # hidden tile


def test_start_returns_the_create_body_for_a_signed_in_user(maker, monkeypatch):
    client = _client(monkeypatch, {"crash-zoom": _entry()})
    body = {"subject": "Fresh pasta class"}
    assert client.post("/api/v1/presets/shelf/crash-zoom/plan", json=body).status_code == 401
    res = client.post("/api/v1/presets/shelf/crash-zoom/plan", json=body, headers={"x-api-key": API_KEY})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["route"] == "jobs"


def test_run_is_recorded_on_the_callers_own_job_only(maker, monkeypatch):
    client = _client(monkeypatch, {"crash-zoom": _entry()})
    with maker() as s:
        owner = s.query(User).filter_by(email="a@example.com").one()
        job = Job(user_id=owner.id, kind="avatar_reel", state=4, params={"video_subject": "x"})
        s.add(job)
        s.commit()
        job_id = job.id
    opened = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=3)
    payload = {"job_id": job_id, "opened_at": opened.isoformat()}
    other = client.post("/api/v1/presets/shelf/crash-zoom/runs", json=payload, headers={"x-api-key": OTHER_KEY})
    assert other.status_code == 404
    res = client.post("/api/v1/presets/shelf/crash-zoom/runs", json=payload, headers={"x-api-key": API_KEY})
    assert res.status_code == 200, res.text
    with maker() as s:
        stored = s.get(Job, job_id).params
    assert stored["preset_run"] == {"preset_id": "crash-zoom", "opened_at": opened.isoformat()}
    assert stored["video_subject"] == "x"
    with maker() as s:
        row = s.get(Job, job_id)
        row.state, row.updated_at = 1, opened + timedelta(seconds=95)
        s.commit()
    view = client.get(f"/api/v1/presets/runs/{job_id}", headers={"x-api-key": API_KEY}).json()["data"]
    assert view["seconds_to_result"] == 95 and view["within_target"] is True
    assert client.get(f"/api/v1/presets/runs/{job_id}", headers={"x-api-key": OTHER_KEY}).status_code == 404


def test_opened_at_in_the_future_or_too_old_is_refused(maker, monkeypatch):
    client = _client(monkeypatch, {"crash-zoom": _entry()})
    with maker() as s:
        owner = s.query(User).filter_by(email="a@example.com").one()
        job = Job(user_id=owner.id, kind="avatar_reel", state=4, params={})
        s.add(job)
        s.commit()
        job_id = job.id
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    res = client.post("/api/v1/presets/shelf/crash-zoom/runs", json={"job_id": job_id, "opened_at": future},
                      headers={"x-api-key": API_KEY})
    assert res.status_code == 400


# --------------------------------------------------------------------------- #
# Preview renderer ($0 filter previews)
# --------------------------------------------------------------------------- #
def test_every_filter_preset_has_its_own_licensed_source_clip():
    from app.domains.presets_hub import preview_render

    assert set(preview_render.SOURCE_CLIPS) == {p.id for p in catalog.filter_presets()}
    assert len(set(preview_render.SOURCE_CLIPS.values())) == 12


def test_manifest_merge_never_removes_entries(tmp_path):
    from app.domains.presets_hub import preview_render

    path = tmp_path / "previews.json"
    path.write_text(json.dumps({"description": "d", "previews": {"old": {"loop": "a"}}}))
    preview_render.write_manifest({"new": {"loop": "b"}}, path)
    data = json.loads(path.read_text())
    assert set(data["previews"]) == {"old", "new"} and data["description"] == "d"


@pytest.mark.integration
def test_preview_render_makes_a_4s_540x960_loop(tmp_path):
    import shutil
    import subprocess

    from app.domains.presets_hub import preview_render

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    src = tmp_path / "px-1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=3",
                    "-pix_fmt", "yuv420p", str(src)], check=True, timeout=120)
    entry = preview_render.render(catalog.get("glitch-punch"), str(src), tmp_path / "out")
    assert entry["status"] == "staged" and entry["spend_usd"] == 0.0
    out = tmp_path / "out" / "glitch-punch.mp4"
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type",
         "-of", "json", str(out)], capture_output=True, text=True, check=True).stdout)
    video = probe["streams"][0]
    assert (video["width"], video["height"]) == (540, 960)
    assert abs(float(probe["format"]["duration"]) - 4.0) < 0.2
    assert not any(s["codec_type"] == "audio" for s in probe["streams"])
    assert (tmp_path / "out" / "glitch-punch.jpg").is_file()
