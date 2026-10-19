"""Wave P PM2.4 (MV2 upload and transcode lanes, MV3 packaging).

1. A 60-min 1080p upload never runs on box 1 (picker); the Mac node takes jobs
   only with a heartbeat under 60 s and more than 10 GB free; burst only for
   paid plans under the MD6 cap.
2. The CMAF ladder becomes HLS and DASH from one set of segments with aligned
   2 s segments across rungs (real ffmpeg + the pinned shaka-packager when
   present); players are checked structurally (m3u8 and MPD parse).
3. Tier-1 protection for non-free titles (HLS AES-128, key server URI, DASH
   removed); the packager checksum is verified before any job.
4. Each job records node, CPU seconds and cost.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.ott.models import OttChannel, OttTitle
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.services.ott_package import packager, sprites, tracks
from app.services.ott_package.ladder_profiles import rungs_for
from app.services.ott_transcode import keys, ladder, mac_node, nodes, picker, pipeline, service, uploads
from app.services.ott_transcode import router as transcode_router
from app.services.ott_transcode.models import OttEncodeJob, OttNode
from app.utils import utils

REPO = Path(__file__).resolve().parents[2]
PACKAGER = os.getenv("SHAKA_PACKAGER_TEST_BIN", "/tmp/menivor-p2-tools/packager")
HAS_MEDIA = shutil.which("ffmpeg") is not None and os.path.exists(PACKAGER)
KEY = "ott-transcode-key"
H = {"x-api-key": KEY}


# --------------------------------------------------------------------------- #
# Picker
# --------------------------------------------------------------------------- #
def test_long_form_never_runs_on_box1():
    hour = picker.pick(seconds=3600, short_side=1080, paid_plan=True, mac_live=False, burst_live=False,
                       burst_spent_usd=0)
    assert hour.lane == "mac" and "waiting" in hour.reason
    assert picker.pick(seconds=180, short_side=1080, paid_plan=False, mac_live=False, burst_live=False,
                       burst_spent_usd=0).lane == "box1"
    assert picker.pick(seconds=120, short_side=1440, paid_plan=False, mac_live=False, burst_live=False,
                       burst_spent_usd=0).lane != "box1"
    assert picker.pick(seconds=181, short_side=720, paid_plan=False, mac_live=True, burst_live=True,
                       burst_spent_usd=0).lane == "mac"


def test_burst_is_for_paid_plans_under_the_monthly_cap(monkeypatch):
    monkeypatch.setenv("OTT_BURST_MONTHLY_CAP_EUR", "20")
    monkeypatch.setenv("OTT_EUR_USD", "1.0")
    kwargs = dict(seconds=3600, short_side=1080, mac_live=False, burst_live=True)
    assert picker.pick(paid_plan=True, burst_spent_usd=0, **kwargs).lane == "burst"
    assert picker.pick(paid_plan=False, burst_spent_usd=0, **kwargs).lane == "mac"
    assert picker.pick(paid_plan=True, burst_spent_usd=19.99, **kwargs).lane == "mac"


# --------------------------------------------------------------------------- #
# Database fixture
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
    monkeypatch.setattr(transcode_router, "get_session", _session)
    monkeypatch.setattr(service, "paid_plan", lambda user_id: False)
    for name in ("OTT_ENABLED", "OTT_UPLOAD_LIVE", "OTT_PACKAGING_LIVE"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv(keys.SECRET_ENV, "a-test-secret-that-is-long-enough")
    with factory() as s:
        s.add(User(email="ott@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    return factory


def _uid(maker):
    with maker() as s:
        return s.query(User).one().id


def _title(maker, *, tier="free", source_job=True) -> str:
    uid = _uid(maker)
    with maker() as s:
        channel = OttChannel(user_id=uid, handle="ch", title="Ch", brand_colors=[])
        s.add(channel)
        s.flush()
        job_id = None
        if source_job:
            reel = Job(user_id=uid, kind="avatar_reel", state=1, result_key="jobs/r/final.mp4", params={})
            s.add(reel)
            s.flush()
            job_id = reel.id
        title = OttTitle(channel_id=channel.id, title="T", source_job_id=job_id, access_tier=tier, genres=[],
                         geo_countries=[], duration_s=30)
        s.add(title)
        s.commit()
        return title.id


class FakeStore:
    def __init__(self):
        self.created, self.completed, self.puts = [], [], []

    def create(self, key, content_type):
        self.created.append(key)
        return "up-1"

    def part_url(self, key, upload_id, part):
        return f"https://r2/{key}?part={part}"

    def complete(self, key, upload_id, parts):
        self.completed.append((key, parts))

    def abort(self, key, upload_id):
        pass

    def presign_get(self, key, ttl_s):
        return f"https://r2/get/{key}"

    def presign_put(self, key, content_type, ttl_s):
        self.puts.append((key, content_type))
        return f"https://r2/put/{key}"


def _client(monkeypatch, store=None) -> TestClient:
    store = store or FakeStore()
    monkeypatch.setattr(transcode_router, "storage", lambda: transcode_router.SourceStorage(store))
    monkeypatch.setattr(transcode_router, "enqueue_box1", lambda job_id: None)
    monkeypatch.setattr(transcode_router, "enqueue_upload_check", lambda title_id: None)  # Wave Q QM1.2
    app = FastAPI()
    app.include_router(transcode_router.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Nodes and the claim protocol
# --------------------------------------------------------------------------- #
def test_mac_is_live_only_with_a_fresh_heartbeat_and_free_space(maker):
    with maker() as s:
        node, token = nodes.register(s, "owner-mac", "mac")
        assert nodes.authenticate(s, token).id == node.id and nodes.authenticate(s, "ottn_wrong") is None
        now = datetime.now(timezone.utc)
        nodes.heartbeat(s, node, free_gb=11, cores=10, now=now - timedelta(seconds=59))
        assert nodes.is_live(node, now=now)
        assert not nodes.is_live(node, now=now + timedelta(seconds=2))
        nodes.heartbeat(s, node, free_gb=10, cores=10, now=now)
        assert not nodes.is_live(node, now=now)
        assert node.token_hash != token and len(node.token_hash) == 64


def test_node_claims_encodes_uploads_and_records_cpu_and_cost(maker, monkeypatch):
    title_id = _title(maker, tier="paid")
    store = FakeStore()
    client = _client(monkeypatch, store)
    uid = _uid(maker)  # outside the session: StaticPool shares one connection
    with maker() as s:
        node, token = nodes.register(s, "owner-mac", "mac")
        title = s.get(OttTitle, title_id)
        job = service.submit(s, title, source_key="ott:ott-uploads/u/x/film.mp4", seconds=3600, short_side=1080,
                             user_id=uid)
        assert job.lane == "mac"
        s.commit()
    auth = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/ott/nodes/claim", headers=auth).status_code == 409  # no heartbeat yet
    assert client.post("/api/v1/ott/nodes/heartbeat", headers=auth, json={"free_gb": 9, "cores": 8}).json()[
        "data"]["live"] is False
    assert client.post("/api/v1/ott/nodes/claim", headers=auth).status_code == 409
    client.post("/api/v1/ott/nodes/heartbeat", headers=auth, json={"free_gb": 120, "cores": 8})
    claimed = client.post("/api/v1/ott/nodes/claim", headers=auth).json()["data"]["job"]
    assert claimed["source_url"] == "https://r2/get/ott-uploads/u/x/film.mp4"
    assert claimed["encoder"] == "h264_videotoolbox"
    assert claimed["protection"]["key_uri"].endswith(f"/api/v1/ott/keys/{title_id}?kv=1")  # Wave Q QM1.2
    assert client.post("/api/v1/ott/nodes/claim", headers=auth).json()["data"]["job"] is None
    bad = client.post(f"/api/v1/ott/nodes/jobs/{claimed['job_id']}/upload-urls", headers=auth,
                      json={"files": ["../../escape.m4s"]})
    assert bad.status_code == 400
    urls = client.post(f"/api/v1/ott/nodes/jobs/{claimed['job_id']}/upload-urls", headers=auth,
                       json={"files": ["master.m3u8", "v_1080p/1.m4s"]}).json()["data"]["urls"]
    assert set(urls) == {"master.m3u8", "v_1080p/1.m4s"}
    assert store.puts[0][1] == "application/vnd.apple.mpegurl"
    assert client.post(f"/api/v1/ott/nodes/jobs/{claimed['job_id']}/complete", headers=auth,
                       json={"files": ["v_1080p/1.m4s"], "cpu_seconds": 5, "packager_sha256": "a" * 64}
                       ).status_code == 400
    done = client.post(f"/api/v1/ott/nodes/jobs/{claimed['job_id']}/complete", headers=auth,
                       json={"files": ["master.m3u8", "v_1080p/1.m4s"], "cpu_seconds": 812.5,
                             "packager_sha256": "a" * 64}).json()["data"]
    assert done["status"] == "done" and done["cpu_seconds"] == 812.5 and done["cost_usd"] == 0.0
    assert done["node_id"]
    with maker() as s:
        title = s.get(OttTitle, title_id)
        assert title.package_status == "ready" and title.manifest_key.endswith("/master.m3u8")
        assert keys.read_key(s, title_id) is not None


def test_burst_nodes_only_take_paid_jobs_and_cost_is_recorded(maker, monkeypatch):
    title_id = _title(maker)
    with maker() as s:
        burst, _token = nodes.register(s, "burst-1", "burst")
        nodes.heartbeat(s, burst, free_gb=50, cores=16)
        free_job = OttEncodeJob(title_id=title_id, user_id="u", source_key="ott:a", lane="burst", paid_plan=False,
                                output_prefix="ott/c/t/j1")
        s.add(free_job)
        s.commit()
        assert mac_node.claim(s, burst, FakeStore(), api_base="https://api") is None
        paid = OttEncodeJob(title_id=title_id, user_id="u", source_key="ott:b", lane="burst", paid_plan=True,
                            output_prefix="ott/c/t/j2")
        s.add(paid)
        s.commit()
        got = mac_node.claim(s, burst, FakeStore(), api_base="https://api")
        assert got["job_id"] == paid.id and got["encoder"] == "libx264" and got["protection"] is None
        monkeypatch.setenv("OTT_BURST_USD_PER_CPU_HOUR", "0.10")
        finished = service.finish(s, s.get(OttEncodeJob, paid.id), cpu_seconds=7200, packager_sha256="b" * 64,
                                  node_id=burst.id)
        assert finished.cost_usd == pytest.approx(0.2)
        s.commit()
        assert service.burst_spent_this_month(s) == pytest.approx(0.2)


def test_quiet_nodes_lose_their_jobs_back_to_the_queue(maker):
    title_id = _title(maker)
    with maker() as s:
        job = OttEncodeJob(title_id=title_id, user_id="u", source_key="ott:a", lane="mac", status="claimed",
                           node_id="n1", heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                           output_prefix="ott/c/t/j")
        s.add(job)
        s.commit()
        assert service.requeue_stale(s) == 1
        assert job.status == "queued" and job.node_id is None and job.lane == "mac" and job.attempts == 1


def test_three_failures_fail_the_title(maker):
    title_id = _title(maker)
    with maker() as s:
        job = OttEncodeJob(title_id=title_id, user_id="u", source_key="ott:a", lane="box1", output_prefix="p")
        s.add(job)
        s.flush()
        for _ in range(3):
            service.fail(s, job, "boom")
        assert job.status == "failed" and s.get(OttTitle, title_id).package_status == "failed"


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #
def test_resumable_upload_creates_a_title_and_queues_it(maker, monkeypatch):
    store = FakeStore()
    client = _client(monkeypatch, store)
    started = client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "My Film (final).mp4", "size_bytes": 3 * uploads.PART_BYTES + 5, "content_type": "video/mp4"})
    data = started.json()["data"]
    assert data["parts"] == 4 and data["key"].endswith("/My-Film-final-.mp4")
    urls = client.post("/api/v1/ott/uploads/parts", headers=H, json={
        "key": data["key"], "upload_id": data["upload_id"], "part_numbers": [3, 1, 3]}).json()["data"]["urls"]
    assert list(urls) == ["1", "3"]
    other = client.post("/api/v1/ott/uploads/parts", headers=H, json={
        "key": "ott-uploads/someone-else/x/f.mp4", "upload_id": "u", "part_numbers": [1]})
    assert other.status_code == 404
    done = client.post("/api/v1/ott/uploads/complete", headers=H, json={
        "key": data["key"], "upload_id": data["upload_id"], "title": "My film", "kind": "movie", "seconds": 3600,
        "short_side": 1080, "parts": [{"PartNumber": 2, "ETag": "b"}, {"PartNumber": 1, "ETag": "a"}]})
    assert done.status_code == 200, done.text
    assert store.completed[0][1][0]["PartNumber"] == 1
    assert done.json()["data"]["job"]["lane"] == "mac"
    assert client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "x.exe", "size_bytes": 10, "content_type": "application/x-msdownload"}).status_code == 400


def test_upload_routes_are_404_until_the_flag_is_on(maker, monkeypatch):
    monkeypatch.setenv("OTT_UPLOAD_LIVE", "0")
    client = _client(monkeypatch)
    assert client.post("/api/v1/ott/uploads", headers=H, json={
        "filename": "a.mp4", "size_bytes": 10, "content_type": "video/mp4"}).status_code == 404


# --------------------------------------------------------------------------- #
# Packaging
# --------------------------------------------------------------------------- #
def test_ladder_keeps_rungs_at_or_below_the_source_and_fixes_the_gop():
    assert [r.name for r in rungs_for(720)] == ["720p", "480p", "360p"]
    assert [r.name for r in rungs_for(240)] == ["360p"]
    source = ladder.Source(720, 1280, 30.0, 60.0)
    sizes = {rung.name: (w, h) for rung, w, h in ladder.plan(source)}
    assert sizes["720p"] == (720, 1280) and sizes["480p"] == (480, 852)
    cmd = " ".join(ladder.rung_command("ff", "in", "out", source, rungs_for(720)[0], 720, 1280))
    assert "-g 60" in cmd and "-keyint_min 60" in cmd and "-sc_threshold 0" in cmd
    vt = " ".join(ladder.rung_command("ff", "in", "out", source, rungs_for(720)[0], 720, 1280,
                                      encoder=ladder.ENCODER_VT))
    assert "h264_videotoolbox" in vt and "expr:gte(t,n_forced*2)" in vt


def test_packager_checksum_is_pinned_and_verified(tmp_path):
    assert packager.VERSION == "v3.9.3"
    assert packager.expected_sha256("linux-arm64") == (
        "d3a50cecc139b54435be1bbbfba5c0ea822d9e1e7edc3531f7821fba65ceebb0")
    fake = tmp_path / "packager"
    fake.write_bytes(b"not the pinned build")
    with pytest.raises(packager.PackagerError):
        packager.verify_binary(str(fake), "linux-arm64")
    if os.path.exists(PACKAGER):
        assert packager.verify_binary(PACKAGER, "osx-arm64") == packager.expected_sha256("osx-arm64")


def test_sprites_and_tracks():
    vtt = sprites.sprite_vtt(12.0, "thumbs.jpg")
    assert vtt.startswith("WEBVTT") and "thumbs.jpg#xywh=160,0,160,90" in vtt and "00:00:10.000 --> 00:00:12.000" in vtt
    assert tracks.subtitle("t.vtt", "tr").language == "tr"
    with pytest.raises(ValueError):
        tracks.dub("a.m4a", "Turkish")
    cmd = packager.command("pk", video=[("720p", "v.mp4")], audio="a.m4a", out_dir="o",
                           tracks=[tracks.subtitle("s.vtt", "en")])
    joined = " ".join(cmd)
    assert "--segment_duration 2" in joined and "--mpd_output o/manifest.mpd" in joined and "stream=text" in joined


def _src(tmp_path, seconds=6) -> str:
    path = str(tmp_path / "src.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size=720x1280:rate=30:d={seconds}", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-shortest", path], check=True)
    return path


def _extinfs(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.startswith("#EXTINF")]


@pytest.mark.integration
@pytest.mark.skipif(not HAS_MEDIA, reason="ffmpeg and the pinned packager required")
def test_free_title_gets_hls_and_dash_from_one_set_of_aligned_segments(tmp_path):
    result = pipeline.run(_src(tmp_path), str(tmp_path / "w"), ffmpeg=shutil.which("ffmpeg"), packager_bin=PACKAGER)
    out = Path(result.out_dir)
    assert result.rungs == ["720p", "480p", "360p"] and result.cpu_seconds > 0
    master = (out / "master.m3u8").read_text()
    assert master.count("#EXT-X-STREAM-INF") == 3 and "RESOLUTION=720x1280" in master
    durations = {tuple(_extinfs(out / f"v_{r}.m3u8")) for r in result.rungs}
    assert len(durations) == 1 and list(durations)[0][0] == "#EXTINF:2.000,"
    mpd = ET.parse(out / "manifest.mpd").getroot()
    ns = {"d": "urn:mpeg:dash:schema:mpd:2011"}
    reps = mpd.findall(".//d:Representation", ns)
    assert len(reps) == 4  # three video rungs + one audio
    assert (out / "thumbs.jpg").exists() and (out / "thumbs.vtt").read_text().startswith("WEBVTT")


@pytest.mark.integration
@pytest.mark.skipif(not HAS_MEDIA, reason="ffmpeg and the pinned packager required")
def test_paid_title_is_encrypted_with_aes128_and_decrypts_with_the_key(tmp_path):
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    protection = packager.Protection(key_hex="fedcba9876543210fedcba9876543210",
                                     iv_hex="00112233445566778899aabbccddeeff",
                                     key_uri="https://api.example/api/v1/ott/keys/t1")
    result = pipeline.run(_src(tmp_path), str(tmp_path / "w"), ffmpeg=shutil.which("ffmpeg"), packager_bin=PACKAGER,
                          protection=protection)
    out = Path(result.out_dir)
    media = (out / "v_720p.m3u8").read_text()
    assert '#EXT-X-KEY:METHOD=AES-128,URI="https://api.example/api/v1/ott/keys/t1",IV=0x0011' in media
    assert protection.key_hex not in media and protection.key_hex not in (out / "master.m3u8").read_text()
    assert not (out / "manifest.mpd").exists()
    raw_init = (out / "v_720p" / "init.mp4").read_bytes()
    assert b"ftyp" not in raw_init[:16]

    def decrypt(data: bytes) -> bytes:
        dec = Cipher(algorithms.AES(bytes.fromhex(protection.key_hex)),
                     modes.CBC(bytes.fromhex(protection.iv_hex))).decryptor()
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(dec.update(data) + dec.finalize()) + unpadder.finalize()

    clear = decrypt(raw_init) + decrypt((out / "v_720p" / "1.m4s").read_bytes())
    joined = tmp_path / "joined.mp4"
    joined.write_bytes(clear)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                            str(joined)], capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == "720,1280"


@pytest.mark.integration
@pytest.mark.skipif(not HAS_MEDIA, reason="ffmpeg and the pinned packager required")
def test_box1_task_packages_a_reel_and_records_it(maker, tmp_path, monkeypatch):
    from app.workers import tasks_ott

    title_id = _title(maker)
    uid = _uid(maker)
    with maker() as s:
        job = service.submit(s, s.get(OttTitle, title_id), source_key="r2:jobs/r/final.mp4", seconds=6,
                             short_side=720, user_id=uid)
        assert job.lane == "box1"
        s.commit()
        job_id = job.id
    monkeypatch.setenv("SHAKA_PACKAGER_PLATFORM", "osx-arm64")
    src = _src(tmp_path)
    uploaded = []
    view = tasks_ott.package_on_box1(job_id, download=lambda url, dest: shutil.copy(src, dest),
                                     upload_dir=lambda out, prefix, files: uploaded.extend(files),
                                     source_url=lambda key: "https://r2/x", ffmpeg=shutil.which("ffmpeg"),
                                     packager_bin=PACKAGER)
    assert view["status"] == "done" and view["node_id"] == "box1" and view["cpu_seconds"] > 0
    assert "master.m3u8" in uploaded and "manifest.mpd" in uploaded
    with maker() as s:
        assert s.get(OttEncodeJob, job_id).packager_sha256 == packager.expected_sha256("osx-arm64")


def test_box1_task_refuses_an_unpinned_packager(maker, tmp_path, monkeypatch):
    from app.workers import tasks_ott

    title_id = _title(maker)
    uid = _uid(maker)
    with maker() as s:
        job = service.submit(s, s.get(OttTitle, title_id), source_key="r2:k", seconds=6, short_side=720,
                             user_id=uid)
        s.commit()
        job_id = job.id
    fake = tmp_path / "packager"
    fake.write_bytes(b"x")
    monkeypatch.setattr(tasks_ott.package_on_box1_task, "apply_async", lambda *a, **k: None)
    view = tasks_ott.package_on_box1(job_id, download=lambda u, d: None, upload_dir=lambda *a: None,
                                     source_url=lambda k: "u", packager_bin=str(fake))
    assert view["status"] == "queued" and "checksum" in view["error"]


# --------------------------------------------------------------------------- #
# The Mac node tool
# --------------------------------------------------------------------------- #
def _tool():
    path = REPO / "tools" / "mac-node" / "ott_worker.py"
    spec = importlib.util.spec_from_file_location("ott_worker", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ott_worker"] = module
    spec.loader.exec_module(module)
    return module


class FakeApi:
    def __init__(self, job=None):
        self.calls, self.job = [], job

    def post(self, path, body=None):
        self.calls.append((path, body))
        if path == "/claim":
            return {"job": self.job}
        if path.endswith("/upload-urls"):
            return {"urls": {f: f"https://put/{f}" for f in body["files"]}}
        if path.endswith("/complete"):
            return {"id": "j1", "status": "done"}
        return {}


def test_mac_node_does_not_claim_on_a_full_disk(monkeypatch, tmp_path):
    tool = _tool()
    api = FakeApi({"job_id": "j1"})
    monkeypatch.setattr(tool, "free_gb", lambda path: 9.5)
    assert tool.cycle(api, str(tmp_path), ffmpeg="ff", packager_bin="pk", digest="d") is None
    assert [c[0] for c in api.calls] == ["/heartbeat"]


def test_mac_node_uploads_outputs_then_completes_or_reports_failure(monkeypatch, tmp_path):
    tool = _tool()
    out = tmp_path / "out"
    out.mkdir()
    (out / "master.m3u8").write_text("#EXTM3U")

    def fake_run(src, work, **kwargs):
        assert kwargs["encoder"] == "h264_videotoolbox"
        return pipeline.Result(out_dir=str(out), files=["master.m3u8"], cpu_seconds=3.5, rungs=["720p"])

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(tool, "free_gb", lambda path: 200.0)
    job = {"job_id": "j1", "source_url": "https://src", "encoder": "h264_videotoolbox", "protection": None}
    api = FakeApi(job)
    puts = []
    done = tool.cycle(api, str(tmp_path), ffmpeg="ff", packager_bin="pk", digest="d" * 64,
                      download=lambda url, dest: None, put=lambda url, path, ct: puts.append((url, ct)))
    assert done["status"] == "done" and puts == [("https://put/master.m3u8", "application/vnd.apple.mpegurl")]
    assert api.calls[-1] == ("/jobs/j1/complete", {"files": ["master.m3u8"], "cpu_seconds": 3.5,
                                                   "packager_sha256": "d" * 64})

    def broken(src, work, **kwargs):
        raise pipeline.PipelineError("encoder crashed")

    monkeypatch.setattr(pipeline, "run", broken)
    api = FakeApi(job)
    tool.cycle(api, str(tmp_path), ffmpeg="ff", packager_bin="pk", digest="d", download=lambda u, d: None)
    assert api.calls[-1] == ("/jobs/j1/fail", {"error": "encoder crashed"})


def test_node_registration_is_staff_only(maker, monkeypatch):
    client = _client(monkeypatch)
    assert client.post("/api/v1/admin/ott/nodes", headers=H, json={"name": "mac", "kind": "mac"}).status_code == 403
    with maker() as s:
        s.query(User).one().is_staff = True
        s.commit()
    made = client.post("/api/v1/admin/ott/nodes", headers=H, json={"name": "mac", "kind": "mac"}).json()["data"]
    assert made["token"].startswith("ottn_")
    with maker() as s:
        assert s.query(OttNode).one().token_hash == hashlib.sha256(made["token"].encode()).hexdigest()
