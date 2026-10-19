"""Ad Clone paid render worker (generation queue). One task, re-scheduled until the engine is done.

Each tick advances a small, persisted state machine, so a retried or duplicated tick never pays
twice and a long engine queue never blocks a worker. The approved engine (Kling, Replicate Seedance,
Higgsfield-Kling, MiniMax Hailuo or RunPod Wan + InfiniteTalk) is driven through one interface
(:mod:`engine_clients`):

  voices  -> one ElevenLabs take per line with the character's locked voice id (stored in R2)
  frames  -> Midjourney imports: the first frame of every talk shot + the image of every still
  shots   -> per shot: image-to-video from the first frame; the lips follow our shot audio either in
             the same task (native: Seedance, InfiniteTalk) or a second lip-sync task (Kling, Higgsfield);
             new -> i2v -> [lipsync] -> done; one re-try per shot; transient poll errors back off
  assemble-> the cut in the plan's aspect (assemble.render), uploaded; job complete (Library),
             film project exported, AI-video credits settled to what the engine actually cost.

Any failure settles the credits to the spend so far (all back when nothing was spent) and marks
the job and project failed.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.workers.celery_app import celery_app

from . import assemble, elevenlabs, midjourney, presets, service
from .engine_clients import EngineError, client_for
from .kling import backoff_s
from .render_job import JOB_KIND, STATE_COMPLETE, STATE_FAILED

TASK = "app.domains.adclone.render_tasks.run_adclone_render_task"
TICK_BASE_S = 20.0
MAX_TRANSIENT = 6
MAX_TRIES = 2
TIMEOUT_S = 45 * 60


def _r2_upload(path: str, key: str, content_type: str) -> None:
    from app.domains.film.story8_tasks import r2_upload

    r2_upload(path, key, content_type)


def _r2_fetch(key: str) -> bytes:
    from app.domains.film.story8_tasks import r2_fetch

    return r2_fetch(key)


def _download(url: str) -> bytes:
    from app.domains.film.story8_tasks import _download as dl

    return dl(url, 120.0)


def _library_root(preset: Mapping[str, Any]) -> str:
    return os.getenv("ADCLONE_MJ_LIBRARY") or presets.project_root(dict(preset))


def _image_bytes(ref: str, root: str) -> bytes:
    """An imported image: a library path (mj/...) or a UI upload key (uploads/...)."""
    if ref.startswith("uploads/"):
        return _r2_fetch(ref)
    path = os.path.realpath(os.path.join(root, ref))
    if not path.startswith(os.path.realpath(root) + os.sep):
        raise ValueError("image outside the library")
    with open(path, "rb") as fh:
        return fh.read()


def _voices(preset: dict, plan: Mapping[str, Any], outdir: str) -> dict[str, str]:
    return elevenlabs.line_audio(elevenlabs.ElevenLabs.from_env(), preset, plan, outdir)


def _line_seconds(path: str) -> float:
    from .media import duration_s

    return duration_s(path)


def _new_engine(engine: str, cap_usd: float, spent_usd: float) -> Any:
    return client_for(engine, cap_usd=cap_usd, spent_usd=spent_usd)


def _public_url(path: str, key: str, content_type: str) -> str:
    """Upload a file and return a short-lived presigned URL (engines that only take URLs)."""
    from app.domains.gallery.service import media_url

    _r2_upload(path, key, content_type)
    return media_url(key)


def _schedule(job_id: str, countdown: float) -> None:
    run_adclone_render_task.apply_async(args=[job_id], countdown=int(countdown), queue="generation")


@dataclass
class Deps:
    engine: Callable[[str, float, float], Any] = _new_engine
    public_url: Callable[[str, str, str], str] = _public_url
    voices: Callable[[dict, Mapping[str, Any], str], dict[str, str]] = _voices
    manifest: Callable[[str], list[dict]] = midjourney.load_manifest
    image: Callable[[str, str], bytes] = _image_bytes
    download: Callable[[str], bytes] = _download
    upload: Callable[[str, str, str], None] = _r2_upload
    fetch: Callable[[str], bytes] = _r2_fetch
    schedule: Callable[[str, float], None] = _schedule
    line_seconds: Callable[[str], float] = _line_seconds
    now: Callable[[], float] = field(default=time.time)


def _session():
    from app.models.db.base import get_session

    return get_session()


def _save(job: Any, **changes: Any) -> None:
    job.params = {**dict(job.params or {}), **changes}


def _project(session: Any, job: Any):
    from app.models.db.film import FilmProject

    pid = (job.params or {}).get("project_id")
    return session.get(FilmProject, pid) if pid else None


def _shot_rows(session: Any, job: Any) -> dict[str, Any]:
    from app.models.db.film import FilmShot

    pid = (job.params or {}).get("project_id")
    if not pid:
        return {}
    return {r.shot_key: r for r in session.query(FilmShot).filter(FilmShot.project_id == pid).all()}


def _settle(job_id: str, spent_usd: float) -> int:
    from app.services.billing.premium_credits import settle_ai_video_once

    return settle_ai_video_once(job_id, spent_usd)


def _fail(job_id: str, error: str) -> None:
    try:
        with _session() as session:
            from app.models.db.models import Job

            job = session.get(Job, job_id)
            if job is None or job.state in (STATE_COMPLETE, STATE_FAILED):
                return
            spent = float((job.params or {}).get("_spent_usd") or 0.0)
            job.state, job.error, job.failed_stage = STATE_FAILED, error[:300], "ad_clone"
            _save(job, _stage="failed", _error=error[:300])
            project = _project(session, job)
            if project is not None:
                project.status = "failed"
            for row in _shot_rows(session, job).values():
                if row.status != "done":
                    row.status = "failed"
        returned = _settle(job_id, spent)
        logger.warning(f"adclone {job_id} failed ({error[:120]}); spent ${spent:.2f}, returned {returned} credits")
    except Exception as exc:  # noqa: BLE001 - the failure path never raises
        logger.error(f"adclone {job_id}: failure handling did not complete: {exc}")


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #
def _stage_voices(job: Any, plan: Mapping[str, Any], preset: dict, work: str, deps: Deps) -> None:
    files = deps.voices(preset, plan, os.path.join(work, "vo"))
    keys, lens = {}, {}
    for lid, path in files.items():
        key = f"jobs/{job.id}/adclone/vo/{lid}{os.path.splitext(path)[1] or '.mp3'}"
        deps.upload(path, key, "audio/mpeg")
        keys[lid], lens[lid] = key, round(float(deps.line_seconds(path)), 3)
    _save(job, _vo=keys, _line_len=lens, _stage="frames")


def _stage_frames(job: Any, plan: Mapping[str, Any], preset: dict, deps: Deps) -> None:
    manifest = deps.manifest(_library_root(preset))
    firsts = midjourney.first_frames(plan, manifest)
    latest = {e["tag"]: e.get("path") or e.get("key") for e in manifest}
    stills = {g["still"]: latest.get(g["still"]) for g in plan.get("edit") or [] if "still" in g}
    missing = [f"shot {k}" for k, v in firsts.items() if not v] + [f"still {k}" for k, v in stills.items() if not v]
    if missing:
        raise ValueError("import Midjourney images first for: " + ", ".join(missing))
    _save(job, _frames=firsts, _stills=stills, _stage="shots", _shots_started=deps.now())


def _shot_audio_file(job: Any, shot: Mapping[str, Any], work: str, deps: Deps) -> str:
    """The shot's audio (its lines on the lead and gaps): what the lips follow and what the cut plays."""
    out = os.path.join(work, f"{shot['id']}.wav")
    if os.path.exists(out):
        return out
    vo = (job.params or {})["_vo"]
    files = []
    for lid in shot["lines"]:
        path = os.path.join(work, f"{lid}.mp3")
        with open(path, "wb") as fh:
            fh.write(deps.fetch(vo[lid]))
        files.append(path)
    return service.shot_audio(files, out, lead_s=float(shot.get("lead", 0.25)), gap_s=float(shot.get("gap", 0.3)))


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _submit_i2v(job: Any, shot: Mapping[str, Any], client: Any, work: str, deps: Deps, root: str) -> str:
    from .engine_clients import b64

    frame = deps.image((job.params or {})["_frames"][shot["id"]], root)
    kwargs: dict[str, Any] = {}
    if client.lipsync == "native":
        kwargs["audio_b64"] = b64(_read(_shot_audio_file(job, shot, work, deps)))
    if client.needs_url:
        path = os.path.join(work, f"{shot['id']}-first.png")
        with open(path, "wb") as fh:
            fh.write(frame)
        kwargs["image_url"] = deps.public_url(path, f"jobs/{job.id}/adclone/frames/{shot['id']}.png", "image/png")
    return client.image_to_video(image=b64(frame), prompt=shot["prompt"], seconds=float(shot["dur"]),
                                 aspect_ratio=(job.params or {}).get("aspect", "9:16"), **kwargs)


def _submit_lipsync(job: Any, shot: Mapping[str, Any], video: Mapping[str, Any], client: Any, work: str,
                    deps: Deps) -> str:
    from .engine_clients import b64

    audio = _shot_audio_file(job, shot, work, deps)
    audio_url = deps.public_url(audio, f"jobs/{job.id}/adclone/shot-audio/{shot['id']}.wav", "audio/wav") \
        if client.needs_url else None
    return client.lip_sync(video_id=str(video.get("id")), audio_b64=b64(_read(audio)),
                           seconds=5 if float(shot["dur"]) <= 5 else 10, video_url=video.get("url"),
                           audio_url=audio_url)


def _advance_shot(job: Any, shot: Mapping[str, Any], st: dict, client: Any, work: str, deps: Deps,
                  root: str) -> dict:
    """One step of one shot's state machine; returns the new state (input untouched)."""
    st = dict(st or {"stage": "new", "tries": 0, "errors": 0})
    try:
        if st["stage"] == "new":
            st["task"] = _submit_i2v(job, shot, client, work, deps, root)
            st.update(stage="i2v", tries=st["tries"] + 1, lipsync=client.lipsync)
        elif st["stage"] == "i2v":
            state, video = client.status("i2v", st["task"])
            if state == "done":
                if client.lipsync == "separate":
                    st["video_id"] = str((video or {}).get("id"))
                    st["task"] = _submit_lipsync(job, shot, video or {}, client, work, deps)
                    st["stage"] = "lipsync"
                else:
                    st.update(stage="done", url=(video or {}).get("url"))
        elif st["stage"] == "lipsync":
            state, video = client.status("lipsync", st["task"])
            if state == "done":
                st.update(stage="done", url=(video or {}).get("url"))
        st["errors"] = 0
    except EngineError as exc:
        if exc.stop:
            raise
        if exc.transient:
            st["errors"] = st.get("errors", 0) + 1
            if st["errors"] > MAX_TRANSIENT:
                raise EngineError(f"shot {shot['id']}: the engine kept failing ({exc})") from exc
        elif st["tries"] < MAX_TRIES:
            st.update(stage="new", errors=0, last_error=str(exc)[:200])  # a failed task is re-tried once
        else:
            raise EngineError(f"shot {shot['id']} failed twice: {exc}") from exc
    return st


def _stage_shots(session: Any, job: Any, plan: Mapping[str, Any], preset: dict, work: str, deps: Deps) -> bool:
    params = dict(job.params or {})
    client = deps.engine(str(params.get("engine") or "kling"), float(params["cap_usd"]),
                         float(params.get("_spent_usd") or 0.0))
    states = dict(params.get("_shots") or {})
    rows = _shot_rows(session, job)
    root = _library_root(preset)
    try:
        for shot in plan["shots"]:
            if (states.get(shot["id"]) or {}).get("stage") == "done":
                continue
            states[shot["id"]] = _advance_shot(job, shot, states.get(shot["id"]), client, work, deps, root)
            row = rows.get(shot["id"])
            if row is not None:
                row.status = "done" if states[shot["id"]]["stage"] == "done" else "rendering"
    finally:
        _save(job, _shots=states, _spent_usd=round(float(client.spent_usd), 4))
    return all(states.get(s["id"], {}).get("stage") == "done" for s in plan["shots"])


def _stage_assemble(session: Any, job: Any, plan: Mapping[str, Any], preset: dict, work: str, deps: Deps) -> None:
    params = dict(job.params or {})
    clips, stills, audio = {}, {}, {}
    shot_audio = {}
    shots = {s["id"]: s for s in plan["shots"]}
    for sid, st in params["_shots"].items():
        path = os.path.join(work, f"{sid}.mp4")
        with open(path, "wb") as fh:
            fh.write(deps.download(st["url"]))
        clips[sid] = path
        shot_audio[sid] = _shot_audio_file(job, shots[sid], work, deps)  # the cut always plays our own voice
    root = _library_root(preset)
    for still_id, ref in (params.get("_stills") or {}).items():
        path = os.path.join(work, f"{still_id}{os.path.splitext(ref)[1] or '.png'}")
        with open(path, "wb") as fh:
            fh.write(deps.image(ref, root))
        stills[still_id] = path
    for lid, key in params["_vo"].items():
        path = os.path.join(work, f"line-{lid}.mp3")
        with open(path, "wb") as fh:
            fh.write(deps.fetch(key))
        audio[lid] = path
    final = os.path.join(work, "final.mp4")
    assemble.render(plan, line_len=params["_line_len"], clips=clips, stills=stills, line_audio=audio,
                    card_text=preset["cta"]["card"], workdir=os.path.join(work, "cut"), out=final,
                    shot_audio=shot_audio)
    poster = os.path.join(work, "poster.jpg")
    assemble._run([assemble._ffmpeg(), "-y", "-v", "error", "-ss", "0.5", "-i", final, "-frames:v", "1", poster])
    result_key, poster_key = f"jobs/{job.id}/adclone/final.mp4", f"jobs/{job.id}/adclone/poster.jpg"
    deps.upload(final, result_key, "video/mp4")
    deps.upload(poster, poster_key, "image/jpeg")
    job.result_key, job.preview_key, job.poster_key = result_key, result_key, poster_key
    job.state, job.progress = STATE_COMPLETE, 100
    _save(job, _stage="finished", _finished_at=datetime.now(timezone.utc).isoformat())
    project = _project(session, job)
    if project is not None:
        project.status, project.export_state, project.final_key = "exported", "done", result_key
        project.exported_at = datetime.now(timezone.utc)


def _advance(session: Any, job: Any, work: str, deps: Deps) -> dict[str, Any] | None:
    """Run the stages from where the job stopped; a dict = re-scheduled (still rendering), None = finished."""
    plan = dict(job.params["plan"])
    preset = presets.load(str((plan.get("clone") or {}).get("preset") or "oxhan"))
    stage = (job.params or {}).get("_stage", "queued")
    if stage in ("queued", "voices"):
        _save(job, _stage="voices")
        _stage_voices(job, plan, preset, work, deps)
        stage = "frames"
    if stage == "frames":
        _stage_frames(job, plan, preset, deps)
        session.commit()
        stage = "shots"
    if stage == "shots":
        started = float((job.params or {}).get("_shots_started") or deps.now())
        if deps.now() - started > TIMEOUT_S:
            raise TimeoutError("the engine did not finish within 45 minutes")
        if not _stage_shots(session, job, plan, preset, work, deps):
            ticks = int((job.params or {}).get("_ticks") or 0) + 1
            _save(job, _ticks=ticks)
            session.commit()
            deps.schedule(job.id, backoff_s(min(ticks - 1, 3), TICK_BASE_S))
            return {"job_id": job.id, "stage": "shots", "tick": ticks}
        _save(job, _stage="assemble")
        session.commit()
    _stage_assemble(session, job, plan, preset, work, deps)
    return None


def tick(job_id: str, deps: Deps | None = None) -> dict[str, Any]:
    from app.models.db.models import Job

    deps = deps or Deps()
    try:
        with tempfile.TemporaryDirectory(prefix="adclone-") as work, _session() as session:
            job = session.get(Job, job_id)
            if job is None or job.kind != JOB_KIND:
                raise LookupError(f"ad clone job {job_id} not found")
            if job.state in (STATE_COMPLETE, STATE_FAILED):
                return {"job_id": job_id, "state": job.state}
            try:
                waiting = _advance(session, job, work, deps)
            except Exception:
                session.commit()  # keep shot states and the spend so far, then settle in _fail
                raise
            if waiting is not None:
                return waiting
            spent = float((job.params or {}).get("_spent_usd") or 0.0)
        returned = _settle(job_id, spent)
        return {"job_id": job_id, "stage": "finished", "spent_usd": spent, "returned_credits": returned}
    except Exception as exc:  # noqa: BLE001 - a failed render settles what it held
        logger.error(f"adclone {job_id} failed: {exc}")
        _fail(job_id, str(exc) or type(exc).__name__)
        return {"job_id": job_id, "stage": "failed", "error": str(exc)[:200]}


@celery_app.task(name=TASK, soft_time_limit=900, time_limit=960)
def run_adclone_render_task(job_id: str) -> dict[str, Any]:
    return tick(job_id)


__all__ = ["Deps", "TASK", "run_adclone_render_task", "tick"]
