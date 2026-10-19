"""QM verify (h): the Mac and burst lanes bill the measured source length once it is reported.

Encode minutes are metered hourly from ``source_seconds`` of finished jobs
(``ott_usage.measure``) and the monthly upload quota sums the same column, so the
declared length acts as the hold until the job finishes. When a node reports the
probed length on ``complete``, that length replaces the declared one exactly once:
a shorter source releases the difference, a longer one adds it, a repeated report
changes nothing, no report keeps the declared length, and a bad length is refused.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
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
from app.models.db.models import User
from app.models.exception import HttpException
from app.services.billing import ott_usage
from app.services.ott_transcode import keys, mac_node, nodes, pipeline, service, uploads
from app.services.ott_transcode import router as transcode_router
from app.services.ott_transcode.models import OttEncodeJob
from app.utils import utils

REPO = Path(__file__).resolve().parents[2]
KEY = "qm-render-key"
SHA = "a" * 64
DECLARED = 3600.0


class Store:
    def presign_get(self, key, ttl):
        return f"https://r2/get/{key}"

    def presign_put(self, key, content_type, ttl):
        return f"https://r2/put/{key}"


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
    monkeypatch.setattr(service, "paid_plan", lambda user_id: True)
    for name in ("OTT_ENABLED", "OTT_UPLOAD_LIVE", "OTT_PACKAGING_LIVE"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv(keys.SECRET_ENV, "a-test-secret-that-is-long-enough")
    with factory() as s:
        s.add(User(email="render@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    return factory


def _claimed(maker, lane: str):
    """A long-form job claimed by a live node of ``lane``: (job id, node id, token, user id)."""
    with maker() as s:
        uid = s.query(User).one().id
        channel = OttChannel(user_id=uid, handle="ch", title="Ch", brand_colors=[])
        s.add(channel)
        s.flush()
        title = OttTitle(channel_id=channel.id, title="T", access_tier="free", genres=[], geo_countries=[],
                         duration_s=DECLARED)
        s.add(title)
        s.flush()
        node, token = nodes.register(s, f"{lane}-1", lane)
        nodes.heartbeat(s, node, free_gb=200, cores=8)
        job = service.submit(s, title, source_key="ott:ott-uploads/u/x/film.mp4", seconds=DECLARED,
                             short_side=1080, user_id=uid)
        assert job.lane == lane
        got = mac_node.claim(s, node, Store(), api_base="https://api")
        assert got["job_id"] == job.id
        s.commit()
        return job.id, node.id, token, uid


def _complete(maker, job_id, node_id, **kw):
    with maker() as s:
        node = s.get(nodes.OttNode, node_id)
        view = mac_node.complete(s, node, job_id, cpu_seconds=kw.pop("cpu_seconds", 900.0), packager_sha256=SHA,
                                 files=["master.m3u8"], **kw)
        s.commit()
        return view


def _billed_minutes(maker, uid) -> float:
    """Encode minutes the hourly meter records for this creator (the hour the job finished in)."""
    with maker() as s:
        job = s.query(OttEncodeJob).filter(OttEncodeJob.user_id == uid).one()
        finished = job.finished_at if job.finished_at.tzinfo else job.finished_at.replace(tzinfo=timezone.utc)
        usage = ott_usage.measure(s, ott_usage.hour_key(finished), counter_=ott_usage.MemoryCounter())
        return usage.get(uid, {}).get("encode_minutes", 0.0)


def _quota_minutes(maker, uid) -> float:
    with maker() as s:
        return uploads.usage(s, uid)[1]


def _only_mac_live(monkeypatch):
    real = nodes.live_nodes

    def live(session, kind):
        return real(session, kind) if kind == "mac" else []

    monkeypatch.setattr(nodes, "live_nodes", live)


def _only_burst_live(monkeypatch):
    real = nodes.live_nodes

    def live(session, kind):
        return real(session, kind) if kind == "burst" else []

    monkeypatch.setattr(nodes, "live_nodes", live)


# --------------------------------------------------------------------------- #
# Measured length is billed
# --------------------------------------------------------------------------- #
def test_mac_lane_bills_the_measured_length_and_refunds_a_shorter_source(maker, monkeypatch):
    _only_mac_live(monkeypatch)
    job_id, node_id, _token, uid = _claimed(maker, "mac")
    assert _quota_minutes(maker, uid) == pytest.approx(60.0)  # the declared length is the hold
    view = _complete(maker, job_id, node_id, measured_seconds=2700.0)
    assert view["status"] == "done"
    assert _billed_minutes(maker, uid) == pytest.approx(45.0)  # 15 minutes released
    assert _quota_minutes(maker, uid) == pytest.approx(45.0)


def test_burst_lane_bills_the_measured_length_and_charges_a_longer_source(maker, monkeypatch):
    _only_burst_live(monkeypatch)
    monkeypatch.setenv("OTT_BURST_USD_PER_CPU_HOUR", "0.10")
    job_id, node_id, _token, uid = _claimed(maker, "burst")
    view = _complete(maker, job_id, node_id, measured_seconds=4500.0, cpu_seconds=7200.0)
    assert view["status"] == "done" and view["cost_usd"] == pytest.approx(0.2)
    assert _billed_minutes(maker, uid) == pytest.approx(75.0)  # 15 minutes added
    assert _quota_minutes(maker, uid) == pytest.approx(75.0)


def test_a_repeated_report_bills_once(maker, monkeypatch):
    _only_mac_live(monkeypatch)
    job_id, node_id, _token, uid = _claimed(maker, "mac")
    first = _complete(maker, job_id, node_id, measured_seconds=1800.0)
    again = _complete(maker, job_id, node_id, measured_seconds=5400.0, cpu_seconds=1.0)
    assert again == first
    assert _billed_minutes(maker, uid) == pytest.approx(30.0)
    with maker() as s:
        job = s.get(OttEncodeJob, job_id)
        assert job.source_seconds == pytest.approx(1800.0) and job.cpu_seconds == pytest.approx(900.0)
        # finishing an already-done job directly is a no-op too
        service.finish(s, job, cpu_seconds=5.0, packager_sha256=SHA, measured_seconds=600.0)
        assert job.source_seconds == pytest.approx(1800.0)
        s.commit()
    assert _billed_minutes(maker, uid) == pytest.approx(30.0)


def test_another_node_cannot_report_a_finished_job(maker, monkeypatch):
    _only_mac_live(monkeypatch)
    job_id, node_id, _token, _uid = _claimed(maker, "mac")
    _complete(maker, job_id, node_id, measured_seconds=1800.0)
    with maker() as s:
        other, _ = nodes.register(s, "mac-2", "mac")
        s.commit()
        other_id = other.id
    with pytest.raises(service.TranscodeError) as err:
        _complete(maker, job_id, other_id, measured_seconds=60.0)
    assert err.value.status_code == 404


def test_no_measured_length_keeps_the_declared_estimate(maker, monkeypatch):
    _only_mac_live(monkeypatch)
    job_id, node_id, _token, uid = _claimed(maker, "mac")
    _complete(maker, job_id, node_id)
    assert _billed_minutes(maker, uid) == pytest.approx(60.0)


@pytest.mark.parametrize("bad", [-30.0, 0.0, float("nan"), float("inf"), service.MAX_SOURCE_S + 1, "abc"])
def test_a_bad_measured_length_is_refused_and_nothing_is_billed(maker, monkeypatch, bad):
    _only_mac_live(monkeypatch)
    job_id, node_id, _token, uid = _claimed(maker, "mac")
    with pytest.raises(service.TranscodeError) as err:
        _complete(maker, job_id, node_id, measured_seconds=bad)
    assert err.value.status_code == 400 and err.value.code == "bad_duration"
    with maker() as s:
        job = s.get(OttEncodeJob, job_id)
        assert job.status == "claimed" and job.source_seconds == pytest.approx(DECLARED)
    # the node can still finish it with a good report afterwards
    _complete(maker, job_id, node_id, measured_seconds=3000.0)
    assert _billed_minutes(maker, uid) == pytest.approx(50.0)


def test_measured_seconds_round_to_milliseconds():
    job = OttEncodeJob(id="j", lane="mac", source_seconds=10.0)
    assert service.checked_seconds(job, None) is None
    assert service.checked_seconds(job, 61.23456) == pytest.approx(61.235)


# --------------------------------------------------------------------------- #
# The node route and the node tool
# --------------------------------------------------------------------------- #
def _client():
    app = FastAPI()

    @app.exception_handler(HttpException)
    async def _h(request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data,
                                                                                    exc.message))

    app.include_router(transcode_router.router)
    return TestClient(app)


def test_node_route_takes_the_measured_length(maker, monkeypatch):
    _only_mac_live(monkeypatch)
    monkeypatch.setattr(transcode_router, "storage", lambda: Store())
    job_id, _node_id, token, uid = _claimed(maker, "mac")
    client = _client()
    auth = {"Authorization": f"Bearer {token}"}
    body = {"files": ["master.m3u8"], "cpu_seconds": 10, "packager_sha256": SHA}
    bad = client.post(f"/api/v1/ott/nodes/jobs/{job_id}/complete", headers=auth,
                      json={**body, "measured_seconds": -1})
    assert bad.status_code == 400
    ok = client.post(f"/api/v1/ott/nodes/jobs/{job_id}/complete", headers=auth,
                     json={**body, "measured_seconds": 1200})
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "done"
    again = client.post(f"/api/v1/ott/nodes/jobs/{job_id}/complete", headers=auth,
                        json={**body, "measured_seconds": 9000})
    assert again.status_code == 200 and again.json()["data"]["status"] == "done"
    assert _billed_minutes(maker, uid) == pytest.approx(20.0)


def _tool():
    path = REPO / "tools" / "mac-node" / "ott_worker.py"
    spec = importlib.util.spec_from_file_location("ott_worker_qm", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ott_worker_qm"] = module
    spec.loader.exec_module(module)
    return module


def test_node_tool_reports_the_probed_length(monkeypatch, tmp_path):
    from app.services.ott_transcode import ladder

    tool = _tool()
    out = tmp_path / "out"
    out.mkdir()
    (out / "master.m3u8").write_text("#EXTM3U")
    calls = []

    class Api:
        def post(self, path, body=None):
            calls.append((path, body))
            if path == "/claim":
                return {"job": {"job_id": "j1", "source_url": "https://src", "encoder": "libx264",
                                "protection": None}}
            if path.endswith("/upload-urls"):
                return {"urls": {f: f"https://put/{f}" for f in body["files"]}}
            return {"status": "done"}

    source = ladder.Source(1920, 1080, 30.0, 2712.4, True)
    monkeypatch.setattr(pipeline, "run", lambda src, work, **kw: pipeline.Result(
        out_dir=str(out), files=["master.m3u8"], cpu_seconds=4.0, rungs=["1080p"], source=source))
    monkeypatch.setattr(tool, "free_gb", lambda path: 200.0)
    tool.cycle(Api(), str(tmp_path), ffmpeg="ff", packager_bin="pk", digest=SHA,
               download=lambda url, dest: None, put=lambda url, path, ct: None)
    assert calls[-1] == ("/jobs/j1/complete", {"files": ["master.m3u8"], "cpu_seconds": 4.0,
                                               "packager_sha256": SHA, "measured_seconds": 2712.4})


def test_finished_hour_is_the_hour_the_measured_job_lands_in(maker, monkeypatch):
    """The meter reads the job in its finish hour only (no second hour bills it again)."""
    _only_mac_live(monkeypatch)
    job_id, node_id, _token, uid = _claimed(maker, "mac")
    _complete(maker, job_id, node_id, measured_seconds=600.0)
    with maker() as s:
        job = s.get(OttEncodeJob, job_id)
        finished = job.finished_at if job.finished_at.tzinfo else job.finished_at.replace(tzinfo=timezone.utc)
        next_hour = ott_usage.hour_key(finished + timedelta(hours=1))
        assert uid not in ott_usage.measure(s, next_hour, counter_=ott_usage.MemoryCounter())
    assert datetime.now(timezone.utc) >= finished
