"""Apps shelf worker (MH8): runs one ``app_run`` job; a failure refunds what it held, once."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

from app.workers.celery_app import celery_app

from . import catalog, runners, service

RUN_TASK = "app.domains.apps_shelf.tasks.run_app_task"
SCENE_TASK = "app.domains.apps_shelf.tasks.run_scene_task"
SCENE_CHECK_TASK = "app.domains.apps_shelf.tasks.check_scene_task"


def _fetch(key: str) -> bytes:
    from app.domains.characters.hub import fetch_bytes

    return fetch_bytes(key)


def _upload(path: str, key: str, content_type: str) -> None:
    from app.platform.storage.r2 import get_r2_client

    get_r2_client().upload_file(path, key, content_type=content_type)


def _signed(key: str) -> str:
    from app.domains.gallery.service import media_url

    return media_url(key)


def _music(music_id: str) -> str:
    from app.services.music import get_music_path

    path = get_music_path(music_id)
    if not path:
        raise runners.AppRunError("that track is no longer in the library")
    return path


@dataclass
class Deps:
    fetch: Callable[[str], bytes] = _fetch
    upload: Callable[[str, str, str], None] = _upload
    signed_url: Callable[[str], str] = _signed
    edit_image: Callable[[str, str], bytes] = runners.edit_image
    remove_background: Callable[[bytes], bytes] = runners.remove_background
    music_path: Callable[[str], str] = _music


def _write(work: str, name: str, data: bytes) -> str:
    path = os.path.join(work, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def execute(job: Any, work: str, deps: Deps) -> tuple[list[str], dict[str, Any] | None]:
    """Run the app; returns (uploaded output keys, an inline result for score-type apps)."""
    params = dict(job.params or {})
    app = catalog.get(params["app_id"])
    if app is None:
        raise runners.AppRunError("this app was removed")
    inputs = dict(params.get("inputs") or {})
    prefix = f"jobs/{job.id}/apps/{app.id}"
    keys: list[str] = []
    if app.runner == "image_edit":
        image_url = deps.signed_url(inputs["image_key"])
        for n, prompt in enumerate(runners.edit_prompts(app.edit, inputs.get("text", "")), start=1):
            path = _write(work, f"out-{n}.png", deps.edit_image(prompt, image_url))
            key = f"{prefix}/out-{n}.png"
            deps.upload(path, key, "image/png")
            keys.append(key)
        return keys, None
    if app.local == "remove_bg":
        path = _write(work, "cutout.png", deps.remove_background(deps.fetch(inputs["image_key"])))
        deps.upload(path, f"{prefix}/cutout.png", "image/png")
        return [f"{prefix}/cutout.png"], None
    if app.local == "transition":
        first = _write(work, "a.img", deps.fetch(inputs["image_key"]))
        second = _write(work, "b.img", deps.fetch(inputs["image_key_2"]))
        out = os.path.join(work, "transition.mp4")
        runners.run(runners.transition_command(first, second, out))
        deps.upload(out, f"{prefix}/transition.mp4", "video/mp4")
        return [f"{prefix}/transition.mp4"], None
    if app.local == "beat_cut":
        clip = _write(work, "clip.mp4", deps.fetch(inputs["video_key"]))
        music = deps.music_path(inputs["music_id"])
        beats = runners.detect_beats(runners.decode_audio(music, seconds=runners.BEAT_CUT_MAX_S + 2))
        segments = runners.plan_beat_cut(runners.probe_seconds(clip), beats)
        out = os.path.join(work, "beat-cut.mp4")
        runners.run(runners.beat_cut_command(clip, music, segments, out))
        deps.upload(out, f"{prefix}/beat-cut.mp4", "video/mp4")
        return [f"{prefix}/beat-cut.mp4"], {"cuts": len(segments) - 1, "beats": len(beats)}
    if app.local == "hook_score":
        clip = _write(work, "clip.mp4", deps.fetch(inputs["video_key"]))
        return [], runners.score_hook(runners.hook_signals(clip), inputs.get("text", ""))
    raise runners.AppRunError("this app has no runner")


def run(job_id: str, deps: Deps | None = None) -> dict[str, Any]:
    from app.models.db.base import get_session
    from app.models.db.models import Job

    deps = deps or Deps()
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None or job.kind != service.JOB_KIND:
            return {"job_id": job_id, "state": None}
        if job.state in (service.TASK_STATE_COMPLETE, service.TASK_STATE_FAILED):
            return {"job_id": job_id, "state": job.state}
        try:
            with tempfile.TemporaryDirectory(prefix="apps-") as work:
                keys, result = execute(job, work, deps)
            job.result_key = keys[0] if keys else ""
            job.state, job.progress = service.TASK_STATE_COMPLETE, 100
            job.params = {**dict(job.params or {}), "_outputs": keys, "_result": result}
        except Exception as exc:  # noqa: BLE001 - a failed run refunds what it held
            logger.warning(f"app run {job_id} failed: {exc}")
            job.state = service.TASK_STATE_FAILED
            job.error = str(exc)[:300] if isinstance(exc, runners.AppRunError) else "this app could not finish"
            job.failed_stage = "app_run"
            service.refund(session, job)
        return {"job_id": job_id, "state": job.state}


def enqueue(job_id: str) -> str:
    return str(run_app_task.apply_async(args=[job_id], queue="generation").id)


@celery_app.task(name=RUN_TASK, soft_time_limit=900, time_limit=960)
def run_app_task(job_id: str) -> dict[str, Any]:
    return run(job_id)


@celery_app.task(name=SCENE_TASK, soft_time_limit=600, time_limit=660)
def run_scene_task(job_id: str) -> dict[str, Any]:
    from app.services.avatar import scenes

    return scenes.run(job_id)


@celery_app.task(name=SCENE_CHECK_TASK, soft_time_limit=600, time_limit=660)
def check_scene_task(job_id: str) -> dict[str, Any]:
    from app.services.avatar import scenes

    return scenes.check(job_id)


def enqueue_scene(job_id: str) -> str:
    return str(run_scene_task.apply_async(args=[job_id], queue="generation").id)


__all__ = ["Deps", "RUN_TASK", "SCENE_CHECK_TASK", "SCENE_TASK", "check_scene_task", "enqueue", "enqueue_scene",
           "execute", "run", "run_app_task", "run_scene_task"]
