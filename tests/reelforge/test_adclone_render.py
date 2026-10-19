"""Ad Clone paid render: approve (credits, cap, idempotency), the worker state machine with mocked
Kling / ElevenLabs / storage, the 9:16 + 16:9 cut, the Relay LLM writer and the OCR fallback.
Nothing here reaches a network or spends."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
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

import app.models.db.base as db_base
from app.domains.adclone import (assemble, captions, engine_clients, kling, presets, relay_writer, render_job,
                                 render_tasks, rewrite, router as adclone_router, service, vision)
from app.domains.adclone.rewrite import CloneOptions
from app.domains.adclone.schemas import CloneBrief
from app.models.db import film as film_models
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.services.billing import premium_credits as pc
from app.utils import utils

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
KEY = "ad-clone-render-key"
H = {"x-api-key": KEY}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adclone" / "brief-tiktok-price-shock.json"
OXHAN = presets.load("oxhan")
ENGINE_KEYS = ("KLING_ACCESS_KEY", "KLING_SECRET_KEY", "KLING_API_KEY", "HIGGSFIELD_API_KEY", "HIGGSFIELD_API_SECRET",
               "REPLICATE_API_TOKEN", "RUNPOD_API_KEY", "RUNPOD_WAN_ENDPOINT_ID", "MINIMAX_API_KEY",
               "ELEVENLABS_API_KEY", "ADCLONE_PAID_RENDER", "ADCLONE_CAP_USD", "RELAY_URL", "RAILYARD_RELAY_URL",
               "RELAY_API_KEY", "RELAY_KEY")


def _brief() -> CloneBrief:
    return CloneBrief.model_validate(json.loads(FIXTURE.read_text()))


def _plan(aspect: str = "9:16") -> dict:
    return rewrite.build_plan(_brief(), OXHAN, variation="a", options=CloneOptions(aspect=aspect))


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    assert film_models.FilmProject
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
    monkeypatch.setattr(adclone_router, "get_session", _session)
    for name in ENGINE_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(service.ENABLED_ENV, "1")
    monkeypatch.setenv(service.LLM_ENV, "0")
    with factory() as s:
        s.add(User(email="r@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    return factory


def _uid(db) -> str:
    with db() as s:
        return s.query(User).one().id


def _grant(db, amount: int) -> None:
    with db() as s:
        pc.grant(s, _uid(db), pc.KIND_AI_VIDEO, amount, "test_grant")
        s.commit()


def _balance(db) -> int:
    with db() as s:
        return pc.balance(s, _uid(db), pc.KIND_AI_VIDEO)


def _paid_env(monkeypatch):
    monkeypatch.setenv("KLING_ACCESS_KEY", "ak")
    monkeypatch.setenv("KLING_SECRET_KEY", "sk")
    monkeypatch.setenv(service.PAID_ENV, "1")


@pytest.fixture()
def api(db):
    app = FastAPI()
    app.include_router(adclone_router.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


# --------------------------------------------------------------------------- approve
def _approve(api, plan, credits, key="k-1"):
    return api.post("/api/v1/ad-clone/render/approve", headers={**H, "Idempotency-Key": key},
                    json={"plan": plan, "engine": "kling", "quoted_credits": credits})


def test_approve_holds_credits_creates_library_job_and_project(api, db, monkeypatch):
    _paid_env(monkeypatch)
    queued = []
    monkeypatch.setattr(render_job, "enqueue", lambda job_id: queued.append(job_id) or "celery-1")
    plan = _plan()
    q = render_job.quote(plan, "kling")
    _grant(db, q["ai_video_credits"] + 100)
    r = _approve(api, plan, q["ai_video_credits"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert queued == [data["job_id"]] and _balance(db) == 100
    with db() as s:
        job = s.get(Job, data["job_id"])
        assert job.kind == "ad_clone" and job.state == 4 and job.params["engine"] == "kling"
        project = s.get(film_models.FilmProject, data["project_id"])
        assert project.status == "rendering" and project.shot_count == len(plan["shots"])
        shots = s.query(film_models.FilmShot).filter_by(project_id=project.id).all()
        assert {x.shot_key for x in shots} == {x["id"] for x in plan["shots"]}
    again = _approve(api, plan, q["ai_video_credits"])
    assert again.json()["data"]["job_id"] == data["job_id"] and again.json()["data"]["replayed"]
    assert queued == [data["job_id"]] and _balance(db) == 100
    other = _approve(api, {**plan, "slug": "clone-other-a"}, q["ai_video_credits"])
    assert other.status_code == 409  # same key, different request
    status = api.get(f"/api/v1/ad-clone/render/{data['job_id']}", headers=H).json()["data"]
    assert status["stage"] == "queued" and status["quoted_usd"] == q["usd"]


def test_approve_refusals(api, db, monkeypatch):
    plan = _plan()
    monkeypatch.setattr(render_job, "enqueue", lambda job_id: "celery-1")
    assert api.post("/api/v1/ad-clone/render/approve", headers=H,
                    json={"plan": plan, "quoted_credits": 1}).status_code == 400  # no Idempotency-Key
    assert _approve(api, plan, 1).status_code == 403  # paid rendering switched off
    _paid_env(monkeypatch)
    q = render_job.quote(plan, "kling")
    assert _approve(api, plan, q["ai_video_credits"], key="poor").status_code == 402
    _grant(db, 5000)
    assert _approve(api, plan, q["ai_video_credits"] - 1, key="stale").status_code == 409
    monkeypatch.setenv(service.CAP_ENV, "1.00")
    assert _approve(api, plan, q["ai_video_credits"], key="cap").status_code == 409
    monkeypatch.delenv(service.CAP_ENV)
    bad = json.loads(json.dumps(plan))
    bad["stills"][1]["prompt"] += " with goggles"
    assert _approve(api, bad, q["ai_video_credits"], key="ip").status_code == 422
    r = api.post("/api/v1/ad-clone/render/approve", headers={**H, "Idempotency-Key": "rep"},
                 json={"plan": plan, "engine": "minimax_hailuo", "quoted_credits": 1})
    assert r.status_code == 409  # engine without keys on this server
    assert _balance(db) == 5000  # nothing held by any refusal


def test_enqueue_failure_gives_credits_back(api, db, monkeypatch):
    _paid_env(monkeypatch)

    def down(job_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr(render_job, "enqueue", down)
    plan = _plan()
    q = render_job.quote(plan, "kling")
    _grant(db, q["ai_video_credits"])
    r = _approve(api, plan, q["ai_video_credits"])
    assert r.status_code == 502 and _balance(db) == q["ai_video_credits"]
    with db() as s:
        job = s.query(Job).one()
        assert job.state == -1


# --------------------------------------------------------------------------- worker
def _png(size=(64, 96), colour=(120, 30, 40)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if not FFMPEG:
        pytest.skip("ffmpeg not installed")
    root = tmp_path_factory.mktemp("adclone-media")
    clip = root / "lips.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "10", "-i", "color=c=gray:s=180x320:r=30",
                    "-f", "lavfi", "-t", "10", "-i", "sine=frequency=220", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(clip)], check=True)
    line = root / "line.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "0.8", "-i", "sine=frequency=330",
                    str(line)], check=True)
    return {"clip": clip.read_bytes(), "line": str(line)}


class FakeKling:
    """Kling with a queue: each task needs ``polls`` status calls; optional transient / failed answers."""

    def __init__(self, polls=1, fail_first_i2v=False, transient=0, balance_after=None):
        self.polls, self.fail_first_i2v, self.transient, self.balance_after = polls, fail_first_i2v, transient, balance_after
        self.tasks, self.posts, self.n = {}, [], 0

    def __call__(self, method, url, headers, body):
        if method == "POST":
            if self.balance_after is not None and len(self.posts) >= self.balance_after:
                return 400, {"code": 1102, "message": "exhausted"}
            self.n += 1
            tid = f"t{self.n}"
            self.posts.append((url, body))
            failed = self.fail_first_i2v and self.n == 1
            self.tasks[tid] = {"left": self.polls, "failed": failed, "lip": url.endswith("lip-sync")}
            return 200, {"code": 0, "data": {"task_id": tid}}
        if self.transient:
            self.transient -= 1
            return 503, {}
        tid = url.rsplit("/", 1)[-1]
        t = self.tasks[tid]
        if t["failed"]:
            return 200, {"code": 0, "data": {"task_status": "failed", "task_status_msg": "busy"}}
        t["left"] -= 1
        if t["left"] > 0:
            return 200, {"code": 0, "data": {"task_status": "processing"}}
        return 200, {"code": 0, "data": {"task_status": "succeed", "task_result": {
            "videos": [{"id": f"vid-{tid}", "url": f"https://cdn.example/{tid}.mp4"}]}}}


def _deps(media, fake, store, scheduled, now=lambda: 1000.0):
    def voices(preset, plan, outdir):
        Path(outdir).mkdir(parents=True, exist_ok=True)
        out = {}
        for ln in plan["lines"]:
            p = Path(outdir) / f"{ln['id']}.mp3"
            shutil.copyfile(media["line"], p)
            out[ln["id"]] = str(p)
        return out

    def manifest(root):
        tags = ["hero", "oxhan"] + [f"s{i}" for i in range(8)]
        return [{"tag": t, "path": f"mj/{t}/x.png", "sha256": t} for t in tags]

    def upload(path, key, ctype):
        store[key] = Path(path).read_bytes()

    def engine(name, cap, spent):
        if name == "kling":
            return kling.KlingClient(access_key="a", secret_key="s", http=fake, cap_usd=cap, spent_usd=spent,
                                     sleep=lambda s: None, clock=lambda: 0.0)
        return engine_clients.client_for(name, cap_usd=cap, spent_usd=spent, env=ENGINE_ENV, http=fake)

    return render_tasks.Deps(
        engine=engine, public_url=lambda path, key, ctype: store.setdefault("_public", []).append(key)
        or f"https://pub.example/{key}",
        voices=voices, manifest=manifest, image=lambda ref, root: _png(), download=lambda url: media["clip"],
        upload=upload, fetch=lambda key: store[key], schedule=lambda job_id, s: scheduled.append(s), now=now)


ENGINE_ENV = {"REPLICATE_API_TOKEN": "r8_test", "HIGGSFIELD_API_KEY": "hid", "HIGGSFIELD_API_SECRET": "hsec",
              "HIGGSFIELD_LIPSYNC_ENDPOINT": "kling-video/lipsync/audio-to-video", "MINIMAX_API_KEY": "mm",
              "RUNPOD_API_KEY": "rp", "RUNPOD_WAN_ENDPOINT_ID": "ep123"}


def _approved_job(db, monkeypatch, plan, engine="kling"):
    _paid_env(monkeypatch)
    for k, v in ENGINE_ENV.items():
        monkeypatch.setenv(k, v)
    q = render_job.quote(plan, engine)
    _grant(db, q["ai_video_credits"])
    with db() as s:
        job = render_job.approve(s, _uid(db), plan=plan, engine=engine, quoted_credits=q["ai_video_credits"])
        s.commit()
        return job.id, q


def _run_until_done(job_id, deps, limit=30):
    for _ in range(limit):
        out = render_tasks.tick(job_id, deps)
        if out.get("stage") in ("finished", "failed") or "state" in out:
            return out
    raise AssertionError("render never finished")


@pytest.mark.parametrize("aspect,size", [("9:16", (180, 320)), ("16:9", (320, 180))])
def test_worker_renders_settles_and_saves_to_library_and_project(db, monkeypatch, media, aspect, size):
    monkeypatch.setitem(assemble.CANVAS, aspect, size)
    plan = _plan(aspect)
    job_id, q = _approved_job(db, monkeypatch, plan)
    fake, store, scheduled = FakeKling(polls=2), {}, []
    out = _run_until_done(job_id, _deps(media, fake, store, scheduled))
    assert out["stage"] == "finished", out
    assert scheduled and scheduled[:3] == [20.0, 40.0, 80.0]  # backoff between engine polls
    i2v = [b for u, b in fake.posts if u.endswith("image2video")]
    assert len(i2v) == len(plan["shots"]) and {b["aspect_ratio"] for b in i2v} == {aspect}
    assert len([u for u, _ in fake.posts if u.endswith("lip-sync")]) == len(plan["shots"])
    with db() as s:
        job = s.get(Job, job_id)
        assert job.state == 1 and job.result_key == f"jobs/{job_id}/adclone/final.mp4"
        project = s.get(film_models.FilmProject, job.params["project_id"])
        assert project.status == "exported" and project.final_key == job.result_key
        assert {r.status for r in s.query(film_models.FilmShot).filter_by(project_id=project.id)} == {"done"}
        spent = job.params["_spent_usd"]
    assert spent == pytest.approx(sum(r["usd"] for r in kling.KlingClient().dry_run_requests(plan)), abs=0.01)
    assert _balance(db) == q["ai_video_credits"] - pc.ai_video_credits_for_usd(spent)
    from app.domains.adclone.media import probe

    final = Path(f"/tmp/adclone-test-{job_id}.mp4")
    final.write_bytes(store[f"jobs/{job_id}/adclone/final.mp4"])
    pr = probe(str(final))
    final.unlink()
    assert (pr.width, pr.height) == size and pr.has_audio and pr.duration_s > 8
    assert render_tasks.tick(job_id, _deps(media, fake, store, scheduled)) == {"job_id": job_id, "state": 1}


def test_worker_retries_a_failed_task_once_and_rides_out_transient_errors(db, monkeypatch, media):
    monkeypatch.setitem(assemble.CANVAS, "9:16", (180, 320))
    plan = _plan()
    job_id, _ = _approved_job(db, monkeypatch, plan)
    fake = FakeKling(polls=1, fail_first_i2v=True, transient=3)
    out = _run_until_done(job_id, _deps(media, fake, {}, []))
    assert out["stage"] == "finished"
    i2v = [u for u, _ in fake.posts if u.endswith("image2video")]
    assert len(i2v) == len(plan["shots"]) + 1  # the failed task was submitted again, once


def test_worker_stops_on_balance_and_charges_only_what_was_spent(db, monkeypatch, media):
    plan = _plan()
    job_id, q = _approved_job(db, monkeypatch, plan)
    fake = FakeKling(polls=1, balance_after=2)
    out = _run_until_done(job_id, _deps(media, fake, {}, []))
    assert out["stage"] == "failed"
    with db() as s:
        job = s.get(Job, job_id)
        spent = job.params["_spent_usd"]
        assert job.state == -1 and spent > 0
        assert s.get(film_models.FilmProject, job.params["project_id"]).status == "failed"
    assert _balance(db) == q["ai_video_credits"] - pc.ai_video_credits_for_usd(spent)


def test_worker_without_imported_frames_refunds_everything(db, monkeypatch, media):
    plan = _plan()
    job_id, q = _approved_job(db, monkeypatch, plan)
    deps = _deps(media, FakeKling(), {}, [])
    deps.manifest = lambda root: []
    out = render_tasks.tick(job_id, deps)
    assert out["stage"] == "failed" and "Midjourney" in out["error"]
    assert _balance(db) == q["ai_video_credits"]


def test_worker_times_out_and_settles(db, monkeypatch, media):
    plan = _plan()
    job_id, q = _approved_job(db, monkeypatch, plan)
    clock = iter([1000.0, 1000.0] + [1000.0 + render_tasks.TIMEOUT_S + 5] * 10)
    deps = _deps(media, FakeKling(polls=99), {}, [], now=lambda: next(clock))
    first = render_tasks.tick(job_id, deps)
    assert first["stage"] == "shots"
    assert render_tasks.tick(job_id, deps)["stage"] == "failed"


# --------------------------------------------------------------------------- the cut (both aspects)
def test_timeline_follows_the_edit_list():
    plan = _plan()
    lens = {ln["id"]: 1.0 for ln in plan["lines"]}
    segs = assemble.timeline(plan, lens)
    assert len(segs) == len(plan["edit"]) + 1 and segs[-1]["type"] == "card"
    first = segs[0]
    assert first["type"] == "clip" and first["start"] == pytest.approx(0.25 - 0.1)
    assert assemble.canvas("16:9") == (1920, 1080)
    with pytest.raises(assemble.AssembleError):
        assemble.canvas("1:1")


def test_sixteen_nine_plan_is_a_valid_episode_plan():
    from app.domains.adclone import planschema

    plan = _plan("16:9")
    assert plan["canvas"] == {"w": 1920, "h": 1080} and plan["edit"][-1]["cap_y"] == rewrite.CAPTION_TOP["16:9"]
    assert planschema.validate(plan, cta_text=OXHAN["cta"]["text"]) == []
    assert all(s["ar"] == "16:9" for s in plan["stills"])


# --------------------------------------------------------------------------- Relay writer
RELAY = {"RELAY_URL": "https://relay.example", "RELAY_API_KEY": "rk"}


def test_relay_writer_not_configured_falls_back_and_says_so(monkeypatch):
    assert relay_writer.relay_llm({}) is None
    monkeypatch.setenv(service.LLM_ENV, "1")
    assert service.default_llm() is None
    plan = rewrite.build_plan(_brief(), OXHAN, variation="a", options=CloneOptions(language="tr"))
    assert plan["clone"]["writer"] == "bank"
    assert "Relay is not configured" in plan["clone"]["writer_note"] and "'tr'" in plan["clone"]["writer_note"]

    brief = _brief().model_copy(update={"notes": []})
    monkeypatch.setattr(service, "heuristic_brief", lambda obs: brief)
    out = service.analyze_link("https://www.tiktok.com/@a/video/1", downloader=lambda u, s: s + ".mp4",
                               observer=lambda *a, **k: None, llm=None)
    assert any("Relay is not configured" in n for n in out.notes)


def test_relay_writer_routes_through_relay_and_writes_turkish():
    calls = []
    slots, _ = rewrite.story_slots(_brief())
    turkish = ["Simit yirmi beş lira oldu.", "Çay yine zamlandı.", "Bakkal fiyatları kurşun kalemle yazıyor.",
               "Geçici dedi abi.", "Geçen yıl da öyle demişti.", "Ben de hiç zamlanmayan bir şey aldım.",
               "Kırk parça. Numaralı."]

    def chat(*, prompt, model, relay_provider, temperature, env):
        calls.append((model, relay_provider, env.get("RELAY_URL"), prompt))
        return json.dumps({"lines": [{"slot": s.index, "speaker": "O" if i == 4 else "H", "text": turkish[i % 7]}
                                     for i, s in enumerate(slots)]}, ensure_ascii=False)

    llm = relay_writer.relay_llm(RELAY, chat=chat)
    assert llm is not None
    plan = rewrite.build_plan(_brief(), OXHAN, variation="b", options=CloneOptions(language="tr"), llm=llm)
    assert plan["clone"]["writer"] == "llm" and plan["clone"]["writer_note"] == ""
    assert plan["lines"][0]["text"] == "Simit yirmi beş lira oldu." and plan["language"] == "tr"
    model, provider, url, prompt = calls[0]
    assert provider == "anthropic" and model == relay_writer.DEFAULT_MODEL and url == "https://relay.example"
    assert "Language: tr" in prompt


def test_relay_writer_bad_answer_falls_back_with_note():
    llm = relay_writer.relay_llm(RELAY, chat=lambda **kw: "sorry, no")
    plan = rewrite.build_plan(_brief(), OXHAN, variation="a", options=CloneOptions(), llm=llm)
    assert plan["clone"]["writer"] == "bank" and "unusable" in plan["clone"]["writer_note"]


# --------------------------------------------------------------------------- dependencies in the images
ROOT = Path(__file__).resolve().parents[2]


def test_adclone_dependencies_are_pinned_and_installed_in_both_images():
    import re
    import tomllib

    reqs = {}
    for line in (ROOT / "requirements-adclone.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            name, _, rest = line.partition("==")
            reqs[name.strip().lower()] = rest.strip()
    assert set(reqs) == {"yt-dlp", "scenedetect", "ocrmac"}
    extra = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]["adclone"]
    pinned = {re.split(r"==", e)[0].strip().lower(): re.split(r"==", e)[1].strip() for e in extra}
    assert {k: v.split(";")[0].strip() for k, v in pinned.items()} == {k: v.split(";")[0].strip() for k, v in reqs.items()}
    assert "darwin" in reqs["ocrmac"]  # macOS only; Linux images read captions with RapidOCR
    assert re.search(r"^rapidocr-onnxruntime==", (ROOT / "requirements.txt").read_text(), re.M)
    for dockerfile in ("apps/api/Dockerfile", "apps/api/Dockerfile.generation"):
        assert "requirements-adclone.txt" in (ROOT / dockerfile).read_text(), dockerfile


# --------------------------------------------------------------------------- OCR on Linux workers
def test_ocr_falls_back_to_rapidocr_when_vision_is_absent(monkeypatch, tmp_path):
    import builtins
    import sys
    import types

    real_import = builtins.__import__

    def no_ocrmac(name, *args, **kwargs):
        if name in ("ocrmac", "pytesseract"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    class FakeRapid:
        def __call__(self, path):
            return ([[[[0, 400], [100, 400], [100, 440], [0, 440]], "eggs are $12", 0.93]], 0.1)

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=FakeRapid))
    monkeypatch.setattr(builtins, "__import__", no_ocrmac)
    img = tmp_path / "f.png"
    img.write_bytes(_png((100, 500)))
    lines = vision.ocr_image(str(img))
    assert lines and lines[0].text == "eggs are $12" and lines[0].y_center == pytest.approx(0.84, abs=0.01)


# --------------------------------------------------------------------------- the other engines
class FakeEngines:
    """Replicate, Higgsfield, MiniMax and RunPod APIs (each task finishes on its second poll)."""

    def __init__(self):
        self.posts, self.polls, self.headers = [], {}, []

    def _done(self, tid):
        self.polls[tid] = self.polls.get(tid, 0) + 1
        return self.polls[tid] >= 2

    def __call__(self, method, url, headers, body):
        self.headers.append(headers)
        if method == "POST":
            self.posts.append((url, body))
            n = len(self.posts)
            if "replicate.com" in url:
                return 201, {"id": f"pred{n}", "status": "starting"}
            if "higgsfield.ai" in url:
                return 200, {"request_id": f"hf{n}", "status": "queued"}
            if "minimax.io" in url:
                return 200, {"task_id": f"mm{n}", "base_resp": {"status_code": 0}}
            if "runpod.ai" in url:
                return 200, {"id": f"rp{n}", "status": "IN_QUEUE"}
        tid = url.rstrip("/").split("/")[-1].split("=")[-1]
        if "replicate.com" in url:
            done = self._done(tid)
            return 200, {"status": "succeeded" if done else "processing", "output": f"https://r.example/{tid}.mp4"}
        if "higgsfield.ai" in url:
            tid = url.split("/requests/")[1].split("/")[0]
            done = self._done(tid)
            return 200, {"status": "completed" if done else "in_progress", "video": {"url": f"https://h.example/{tid}.mp4"}}
        if "minimax.io" in url and "files/retrieve" in url:
            return 200, {"file": {"download_url": "https://m.example/v.mp4"}, "base_resp": {"status_code": 0}}
        if "minimax.io" in url:
            done = self._done(tid)
            return 200, {"status": "Success" if done else "Processing", "file_id": "f1", "base_resp": {"status_code": 0}}
        if "runpod.ai" in url:
            done = self._done(tid)
            return 200, {"status": "COMPLETED" if done else "IN_PROGRESS", "executionTime": 90_000,
                         "output": {"video_url": f"https://rp.example/{tid}.mp4"}}
        return 404, {}


@pytest.mark.parametrize("engine,lipsync", [("replicate", "native"), ("higgsfield_kling", "separate"),
                                            ("minimax_hailuo", "none"), ("runpod_wan", "native")])
def test_every_engine_renders_through_the_same_approved_flow(db, monkeypatch, media, engine, lipsync):
    monkeypatch.setitem(assemble.CANVAS, "9:16", (180, 320))
    plan = _plan()
    job_id, q = _approved_job(db, monkeypatch, plan, engine)
    fake, store = FakeEngines(), {}
    out = _run_until_done(job_id, _deps(media, fake, store, []))
    assert out["stage"] == "finished", out
    n = len(plan["shots"])
    posts = len(fake.posts)
    assert posts == (2 * n if lipsync == "separate" else n)
    first_body = fake.posts[0][1]
    if engine == "replicate":
        assert first_body["input"]["reference_audios"][0].startswith("data:audio/wav;base64,")
        assert fake.headers[0]["Authorization"] == "Bearer r8_test"
    if engine == "higgsfield_kling":
        assert first_body["image_url"].startswith("https://pub.example/jobs/")
        lips = [b for u, b in fake.posts if u.endswith("lipsync/audio-to-video")]
        assert len(lips) == n and lips[0]["audio_url"].startswith("https://pub.example/")
        assert lips[0]["video_url"].startswith("https://h.example/")
        assert fake.headers[0]["Authorization"] == "Key hid:hsec"
    if engine == "minimax_hailuo":
        assert first_body["first_frame_image"].startswith("data:image/png;base64,") and first_body["duration"] in (6, 10)
    if engine == "runpod_wan":
        assert first_body["input"]["task"] == "infinitetalk" and first_body["input"]["audio_base64"]
    with db() as s:
        job = s.get(Job, job_id)
        assert job.state == 1 and job.params["engine"] == engine
        spent = job.params["_spent_usd"]
        assert {st["lipsync"] for st in job.params["_shots"].values()} == {lipsync}
    if engine == "runpod_wan":
        assert spent == pytest.approx(n * 90 / 3600 * 1.99, abs=0.01)  # billed by measured GPU time
    assert 0 < spent <= q["usd"] + 1e-6
    assert _balance(db) == q["ai_video_credits"] - pc.ai_video_credits_for_usd(spent)


def test_engine_errors_are_classified():
    rep = engine_clients.ReplicateSeedance(token="t", http=lambda *a: (402, {}))
    with pytest.raises(engine_clients.EngineError) as exc:
        rep.image_to_video(image="eA==", prompt="p", seconds=5)
    assert exc.value.stop and rep.spent_usd == 0
    mm = engine_clients.MinimaxHailuo(api_key="k", http=lambda *a: (200, {"base_resp": {"status_code": 1002}}))
    with pytest.raises(engine_clients.EngineError) as exc:
        mm.image_to_video(image="eA==", prompt="p", seconds=5)
    assert exc.value.transient
    hf = engine_clients.HiggsfieldKling(key_id="a", key_secret="b")
    assert hf.lipsync == "none"
    with pytest.raises(engine_clients.EngineError):
        hf.image_to_video(image="eA==", prompt="p", seconds=5)  # no public URL
    rp = engine_clients.RunpodWan(api_key="k", endpoint_id="e", cap_usd=0.01)
    with pytest.raises(engine_clients.EngineError) as exc:
        rp.image_to_video(image="eA==", prompt="p", seconds=5, audio_b64="eA==")
    assert exc.value.stop  # cap checked before the call
    with pytest.raises(engine_clients.EngineError):
        engine_clients.client_for("minimax_hailuo", cap_usd=1, spent_usd=0, env={})
    assert len(engine_clients.ReplicateSeedance(token="t").dry_run_requests(_plan())) == len(_plan()["shots"])


# --------------------------------------------------------------------------- captions
def test_caption_style_follows_the_brief():
    plan = _plan()
    assert plan["captions"] == {"style": "game", "position": "bottom", "case": "lower", "enabled": True,
                                "max_chars": 26, "source_present": True}
    wide = _plan("16:9")["captions"]
    assert wide["max_chars"] == 44
    assert captions.style_from_brief({"position": "top", "case": "upper"}, "9:16")["position"] == "top"
    assert captions.apply_case("Simit Is Up", "lower") == "simit is up"
    assert captions.wrap("one two three four five six", 9) == ["one two", "three", "four five", "six"]


def test_caption_png_sits_in_the_requested_band(tmp_path):
    from PIL import Image

    png = captions.render_png("Simit is twenty-five lira now.", str(tmp_path / "c.png"), (360, 640),
                              {"position": "bottom", "case": "lower", "max_chars": 26})
    alpha = Image.open(png).split()[-1]
    box = alpha.getbbox()
    assert box is not None and box[1] > 640 * 0.6 and box[3] < 640 * 0.95
    top = captions.render_png("hi there", str(tmp_path / "t.png"), (360, 640), {"position": "top"})
    assert Image.open(top).split()[-1].getbbox()[3] < 640 * 0.3


def test_caption_windows_follow_the_spoken_lines():
    plan = _plan()
    lens = {ln["id"]: 1.0 for ln in plan["lines"]}
    segs = assemble.timeline(plan, lens)
    starts = {s["id"]: assemble.onsets(s, lens) for s in plan["shots"]}
    clip = next(s for s in segs if s["type"] == "clip")
    (lid, t0, t1), = captions.windows(clip, lens, starts, 0.3)
    assert lid == clip["lines"][0] and t1 - t0 == pytest.approx(1.0) and t0 == pytest.approx(0.1)
    still = next(s for s in segs if s["type"] == "still" and s["lines"])
    assert captions.windows(still, lens, starts, 0.3)[0][1:] == (0.3, 1.3)
    assert captions.windows(segs[-1], lens, starts, 0.3) == []


def test_burned_in_caption_is_visible_only_while_the_line_is_heard(tmp_path, media):
    from PIL import Image

    size = (180, 320)
    still = tmp_path / "s.png"
    still.write_bytes(_png((90, 160), (20, 20, 20)))
    cap = captions.render_png("simit is up", str(tmp_path / "cap.png"), size, {"position": "bottom"})
    out = tmp_path / "seg.mp4"
    assemble._run(assemble.still_command(str(still), str(out), length=2.0, push=1.0, size=size,
                                         audio=media["line"], captions=[(cap, 0.5, 1.2)]))

    def band(at):
        frame = tmp_path / f"f{at}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(out), "-frames:v", "1", str(frame)],
                       check=True)
        img = Image.open(frame).convert("L").crop((0, int(320 * 0.7), 180, int(320 * 0.9)))
        return max(img.getdata())

    assert band(0.8) > 200 and band(0.2) < 80 and band(1.6) < 80
