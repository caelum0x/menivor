"""Story in 8 frames workers (MH5): frames, identity scores, animation and the final video.

``run_story8_task(job_id)`` (generation queue):
1. makes the eight frames (house-paid image lane, cheapest commercially
   usable image model; the frame cost is covered by the story's standard
   credits), stores them under ``jobs/<id>/story8/`` and scores each against
   the character's reference image when there is one;
2. frames mode: Ken Burns each frame, narrate the lines with a free voice,
   burn captions and finish;
   animated mode: start one AI-video shot per frame (already paid by the
   story, so each shot carries 0 credits) and hand over to
   ``assemble_story8_task``.

``assemble_story8_task(job_id)`` waits for the shots (up to
``ANIMATE_TIMEOUT_S``); a shot that failed or timed out falls back to its Ken
Burns frame and its AI-video credits come back once.

Any other failure marks the story failed and refunds everything it held.

Every step reads the job's own preset (``params.preset``; story8 when absent), so
the same workers run story8 and very-time: frame model, beat seconds, shot
length, the shot request contract (``video_model``, ``references``, ``brief``
when the preset names a video model), static captions with the narration placed
on the speaking beat, and the look's grade at the final mux.
"""

from __future__ import annotations

import functools
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger

from app.workers.celery_app import celery_app

from . import story8, story8_render as render, very_time_worker

RUN_TASK = "app.domains.film.story8_tasks.run_story8_task"
ASSEMBLE_TASK = "app.domains.film.story8_tasks.assemble_story8_task"
ANIMATE_POLL_S = 30
ANIMATE_TIMEOUT_S = 20 * 60
FRAME_TIMEOUT_S = 90.0
BROLL_KIND = "broll_gen"


# --------------------------------------------------------------------------- #
# Default lanes (real services); tests inject their own
# --------------------------------------------------------------------------- #
def _download(url: str, timeout_s: float = FRAME_TIMEOUT_S) -> bytes:
    import requests

    response = requests.get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.content


def house_frame_image(prompt: str, negative: str, seed: int, model: str | None = None) -> bytes:
    """One frame from the image lane named in the preset, paid by us (no user wallet)."""
    from app.domains.gateway.media_catalog import image_models
    from app.domains.gateway.media_gateway import _provider_request
    from app.domains.gateway.provider_execution import MediaProviderExecutor

    wanted = str(model or story8.preset()["frame_model"])
    model = next((m for m in image_models() if m.id == wanted), None)
    if model is None:
        raise render.RenderError("the frame lane is not configured")
    text = f"{prompt}. Avoid: {negative}" if negative else prompt
    execution = MediaProviderExecutor().submit(
        _provider_request(model, correlation_id=f"story8-{seed}", prompt=text[:1800], cost_micros=model.price_micros))
    return _download(execution.outputs[0].reference)


def fit_frame(image: bytes) -> bytes:
    """Cover-crop any frame to 720x1280 PNG."""
    import io

    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(image)) as source:
        fitted = ImageOps.fit(source.convert("RGB"), (render.WIDTH, render.HEIGHT), Image.LANCZOS)
        out = io.BytesIO()
        fitted.save(out, format="PNG")
        return out.getvalue()


def free_narration(text: str, language: str, audio_path: str) -> list[list[Any]]:
    """Narrate with the free voice chain; returns word timings ``[[text, start, end], ...]``."""
    from app.core.launch.formats import free_voice_for
    from app.services.reelforge import _submaker_words
    from app.services.tts.narration import narrate, plan_chain

    voice = free_voice_for(language or "en")
    result = narrate(text, plan_chain(voice, language=language or "en", free_voice=voice), audio_path)
    words = _submaker_words(result.sub_maker)
    if not words:
        raise render.RenderError("narration returned no word timings")
    return words


def r2_upload(path: str, key: str, content_type: str) -> None:
    from app.platform.storage.r2 import get_r2_client

    get_r2_client().upload_file(path, key, content_type=content_type)


def r2_fetch(key: str) -> bytes:
    from app.domains.characters.hub import fetch_bytes

    return fetch_bytes(key)


def submit_shot(session: Any, story: Any, frame: dict[str, Any]) -> str:
    """One i2v shot for a frame, as a ``broll_gen`` job the story already paid for."""
    from app.models.db.repositories import JobRepository

    story_params = dict(story.params or {})
    animated = story8.job_preset(story_params)["animated"]
    seconds = float(frame["seconds"]) if animated.get("seconds_from_beat") else float(animated["seconds_per_shot"])
    params = {
        "_correlation_id": f"story8:{story.id}:{frame['index']}", "prompt": frame["prompt"][:1000], "mode": "i2v",
        "image_key": frame["key"], "width": render.WIDTH, "height": render.HEIGHT,
        "duration_s": seconds, "seed": int(frame["seed"]),
        "workflow_id": None, "credits_cost": 0, "ai_video_credits": 0, "provider_usd_estimate": 0,
        "workspace_id": None, "story8_parent": story.id,
    }
    video_model = story_params.get("video_model") or animated.get("video_model")
    if video_model:
        # Multi-reference contract (the media lane consumes it; older workers ignore it and
        # use prompt + image_key above): the frame is the first frame, the character's
        # reference image (when there is one) locks identity.
        if very_time_worker.is_very_time(story_params):
            references = very_time_worker.shot_references(story, frame, None)
            params["generate_audio"] = very_time_worker.shot_generate_audio(story_params, frame)
        else:
            references = [{"key": frame["key"], "role": "first_frame"}]
            if story_params.get("character_ref"):
                references.append({"key": str(story_params["character_ref"]), "role": "identity"})
        video_model = _shot_model(str(video_model), animated, references)
        if not _takes_many_images(video_model):
            references = references[:1]  # a first-frame-only model: the identity reference cannot ride along
        params.update(video_model=video_model, references=references, brief=dict(frame.get("brief") or {}))
    job = JobRepository(session).create(user_id=story.user_id, kind=BROLL_KIND, params=params)
    session.flush()
    return job.id


def _takes_many_images(model_id: str) -> bool:
    from app.domains.gateway.media_catalog import get_row

    row = get_row(model_id)
    return row is not None and "images" in row.inputs


def _shot_model(model_id: str, animated: dict[str, Any], references: list[dict[str, str]]) -> str:
    """With an identity reference, use the preset's reference-to-video model (a first-frame-only
    image-to-video model refuses a second image); otherwise keep the chosen model."""
    if len(references) > 1 and not _takes_many_images(model_id):
        wanted = (os.getenv("VERY_TIME_REFERENCE_VIDEO_MODEL") or "").strip() or \
            str(animated.get("reference_video_model") or "")
        if wanted and _takes_many_images(wanted):
            return wanted
    return model_id


def enqueue_shot(job_id: str) -> None:
    from app.workers.tasks import generate_broll_clip_task

    generate_broll_clip_task.apply_async(args=[{"job_id": job_id}], queue="generation")


def schedule_assemble(job_id: str, countdown: int = ANIMATE_POLL_S) -> None:
    assemble_story8_task.apply_async(args=[job_id], countdown=countdown, queue="generation")


@dataclass
class Deps:
    frame_image: Callable[[str, str, int], bytes] = house_frame_image
    narrate: Callable[[str, str, str], list[list[Any]]] = free_narration
    upload: Callable[[str, str, str], None] = r2_upload
    fetch: Callable[[str], bytes] = r2_fetch
    submit_shot: Callable[[Any, Any, dict[str, Any]], str] = submit_shot
    enqueue_shot: Callable[[str], None] = enqueue_shot
    schedule_assemble: Callable[[str], None] = schedule_assemble
    burn_captions: bool | None = None  # None: burn when ffmpeg has the ass filter
    grade: bool | None = None  # None: apply the look's LUT when ffmpeg has the lut3d filter
    now: Callable[[], float] = field(default=time.time)
    very_time: Any = None  # very_time_worker.VtDeps (None: the real lanes)


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
def _session():
    from app.models.db.base import get_session

    return get_session()


def _load(session: Any, job_id: str):
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None or job.kind != story8.JOB_KIND:
        raise LookupError(f"story {job_id} not found")
    return job


def _save(job: Any, **changes: Any) -> None:
    job.params = {**dict(job.params or {}), **changes}


def _score_frames(session: Any, job: Any, frames: list[dict[str, Any]], deps: Deps) -> list[dict[str, Any]]:
    character_id = (job.params or {}).get("character_id")
    if not character_id:
        return frames
    from app.domains.characters import hub

    try:
        character = hub.character_for_user(session, str(job.user_id), character_id)
    except hub.HubError as exc:
        logger.warning(f"story8 {job.id}: no identity scoring ({exc.code})")
        return frames
    refs = list(character.get("reference_images") or [])
    if not refs:
        return frames
    reference = deps.fetch(refs[0])
    pid = story8.job_preset_id(job)
    scored = []
    for frame in frames:
        score = hub.appearance_score(reference, deps.fetch(frame["key"]))
        session.add(hub.CharacterIdentityScore(character_id=character_id, user_id=str(job.user_id), job_id=job.id,
                                               preset_id=f"{pid}:frame-{frame['index'] + 1}", model=f"{pid}-frames",
                                               score=score))
        scored.append({**frame, "identity_score": score})
    return scored


def _frame_lane(job: Any, deps: Deps) -> Callable[[str, str, int], bytes]:
    """The image lane for this job: the default house lane uses the job preset's frame model."""
    if deps.frame_image is house_frame_image:
        return functools.partial(house_frame_image, model=str(story8.job_preset(job)["frame_model"]))
    return deps.frame_image


def make_frames(session: Any, job: Any, work: str, deps: Deps) -> list[dict[str, Any]]:
    if very_time_worker.is_very_time(job):
        frames = very_time_worker.make_frames(session, job, work, deps, fit_frame)
        frames = _score_frames(session, job, frames, deps)
        _save(job, frames=frames, _stage="frames_ready")
        session.flush()
        return frames
    frames = [dict(f) for f in (job.params or {}).get("frames") or []]
    lane = _frame_lane(job, deps)
    for frame in frames:
        if frame.get("key"):
            continue
        image = fit_frame(lane(frame["prompt"], frame.get("negative", ""), int(frame["seed"])))
        path = os.path.join(work, f"frame-{frame['index'] + 1}.png")
        with open(path, "wb") as fh:
            fh.write(image)
        key = f"jobs/{job.id}/story8/frame-{frame['index'] + 1}.png"
        deps.upload(path, key, "image/png")
        frame["key"] = key
    frames = _score_frames(session, job, frames, deps)
    _save(job, frames=frames, _stage="frames_ready")
    session.flush()
    return frames


def _frame_file(frame: dict[str, Any], work: str, deps: Deps) -> str:
    path = os.path.join(work, f"frame-{frame['index'] + 1}.png")
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(deps.fetch(frame["key"]))
    return path


def _speech_plan(data: dict[str, Any], params: dict[str, Any], frames: list[dict[str, Any]]) -> dict[str, Any]:
    """What is narrated, when, and how it is captioned.

    Karaoke presets (story8): every line is narrated from 0 s, word-by-word captions.
    Static presets (very-time): only the frames with a line speak; the narration is
    delayed to the first speaking frame and the sentence is shown, whole, from that
    frame's start to the end of the video in the look's caption style.
    """
    captions = data.get("captions") or {}
    if captions.get("mode") != "static":
        return {"text": " ".join(f["line"] for f in frames), "style": render.KARAOKE, "lines": None, "delay_s": 0.0}
    ordered = sorted(frames, key=lambda f: int(f["index"]))
    speaking = [f for f in ordered if str(f.get("line") or "").strip()]
    if not speaking:
        raise render.RenderError("this story has no spoken line")
    start = sum(float(f["seconds"]) for f in ordered if int(f["index"]) < int(speaking[0]["index"]))
    total = sum(float(f["seconds"]) for f in ordered)
    text = " ".join(str(f["line"]).strip() for f in speaking)
    look = (data.get("looks") or {}).get(str(params.get("look") or ""), {})
    style = str(look.get("caption_style") or captions.get("style") or "game_yellow")
    return {"text": text, "style": style, "lines": [(text, start, total)],
            "delay_s": start + float(captions.get("speech_lead_s") or 0.0)}


def finish(session: Any, job: Any, work: str, deps: Deps, clips: dict[int, str] | None = None) -> None:
    """Assemble the eight slots, narrate, caption, upload and mark the story finished."""
    if very_time_worker.is_very_time(job):
        very_time_worker.finish(session, job, work, deps, clips or {},
                                frame_file=lambda frame: _frame_file(frame, work, deps))
        _publish(session, job, work, deps)
        return
    params = dict(job.params or {})
    frames = [dict(f) for f in params.get("frames") or []]
    clips = clips or {}
    ffmpeg = render.ffmpeg_bin()
    slots = []
    for frame in frames:
        out = os.path.join(work, f"slot-{frame['index'] + 1}.mp4")
        clip = clips.get(int(frame["index"]))
        if clip:
            render.run(render.fit_clip_command(clip, out, seconds=frame["seconds"], ffmpeg=ffmpeg))
        else:
            render.run(render.ken_burns_command(_frame_file(frame, work, deps), out, seconds=frame["seconds"],
                                                camera=frame["camera"], ffmpeg=ffmpeg))
        slots.append(out)
    silent = os.path.join(work, "story.mp4")
    render.run(render.concat_command(slots, silent, ffmpeg=ffmpeg))
    audio = os.path.join(work, "narration.mp3")
    data = story8.job_preset(params)
    language = str(params.get("language") or "")
    speech = _speech_plan(data, params, frames)
    words = deps.narrate(speech["text"], language, audio)
    burn = deps.burn_captions if deps.burn_captions is not None else render.has_filter("ass", ffmpeg)
    ass_path = None
    if burn:
        ass_path = os.path.join(work, "captions.ass")
        with open(ass_path, "w", encoding="utf-8") as fh:
            fh.write(render.captions_ass(words, speech["style"], lines=speech["lines"], language=language))
    elif deps.burn_captions is None:
        raise render.RenderError("this ffmpeg cannot burn captions (no ass filter)")
    final = os.path.join(work, "final.mp4")
    from app.utils import utils

    look = (data.get("looks") or {}).get(str(params.get("look") or ""))
    grade = render.look_filters(look, ffmpeg=ffmpeg, lut_available=deps.grade)
    render.run(render.mux_command(silent, audio, final, ass_path=ass_path, fonts_dir=utils.font_dir(), ffmpeg=ffmpeg,
                                  video_filters=grade, audio_delay_s=speech["delay_s"]))
    _publish(session, job, work, deps)


def _publish(session: Any, job: Any, work: str, deps: Deps) -> None:
    """Poster, upload and mark the story finished (``work/final.mp4`` is the video)."""
    final = os.path.join(work, "final.mp4")
    poster = os.path.join(work, "poster.jpg")
    render.run(render.poster_command(final, poster, ffmpeg=render.ffmpeg_bin()))
    result_key, poster_key = f"jobs/{job.id}/story8/final.mp4", f"jobs/{job.id}/story8/poster.jpg"
    deps.upload(final, result_key, "video/mp4")
    deps.upload(poster, poster_key, "image/jpeg")
    job.result_key, job.preview_key, job.poster_key = result_key, result_key, poster_key
    job.state = story8.TASK_STATE_COMPLETE
    job.progress = 100
    _save(job, _stage="finished", _finished_at=datetime.now(timezone.utc).isoformat())
    session.flush()


def _fail(job_id: str, error: str) -> None:
    try:
        with _session() as session:
            job = _load(session, job_id)
            if job.state == story8.TASK_STATE_COMPLETE:
                return
            job.state = story8.TASK_STATE_FAILED
            job.error, job.failed_stage = error[:300], "story8"
            _save(job, _stage="failed", _error=error[:300])
            story8.refund(session, job)
    except Exception as exc:  # noqa: BLE001 - never raise out of the failure path
        logger.error(f"story8 {job_id}: refund after failure did not complete: {exc}")


def _meter(job_id: str, user_id: str) -> None:
    try:
        from app.integrations.railyard.meters import on_render_settled

        on_render_settled(job_id=job_id, owner_key=user_id, job_kind=story8.JOB_KIND)
    except Exception as exc:  # noqa: BLE001 - metering never fails a render
        logger.warning(f"story8 {job_id}: meter not queued: {exc}")


def run(job_id: str, deps: Deps | None = None) -> dict[str, Any]:
    deps = deps or Deps()
    try:
        with tempfile.TemporaryDirectory(prefix="story8-") as work, _session() as session:
            job = _load(session, job_id)
            if job.state in (story8.TASK_STATE_COMPLETE, story8.TASK_STATE_FAILED):
                return {"job_id": job_id, "state": job.state}
            frames = make_frames(session, job, work, deps)
            if (job.params or {}).get("mode") == story8.MODE_ANIMATED:
                shots = {}
                for frame in frames:
                    shots[str(frame["index"])] = deps.submit_shot(session, job, frame)
                _save(job, _shots=shots, _stage="animating", _animate_started=deps.now())
                session.commit()
                for shot_id in shots.values():
                    deps.enqueue_shot(shot_id)
                deps.schedule_assemble(job_id)
                return {"job_id": job_id, "stage": "animating"}
            finish(session, job, work, deps)
            user_id = str(job.user_id)
        _meter(job_id, user_id)
        return {"job_id": job_id, "stage": "finished"}
    except Exception as exc:  # noqa: BLE001 - a failed story refunds what it held
        logger.error(f"story8 {job_id} failed: {exc}")
        _fail(job_id, str(exc) or type(exc).__name__)
        return {"job_id": job_id, "stage": "failed"}


def assemble(job_id: str, deps: Deps | None = None) -> dict[str, Any]:
    """Animated stories: wait for the shots, fall back per shot, then finish."""
    from app.models.db.models import Job

    deps = deps or Deps()
    try:
        with tempfile.TemporaryDirectory(prefix="story8-") as work, _session() as session:
            job = _load(session, job_id)
            if job.state in (story8.TASK_STATE_COMPLETE, story8.TASK_STATE_FAILED):
                return {"job_id": job_id, "state": job.state}
            params = dict(job.params or {})
            shots = {int(k): v for k, v in (params.get("_shots") or {}).items()}
            rows = {index: session.get(Job, shot_id) for index, shot_id in shots.items()}
            pending = [i for i, row in rows.items() if row is not None and row.state not in
                       (story8.TASK_STATE_COMPLETE, story8.TASK_STATE_FAILED)]
            waited = deps.now() - float(params.get("_animate_started") or deps.now())
            if pending and waited < ANIMATE_TIMEOUT_S:
                deps.schedule_assemble(job_id)
                return {"job_id": job_id, "stage": "animating", "pending": len(pending)}
            clips: dict[int, str] = {}
            for index, row in rows.items():
                if row is not None and row.state == story8.TASK_STATE_COMPLETE and row.result_key:
                    path = os.path.join(work, f"shot-{index + 1}.mp4")
                    with open(path, "wb") as fh:
                        fh.write(deps.fetch(row.result_key))
                    clips[index] = path
            failed = len(story8.job_preset(params)["beats"]) - len(clips)
            frames = [{**f, "clip_key": rows[int(f["index"])].result_key if int(f["index"]) in clips else None}
                      for f in params.get("frames") or []]
            _save(job, frames=frames)
            if failed and not params.get("_shots_refunded"):
                lost = [f for f in frames if int(f["index"]) not in clips]
                if all("ai_credits" in f for f in lost):  # shots priced by length (very-time)
                    story8.refund(session, job, failed_credits=sum(int(f["ai_credits"]) for f in lost))
                else:
                    story8.refund(session, job, clips_failed=failed)
                _save(job, _shots_refunded=failed)
            if very_time_worker.is_very_time(job) and \
                    very_time_worker.payoff_stage(session, job, work, deps, clips) == "wait":
                session.commit()
                deps.schedule_assemble(job_id)
                return {"job_id": job_id, "stage": "payoff"}
            finish(session, job, work, deps, clips)
            user_id = str(job.user_id)
        _meter(job_id, user_id)
        return {"job_id": job_id, "stage": "finished", "fallback_frames": failed}
    except Exception as exc:  # noqa: BLE001 - a failed story refunds what it held
        logger.error(f"story8 {job_id} assemble failed: {exc}")
        _fail(job_id, str(exc) or type(exc).__name__)
        return {"job_id": job_id, "stage": "failed"}


@celery_app.task(name=RUN_TASK, soft_time_limit=1500, time_limit=1560)
def run_story8_task(job_id: str) -> dict[str, Any]:
    return run(job_id)


@celery_app.task(name=ASSEMBLE_TASK, soft_time_limit=1500, time_limit=1560)
def assemble_story8_task(job_id: str) -> dict[str, Any]:
    return assemble(job_id)


__all__ = ["ASSEMBLE_TASK", "Deps", "RUN_TASK", "assemble", "assemble_story8_task", "finish", "fit_frame",
           "make_frames", "run", "run_story8_task"]
