"""Dub any uploaded video (pyvideotrans sidecar) — catalog, CLI boundary,
worker delegate, credits/refunds and the HTTP surface.

The container is never run: ``sidecar._run_process`` and the R2/ffprobe seams
are monkeypatched. An in-memory SQLite DB backs the controller + refund tests.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.domains.dub.router as dub_router
import app.domains.dub.service as dub_service
import app.domains.dub.sidecar as dub_sidecar
from app.domains.dub import catalog
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.base import Base
from app.models.db.models import Asset, User
from app.models.db.repositories import CreditRepository, JobRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "dub-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode()).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}
_OTHER_KEY = "dub-other"
_OTHER_HASH = hashlib.sha256(_OTHER_KEY.encode()).hexdigest()
_OTHER_HEADERS = {"x-api-key": _OTHER_KEY}

_REPO_ROOT = Path(__file__).resolve().parents[2]


# =========================================================================== #
# Catalog (pure)
# =========================================================================== #
def test_default_plan_is_free_edge_voice_with_local_whisper():
    plan = catalog.resolve_plan(source_language="en", target_language="tr", env={})
    assert plan.voice_engine == "edge"
    assert plan.voice == "tr-TR-EmelNeural"
    assert plan.whisper_model == "small"
    assert plan.translation == "google"
    assert plan.free is True
    assert plan.credits_cost == catalog.credit_cost(True)


def test_plan_rejects_same_language_and_foreign_voice():
    with pytest.raises(catalog.DubOptionError):
        catalog.resolve_plan(source_language="en", target_language="en", env={})
    with pytest.raises(catalog.DubOptionError):
        catalog.resolve_plan(source_language="en", target_language="tr", voice="en-US-GuyNeural", env={})
    with pytest.raises(catalog.DubOptionError):
        catalog.resolve_plan(source_language="xx", target_language="tr", env={})
    with pytest.raises(catalog.DubOptionError):
        catalog.resolve_plan(source_language="en", target_language="tr", whisper_model="large-v3", env={})


def test_elevenlabs_needs_a_key_and_is_not_free():
    with pytest.raises(catalog.DubOptionError):
        catalog.resolve_plan(
            source_language="en", target_language="es", voice_engine="elevenlabs", voice="Rachel", env={}
        )
    plan = catalog.resolve_plan(
        source_language="en",
        target_language="es",
        voice_engine="elevenlabs",
        voice="Rachel",
        env={"ELEVENLABS_API_KEY": "x"},
    )
    assert plan.free is False
    assert plan.credits_cost == catalog.credit_cost(False)
    with pytest.raises(catalog.DubOptionError):
        catalog.resolve_plan(
            source_language="en", target_language="es", voice_engine="elevenlabs",
            voice="bad;rm -rf", env={"ELEVENLABS_API_KEY": "x"},
        )


def test_translation_uses_relay_when_configured():
    plan = catalog.resolve_plan(source_language="en", target_language="tr", env={"RELAY_URL": "http://relay:3000"})
    assert plan.translation == "relay"


def test_options_document_reports_availability_names_only():
    doc = catalog.options_document({"ELEVENLABS_API_KEY": "secret-value"})
    assert doc["available"] is False
    assert "secret-value" not in repr(doc)
    engines = {e["id"]: e for e in doc["voice_engines"]}
    assert engines["edge"]["free"] is True and engines["elevenlabs"]["available"] is True
    assert catalog.options_document({"PYVIDEOTRANS_IMAGE": "menivor/pyvideotrans:v4.13"})["available"] is True


def test_free_tier_format_catalog_lists_dub_formats():
    from app.core.launch.formats import format_catalog

    locked = {f["id"] for f in format_catalog({})["locked_formats"]}
    assert {"dub_video_free_voice", "dub_video_premium_voice"} <= locked
    available = {f["id"] for f in format_catalog({"PYVIDEOTRANS_IMAGE": "img"})["available_formats"]}
    assert "dub_video_free_voice" in available
    assert "dub_video_premium_voice" not in available
    both = {f["id"] for f in format_catalog({"PYVIDEOTRANS_IMAGE": "img", "ELEVENLABS_API_KEY": "k"})["available_formats"]}
    assert "dub_video_premium_voice" in both


# =========================================================================== #
# CLI boundary (sidecar)
# =========================================================================== #
def _settings(tmp_path, **kw):
    return dub_sidecar.SidecarSettings(
        image="menivor/pyvideotrans:v4.13",
        lock_path=str(tmp_path / "dub.lock"),
        work_root=str(tmp_path / "work"),
        **kw,
    )


_PLAN = {
    "source_language": "en",
    "target_language": "tr",
    "voice_engine": "edge",
    "voice": "tr-TR-EmelNeural",
    "whisper_model": "small",
    "translation": "google",
}


def test_build_command_is_a_fixed_vtv_invocation(tmp_path):
    argv = dub_sidecar.build_command(
        _settings(tmp_path, network="menivor"),
        job_id="job-1",
        host_dir="/host/work/job-1",
        plan=_PLAN,
        secret_names=("PVT_ELEVENLABS_KEY",),
        user="1000:1000",
    )
    joined = " ".join(argv)
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "-v /host/work/job-1:/work" in joined
    assert "--network menivor" in joined
    assert "--user 1000:1000" in joined
    # Secret NAMES only: value comes from the child env.
    i = argv.index("-e")
    assert argv[i + 1] == "PVT_ELEVENLABS_KEY"
    task = argv[argv.index("menivor/pyvideotrans:v4.13") + 1:]
    assert task[:2] == ["--task", "vtv"]
    assert "--subtitle_type" in task and task[task.index("--subtitle_type") + 1] == "2"
    assert task[task.index("--tts_type") + 1] == "0"
    assert task[task.index("--translate_type") + 1] == "0"
    assert task[task.index("--recogn_type") + 1] == "0"
    assert task[task.index("--voice_role") + 1] == "tr-TR-EmelNeural"


def test_build_command_requires_an_image(tmp_path):
    with pytest.raises(dub_sidecar.SidecarError):
        dub_sidecar.build_command(
            dub_sidecar.SidecarSettings(image=""), job_id="j", host_dir="/x", plan=_PLAN
        )


def test_host_path_mapping(tmp_path):
    s = _settings(tmp_path, host_work_root="/srv/dub")
    assert dub_sidecar.host_path_for(s, str(tmp_path / "work" / "a")) == "/srv/dub/a"
    with pytest.raises(dub_sidecar.SidecarError):
        dub_sidecar.host_path_for(s, "/etc")


def _fake_outputs(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "input.mp4").write_bytes(b"dubbed-video")
    (out_dir / "tr.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nMerhaba\n")
    (out_dir / "en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")


def test_run_dub_success_passes_secrets_via_env_only(tmp_path, monkeypatch):
    work = tmp_path / "work" / "job"
    work.mkdir(parents=True)
    monkeypatch.setattr(dub_sidecar, "_elevenlabs_key", lambda: "el-secret")
    seen = {}

    def _fake_run(argv, env, timeout):
        seen["argv"], seen["env"] = argv, env
        _fake_outputs(work / "out")
        return subprocess.CompletedProcess(argv, 0, "done", "")

    monkeypatch.setattr(dub_sidecar, "_run_process", _fake_run)
    plan = {**_PLAN, "voice_engine": "elevenlabs", "voice": "Rachel"}
    result = dub_sidecar.run_dub(job_id="job", work_dir=str(work), plan=plan, settings=_settings(tmp_path))
    assert "el-secret" not in " ".join(seen["argv"])
    assert seen["env"]["PVT_ELEVENLABS_KEY"] == "el-secret"
    assert seen["argv"][seen["argv"].index("--tts_type") + 1] == "24"
    assert result.video_path.endswith("input.mp4")
    assert set(result.subtitle_paths) == {"tr", "en"}


def test_run_dub_relay_falls_back_to_google_when_relay_gone(tmp_path, monkeypatch):
    work = tmp_path / "work" / "job"
    work.mkdir(parents=True)
    monkeypatch.setattr(dub_sidecar, "relay_target", lambda env=None: None)
    seen = {}

    def _fake_run(argv, env, timeout):
        seen["argv"] = argv
        _fake_outputs(work / "out")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(dub_sidecar, "_run_process", _fake_run)
    dub_sidecar.run_dub(job_id="job", work_dir=str(work), plan={**_PLAN, "translation": "relay"}, settings=_settings(tmp_path))
    assert seen["argv"][seen["argv"].index("--translate_type") + 1] == "0"


def test_run_dub_relay_uses_openai_compatible_engine(tmp_path, monkeypatch):
    work = tmp_path / "work" / "job"
    work.mkdir(parents=True)
    monkeypatch.setattr(
        dub_sidecar, "relay_target",
        lambda env=None: {"api": "http://relay/openai/v1", "key": "", "model": "tensorzero::model_name::openai::gpt-4o-mini"},
    )
    seen = {}

    def _fake_run(argv, env, timeout):
        seen["argv"], seen["env"] = argv, env
        _fake_outputs(work / "out")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(dub_sidecar, "_run_process", _fake_run)
    dub_sidecar.run_dub(job_id="job", work_dir=str(work), plan={**_PLAN, "translation": "relay"}, settings=_settings(tmp_path))
    assert seen["argv"][seen["argv"].index("--translate_type") + 1] == "9"
    assert seen["env"]["PVT_LLM_API"] == "http://relay/openai/v1"
    assert seen["env"]["PVT_LLM_KEY"] == "none"


def test_run_dub_nonzero_exit_and_empty_output_fail(tmp_path, monkeypatch):
    work = tmp_path / "work" / "job"
    (work / "out").mkdir(parents=True)
    monkeypatch.setattr(
        dub_sidecar, "_run_process", lambda argv, env, t: subprocess.CompletedProcess(argv, 1, "", "boom")
    )
    with pytest.raises(dub_sidecar.SidecarError, match="exit 1"):
        dub_sidecar.run_dub(job_id="job", work_dir=str(work), plan=_PLAN, settings=_settings(tmp_path))
    monkeypatch.setattr(
        dub_sidecar, "_run_process", lambda argv, env, t: subprocess.CompletedProcess(argv, 0, "", "")
    )
    with pytest.raises(dub_sidecar.SidecarError, match="no dubbed video"):
        dub_sidecar.run_dub(job_id="job", work_dir=str(work), plan=_PLAN, settings=_settings(tmp_path))


def test_run_dub_timeout_force_removes_container(tmp_path, monkeypatch):
    work = tmp_path / "work" / "job"
    work.mkdir(parents=True)

    def _timeout(argv, env, t):
        raise subprocess.TimeoutExpired(argv, t)

    removed = []
    monkeypatch.setattr(dub_sidecar, "_run_process", _timeout)
    monkeypatch.setattr(dub_sidecar, "_force_remove", lambda s, job_id: removed.append(job_id))
    with pytest.raises(dub_sidecar.SidecarError, match="timed out"):
        dub_sidecar.run_dub(job_id="job-9", work_dir=str(work), plan=_PLAN, settings=_settings(tmp_path))
    assert removed == ["job-9"]


def test_host_lock_allows_one_dub_at_a_time(tmp_path):
    lock = str(tmp_path / "dub.lock")
    with dub_sidecar.host_lock(lock):
        with pytest.raises(dub_sidecar.SidecarBusy):
            with dub_sidecar.host_lock(lock):
                pass
    with dub_sidecar.host_lock(lock):  # released again
        pass


def test_no_python_import_of_pyvideotrans_in_api():
    pattern = re.compile(r"^\s*(from|import)\s+(videotrans|pyvideotrans)\b", re.M)
    offenders = []
    for path in (_REPO_ROOT / "apps" / "api" / "app").rglob("*.py"):
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(path))
    assert offenders == []


# =========================================================================== #
# Worker delegate (service)
# =========================================================================== #
def _job_params(**extra):
    return {"video_key": "uploads/src.mp4", **_PLAN, "free": True, "credits_cost": 2, "_correlation_id": "c-1", **extra}


def _patch_service(monkeypatch, tmp_path, *, duration=30.0):
    monkeypatch.setattr(dub_service, "_load_job_context", lambda jid: ("u-1", _job_params()))
    monkeypatch.setattr(dub_service, "_set_progress", lambda *a, **k: None)
    monkeypatch.setattr(dub_sidecar, "settings_from_config", lambda env=None: _settings(tmp_path))

    def _download(key, path):
        Path(path).write_bytes(b"source")

    monkeypatch.setattr(dub_service, "_download_input", _download)
    monkeypatch.setattr(dub_service, "probe_duration", lambda path: duration)
    uploads = []
    monkeypatch.setattr(dub_service, "_upload", lambda path, key, ct: uploads.append((key, ct)))
    persisted = {}
    monkeypatch.setattr(dub_service, "_persist_and_complete", lambda **kw: persisted.update(kw))
    return uploads, persisted


def test_run_dub_video_uploads_video_and_subtitles(tmp_path, monkeypatch):
    uploads, persisted = _patch_service(monkeypatch, tmp_path)

    def _fake_run_dub(*, job_id, work_dir, plan, settings):
        out = Path(work_dir) / "out"
        _fake_outputs(out)
        assert (Path(work_dir) / "input.mp4").read_bytes() == b"source"
        return dub_sidecar.collect_outputs(str(out), plan)

    monkeypatch.setattr(dub_sidecar, "run_dub", _fake_run_dub)
    out = dub_service.run_dub_video("job-1")
    keys = [k for k, _ in uploads]
    assert keys[0].startswith("jobs/job-1/dub/") and keys[0].endswith("-tr.mp4")
    assert set(out["subtitle_keys"]) == {"tr", "en"}
    assert persisted["video_key"] == keys[0]
    assert persisted["meta"]["free"] is True
    # Work dir is cleaned up.
    assert list((tmp_path / "work").iterdir()) == []


def test_run_dub_video_rejects_over_long_video(tmp_path, monkeypatch):
    _patch_service(monkeypatch, tmp_path, duration=catalog.max_seconds() + 1)
    monkeypatch.setattr(dub_sidecar, "run_dub", lambda **kw: pytest.fail("must not run"))
    with pytest.raises(RuntimeError, match="limit"):
        dub_service.run_dub_video("job-1")


def test_run_dub_video_busy_host_raises_busy(tmp_path, monkeypatch):
    _patch_service(monkeypatch, tmp_path)
    with dub_sidecar.host_lock(str(tmp_path / "dub.lock")):
        with pytest.raises(dub_sidecar.SidecarBusy):
            dub_service.run_dub_video("job-1")


# =========================================================================== #
# DB-backed: refunds + HTTP
# =========================================================================== #
def _factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return Factory, _get_session


def _make_user(Factory, email, key_hash, credits=0) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        if credits:
            CreditRepository(s).grant(uid, credits, reason="signup")
        s.commit()
    return uid


def _add_asset(Factory, uid, key, content_type="video/mp4", kind="video", size=1000):
    with Factory() as s:
        s.add(Asset(user_id=uid, kind=kind, r2_key=key, content_type=content_type, size_bytes=size, meta={}))
        s.commit()


def test_refund_is_idempotent_and_task_failure_refunds(monkeypatch):
    Factory, get_session = _factory()
    monkeypatch.setattr("app.models.db.base.get_session", get_session)
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    with Factory() as s:
        job = JobRepository(s).create(user_id=uid, kind="dub_video", params={"credits_cost": 2})
        jid = job.id
        CreditRepository(s).debit(uid, 2, jid, "dub_video_debit")
        s.commit()

    from app.domains.dub.tasks import DubVideoTask

    DubVideoTask().on_failure(RuntimeError("engine died"), "t", [{"job_id": jid}], {}, None)
    dub_service.refund_dub_video(jid)  # second call is a no-op
    with Factory() as s:
        assert CreditRepository(s).balance(uid) == 10
        job = JobRepository(s).get(jid)
        assert job.params["refunded"] is True
        assert "engine died" in (job.error or "")


@pytest.fixture()
def api(monkeypatch):
    Factory, get_session = _factory()
    monkeypatch.setattr(dub_router, "get_session", get_session)
    monkeypatch.setattr("app.models.db.base.get_session", get_session)
    monkeypatch.setattr(dub_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setenv("PYVIDEOTRANS_IMAGE", "menivor/pyvideotrans:v4.13")
    monkeypatch.delenv("RELAY_URL", raising=False)
    enqueued: list[str] = []
    monkeypatch.setattr(dub_router, "_enqueue", lambda jid, rid: enqueued.append(jid))

    app = FastAPI()
    app.include_router(dub_router.router)

    def _handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)
        )

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app), Factory, enqueued


def _body(**kw):
    return {"video_key": "uploads/src.mp4", "source_language": "en", "target_language": "tr", **kw}


def test_create_dub_debits_and_enqueues(api):
    client, Factory, enqueued = api
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    _add_asset(Factory, uid, "uploads/src.mp4")
    resp = client.post("/api/v1/dub/videos", json=_body(), headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["state"] == "processing"
    assert data["free"] is True and data["voice"] == "tr-TR-EmelNeural"
    with Factory() as s:
        job = JobRepository(s).get(data["dub_id"])
        assert job.kind == "dub_video"
        assert job.params["video_key"] == "uploads/src.mp4"
        assert CreditRepository(s).balance(uid) == 10 - catalog.credit_cost(True)
    assert enqueued == [data["dub_id"]]


def test_create_dub_locked_without_engine(api, monkeypatch):
    client, Factory, enqueued = api
    monkeypatch.delenv("PYVIDEOTRANS_IMAGE")
    monkeypatch.setattr(catalog, "_cfg", lambda name, default: default)
    _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    resp = client.post("/api/v1/dub/videos", json=_body(), headers=_HEADERS)
    assert resp.status_code == 402
    assert enqueued == []


def test_create_dub_rejects_foreign_or_non_video_asset(api):
    client, Factory, enqueued = api
    _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    other = _make_user(Factory, "b@example.com", _OTHER_HASH, credits=10)
    _add_asset(Factory, other, "uploads/src.mp4")
    resp = client.post("/api/v1/dub/videos", json=_body(), headers=_HEADERS)
    assert resp.status_code == 403
    _add_asset(Factory, other, "uploads/pic.png", content_type="image/png", kind="image")
    resp = client.post("/api/v1/dub/videos", json=_body(video_key="uploads/pic.png"), headers=_OTHER_HEADERS)
    assert resp.status_code == 400
    assert enqueued == []


def test_create_dub_bad_options_and_insufficient_credits(api):
    client, Factory, enqueued = api
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=1)
    _add_asset(Factory, uid, "uploads/src.mp4")
    assert client.post("/api/v1/dub/videos", json=_body(target_language="en"), headers=_HEADERS).status_code == 400
    resp = client.post("/api/v1/dub/videos", json=_body(), headers=_HEADERS)
    assert resp.status_code == 402
    with Factory() as s:
        assert CreditRepository(s).balance(uid) == 1
        assert JobRepository(s).list_for_user_by_kind(uid, "dub_video") == []
    assert enqueued == []


def test_one_dub_in_flight_per_user(api):
    client, Factory, enqueued = api
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=20)
    _add_asset(Factory, uid, "uploads/src.mp4")
    assert client.post("/api/v1/dub/videos", json=_body(), headers=_HEADERS).status_code == 200
    assert client.post("/api/v1/dub/videos", json=_body(), headers=_HEADERS).status_code == 409


def test_enqueue_failure_refunds(api, monkeypatch):
    client, Factory, _ = api
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    _add_asset(Factory, uid, "uploads/src.mp4")

    def _boom(jid, rid):
        raise ConnectionError("broker down")

    monkeypatch.setattr(dub_router, "_enqueue", _boom)
    resp = client.post("/api/v1/dub/videos", json=_body(), headers=_HEADERS)
    assert resp.status_code == 502
    with Factory() as s:
        assert CreditRepository(s).balance(uid) == 10


def test_poll_is_owner_scoped_and_returns_outputs(api, monkeypatch):
    client, Factory, _ = api
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    _make_user(Factory, "b@example.com", _OTHER_HASH, credits=0)
    _add_asset(Factory, uid, "uploads/src.mp4")
    dub_id = client.post("/api/v1/dub/videos", json=_body(), headers=_HEADERS).json()["data"]["dub_id"]
    assert client.get(f"/api/v1/dub/videos/{dub_id}", headers=_OTHER_HEADERS).status_code == 404

    with Factory() as s:
        job = JobRepository(s).get(dub_id)
        job.params = {**job.params, "subtitle_keys": {"tr": "jobs/x/dub/a-tr.srt"}}
        job.state = TASK_STATE_COMPLETE
        job.result_key = "jobs/x/dub/a-tr.mp4"
        s.commit()
    monkeypatch.setattr(dub_router, "_presign", lambda key, name="": f"https://signed/{key}")
    data = client.get(f"/api/v1/dub/videos/{dub_id}", headers=_HEADERS).json()["data"]
    assert data["state"] == "complete"
    assert data["video_url"] == "https://signed/jobs/x/dub/a-tr.mp4"
    assert data["subtitles"][0]["language"] == "tr"
    listed = client.get("/api/v1/dub/videos", headers=_HEADERS).json()["data"]["dubs"]
    assert [d["dub_id"] for d in listed] == [dub_id]


def test_options_route(api):
    client, Factory, _ = api
    _make_user(Factory, "a@example.com", _KEY_HASH)
    data = client.get("/api/v1/dub/options", headers=_HEADERS).json()["data"]
    assert data["available"] is True
    assert any(lang["code"] == "tr" for lang in data["languages"])


# =========================================================================== #
# Dub a finished reel directly (jobs/<id>/final.mp4)
# =========================================================================== #
def _make_reel(Factory, user_id: str, *, complete: bool = True) -> str:
    with Factory() as s:
        job = JobRepository(s).create(user_id=user_id, kind="avatar_reel", params={})
        key = f"jobs/{job.id}/final.mp4"
        job.result_key = key
        if complete:
            job.state = TASK_STATE_COMPLETE
        s.commit()
        return key


def test_dub_own_finished_reel_with_clean_access(api, monkeypatch):
    client, Factory, enqueued = api
    monkeypatch.setattr("app.services.user_entitlements.can_access_clean_result", lambda uid, **k: True)
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    key = _make_reel(Factory, uid)
    resp = client.post("/api/v1/dub/videos", json=_body(video_key=key), headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["source_key"] == key
    assert len(enqueued) == 1


def test_dub_reel_needs_clean_access(api, monkeypatch):
    client, Factory, enqueued = api
    monkeypatch.setattr("app.services.user_entitlements.can_access_clean_result", lambda uid, **k: False)
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    key = _make_reel(Factory, uid)
    resp = client.post("/api/v1/dub/videos", json=_body(video_key=key), headers=_HEADERS)
    assert resp.status_code == 402
    assert enqueued == []


def test_dub_reel_rejects_foreign_or_unfinished(api, monkeypatch):
    client, Factory, enqueued = api
    monkeypatch.setattr("app.services.user_entitlements.can_access_clean_result", lambda uid, **k: True)
    uid = _make_user(Factory, "a@example.com", _KEY_HASH, credits=10)
    other = _make_user(Factory, "b@example.com", _OTHER_HASH, credits=10)
    foreign = _make_reel(Factory, other)
    pending = _make_reel(Factory, uid, complete=False)
    for key in (foreign, pending, "jobs/../uploads/x.mp4", "jobs/abc/final.mov"):
        resp = client.post("/api/v1/dub/videos", json=_body(video_key=key), headers=_HEADERS)
        assert resp.status_code == 403, key
    assert enqueued == []
