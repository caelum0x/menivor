"""Wave P PM2.1 (MH7): upscale and smooth.

1. 4x image upscale on the CPU sidecar, capped per user per day, free inside
   the cap; the seconds per image are recorded (the 1080p target is measured
   on box 1 before launch).
2. Video upscale only on AI-video credits via the SeedVR2 API, priced from the
   catalog row at 3x before it starts; refunded once on failure.
3. RIFE only on the GPU lane: off without the lane, unpriced without a recorded
   GPU price.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import threading
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.services.billing import premium_credits as pc
from app.services.enhance import esrgan_cpu, rife, router as enhance_router, seedvr_api, service, tasks
from app.services.enhance.errors import EnhanceError
from app.utils import utils

REPO = Path(__file__).resolve().parents[2]
KEY = "enhance-key"
H = {"x-api-key": KEY}


def _png(size=(64, 36), colour=(20, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return out.getvalue()


def _resize_backend(data: bytes, scale: int) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        out = io.BytesIO()
        im.resize((im.width * scale, im.height * scale)).save(out, format="PNG")
        return out.getvalue()


# --------------------------------------------------------------------------- #
# CPU image upscale client and sidecar
# --------------------------------------------------------------------------- #
def test_client_checks_the_output_is_exactly_four_times_larger():
    image = _png()
    good = esrgan_cpu.upscale(image, url="http://esrgan", post=lambda u, b, h, t: (200, _resize_backend(b, 4)))
    assert (good.width, good.height) == (256, 144) and good.seconds >= 0
    with pytest.raises(EnhanceError) as wrong:
        esrgan_cpu.upscale(image, url="http://esrgan", post=lambda u, b, h, t: (200, _resize_backend(b, 2)))
    assert wrong.value.status_code == 502
    with pytest.raises(EnhanceError) as big:
        esrgan_cpu.upscale(_png((2000, 1000)), url="http://esrgan", post=lambda *a: (200, b""))
    assert big.value.code == "image_too_large"
    with pytest.raises(EnhanceError) as off:
        esrgan_cpu.upscale(image, url="")
    assert off.value.status_code == 503


def _sidecar():
    path = REPO / "deploy" / "esrgan-ncnn" / "server.py"
    spec = importlib.util.spec_from_file_location("menivor_esrgan_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sidecar_serves_upscales_one_at_a_time_and_refuses_bad_input():
    server_mod = _sidecar()
    from http.server import ThreadingHTTPServer

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.make_handler("fake", _resize_backend))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        health = urllib.request.urlopen(f"{base}/healthz", timeout=5).read()
        assert b'"backend": "fake"' in health
        result = esrgan_cpu.upscale(_png(), url=base)
        assert (result.width, result.height) == (256, 144)
        request = urllib.request.Request(f"{base}/v1/upscale?scale=4", data=b"not an image", method="POST")
        with pytest.raises(urllib.error.HTTPError) as bad:
            urllib.request.urlopen(request, timeout=5)
        assert bad.value.code == 400
        big = urllib.request.Request(f"{base}/v1/upscale?scale=4", data=_png((2400, 100)), method="POST")
        with pytest.raises(urllib.error.HTTPError) as too_big:
            urllib.request.urlopen(big, timeout=5)
        assert too_big.value.code == 400
    finally:
        httpd.shutdown()


def test_sidecar_prefers_torch_when_no_ncnn_binary(monkeypatch):
    server_mod = _sidecar()
    monkeypatch.setattr(server_mod, "NCNN_BIN", "")
    assert server_mod.pick_backend("auto")[0] == "torch"
    assert server_mod.pick_backend("ncnn")[0] == "ncnn"


def test_deploy_fragment_is_capped_and_pins_the_weights():
    fragment = (REPO / "deploy" / "esrgan-ncnn" / "compose.fragment.yml").read_text(encoding="utf-8")
    assert "mem_limit: 512m" in fragment and "menivor-esrgan" in fragment
    dockerfile = (REPO / "deploy" / "esrgan-ncnn" / "Dockerfile").read_text(encoding="utf-8")
    assert "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1" in dockerfile
    assert "sha256sum -c" in dockerfile and "BSD-3-Clause" in dockerfile


# --------------------------------------------------------------------------- #
# Video upscale price and client; RIFE lane
# --------------------------------------------------------------------------- #
def test_video_upscale_is_priced_from_the_catalog_at_three_times():
    price = seedvr_api.quote(width=540, height=960, seconds=5, fps=24)
    assert price["output"] == [1080, 1920]
    assert price["megapixels"] == pytest.approx(248.8, abs=0.1)
    assert price["provider_usd"] == pytest.approx(0.2488, abs=0.001)
    assert price["ai_video_credits"] == pc.ai_video_credits_for_usd(price["provider_usd"])
    assert price["price_source"].startswith("https://fal.ai/")
    assert seedvr_api.output_size(1080, 1920) == (2160, 3840)
    with pytest.raises(EnhanceError):
        seedvr_api.quote(width=720, height=1280, seconds=90, fps=30)


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _FakeFal:
    def __init__(self, states):
        self.states, self.calls = list(states), []

    def post(self, url, headers, json, timeout):
        self.calls.append(("POST", url, json))
        return _Resp(200, {"request_id": "r1"})

    def get(self, url, headers, timeout):
        self.calls.append(("GET", url, None))
        if url.endswith("/status"):
            return _Resp(200, {"status": self.states.pop(0)})
        return _Resp(200, {"video": {"url": "https://fal.media/out.mp4"}})


def test_seedvr_client_submits_polls_and_returns_the_video():
    fake = _FakeFal(["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])
    client = seedvr_api.SeedVRClient(api_key="k", session=fake, sleep=lambda s: None)
    handle = client.submit("https://media.example/in.mp4")
    assert client.wait(handle) == "https://fal.media/out.mp4"
    assert fake.calls[0][2] == {"video_url": "https://media.example/in.mp4", "upscale_factor": 2}
    failing = seedvr_api.SeedVRClient(api_key="k", session=_FakeFal(["FAILED"]), sleep=lambda s: None)
    with pytest.raises(EnhanceError):
        failing.wait(failing.submit("https://media.example/in.mp4"))


def test_rife_runs_only_on_a_priced_gpu_lane(monkeypatch):
    for name in (rife.ENDPOINT_ENV, rife.KEY_ENV, rife.PRICE_ENV):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(EnhanceError) as off:
        rife.quote(seconds=10)
    assert off.value.code == "gpu_lane_off"
    monkeypatch.setenv(rife.ENDPOINT_ENV, "ep1")
    monkeypatch.setenv(rife.KEY_ENV, "key")
    with pytest.raises(EnhanceError) as unpriced:
        rife.quote(seconds=10)
    assert unpriced.value.status_code == 402
    monkeypatch.setenv(rife.PRICE_ENV, "0.60")
    price = rife.quote(seconds=30)
    assert price["provider_usd"] == pytest.approx(0.30)

    class FakeRunPod:
        def run(self, worker_input):
            assert worker_input == {"video_url": "https://in", "multi": 2}
            return "job1"

        def wait(self, job_id):
            return {"video_url": "https://out/smooth.mp4"}

    assert rife.interpolate("https://in", client=FakeRunPod()) == "https://out/smooth.mp4"


# --------------------------------------------------------------------------- #
# Jobs, caps, charges and refunds
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
    monkeypatch.setattr(enhance_router, "get_session", _session)
    monkeypatch.setattr(enhance_router, "enqueue_image", lambda job_id: "celery-1")
    monkeypatch.setattr(enhance_router, "enqueue_video", lambda job_id: "celery-2")
    monkeypatch.setattr(service, "_require_owned_key", lambda s, u, k: None)
    monkeypatch.setattr(service, "_media_url", lambda key: f"https://signed.example/{key}" if key else "")
    monkeypatch.setattr(service, "probe_video", lambda url: {"width": 540, "height": 960, "seconds": 5, "fps": 24})
    with factory() as s:
        s.add(User(email="enh@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    return factory


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(enhance_router.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def _uid(maker):
    with maker() as s:
        return s.query(User).one().id


def _render(maker) -> str:
    uid = _uid(maker)
    with maker() as s:
        job = Job(user_id=uid, kind="avatar_reel", state=1, params={}, result_key="jobs/r/final.mp4",
                  poster_key="jobs/r/poster.jpg")
        s.add(job)
        s.commit()
        return job.id


def test_image_upscale_is_free_inside_the_daily_cap(maker, monkeypatch):
    monkeypatch.setenv(esrgan_cpu.CAP_ENV, "2")
    client = _client()
    for _ in range(2):
        assert client.post("/api/v1/enhance/image", json={"image_key": "uploads/u/a.png"}, headers=H).status_code == 200
    capped = client.post("/api/v1/enhance/image", json={"image_key": "uploads/u/a.png"}, headers=H)
    assert capped.status_code == 429 and capped.json()["data"]["code"] == "daily_cap"
    both = client.post("/api/v1/enhance/image", json={"image_key": "k", "source_job_id": "j"}, headers=H)
    assert both.status_code == 400


def test_image_job_runs_on_the_sidecar_and_records_its_time(maker):
    client = _client()
    render_id = _render(maker)
    job_id = client.post("/api/v1/enhance/image", json={"source_job_id": render_id}, headers=H).json()["data"]["job_id"]
    stored = {}
    deps = tasks.Deps(fetch=lambda key: _png(), upload=lambda path, key, ct: stored.update({key: Path(path).read_bytes()}),
                      upscale_image=lambda data: esrgan_cpu.upscale(
                          data, url="http://esrgan", post=lambda u, b, h, t: (200, _resize_backend(b, 4))))
    assert tasks.run_image(job_id, deps)["state"] == 1
    view = client.get(f"/api/v1/enhance/{job_id}", headers=H).json()["data"]
    assert view["output"] == [256, 144] and view["seconds"] is not None
    assert list(stored) == [f"jobs/{job_id}/enhance/upscaled-4x.png"]


def test_video_upscale_is_quoted_then_charged_and_refunded_once_on_failure(maker):
    client = _client()
    render_id = _render(maker)
    quote = client.post("/api/v1/enhance/video/quote", json={"source_job_id": render_id, "op": "upscale"},
                        headers=H).json()["data"]
    credits = quote["ai_video_credits"]
    assert "price_source" not in quote and "provider_usd" not in quote  # no vendor names reach the client
    body = {"source_job_id": render_id, "op": "upscale", "quoted_credits": credits}
    assert client.post("/api/v1/enhance/video", json=body, headers=H).status_code == 402
    assert client.post("/api/v1/enhance/video", json={**body, "quoted_credits": credits + 1},
                       headers=H).status_code == 409
    with maker() as s:
        pc.grant(s, _uid(maker), pc.KIND_AI_VIDEO, credits, "test_grant")
        s.commit()
    job_id = client.post("/api/v1/enhance/video", json=body, headers=H).json()["data"]["job_id"]
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == 0

    def down(url):
        raise EnhanceError(502, "upscale_failed", "the upscaler could not finish this video")

    deps = tasks.Deps(upscale_video=down, media_url=lambda key: f"https://signed.example/{key}")
    assert tasks.run_video(job_id, deps)["state"] == -1
    assert tasks.run_video(job_id, deps)["state"] == -1  # a second pass changes nothing
    with maker() as s:
        assert pc.balance(s, _uid(maker), pc.KIND_AI_VIDEO) == credits
    assert client.get(f"/api/v1/enhance/{job_id}", headers=H).json()["data"]["refunded"] is True


def test_video_upscale_success_stores_the_result(maker):
    client = _client()
    render_id = _render(maker)
    credits = client.post("/api/v1/enhance/video/quote", json={"source_job_id": render_id, "op": "upscale"},
                          headers=H).json()["data"]["ai_video_credits"]
    with maker() as s:
        pc.grant(s, _uid(maker), pc.KIND_AI_VIDEO, credits, "test_grant")
        s.commit()
    job_id = client.post("/api/v1/enhance/video", json={"source_job_id": render_id, "op": "upscale",
                                                         "quoted_credits": credits}, headers=H).json()["data"]["job_id"]
    uploaded = []
    deps = tasks.Deps(upscale_video=lambda url: "https://fal.media/out.mp4",
                      download=lambda url, path: Path(path).write_bytes(b"mp4"),
                      upload=lambda path, key, ct: uploaded.append(key),
                      media_url=lambda key: f"https://signed.example/{key}")
    assert tasks.run_video(job_id, deps)["state"] == 1
    assert uploaded == [f"jobs/{job_id}/enhance/upscale.mp4"]


def test_smooth_motion_is_refused_while_the_gpu_lane_is_off(maker, monkeypatch):
    monkeypatch.delenv(rife.ENDPOINT_ENV, raising=False)
    client = _client()
    res = client.post("/api/v1/enhance/video/quote", json={"source_job_id": _render(maker), "op": "smooth"}, headers=H)
    assert res.status_code == 503 and res.json()["data"]["code"] == "gpu_lane_off"


def test_other_users_renders_are_not_found(maker):
    client = _client()
    with maker() as s:
        other = User(email="other@example.com", api_key_hash="x")
        s.add(other)
        s.flush()
        job = Job(user_id=other.id, kind="avatar_reel", state=1, params={}, result_key="jobs/o/final.mp4")
        s.add(job)
        s.commit()
        jid = job.id
    assert client.post("/api/v1/enhance/video/quote", json={"source_job_id": jid, "op": "upscale"},
                       headers=H).status_code == 404
