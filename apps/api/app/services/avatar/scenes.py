"""Talking scenes (MH6, Wave P PM2.2): selfie, podcast, car, desk and product-in-hand.

Owner-gated with MU15, MO12 and OU5: every route and every line of copy stays
off until ``PRESENTER_LIVE`` is on. With it on, a scene run is:

1. **Scene still**: the consented character's reference photo placed into the
   scene look by the hosted edit model (``apps_shelf.runners.edit_image``).
   Only the user's own consented real-face character or an original character
   is accepted; never a third-party face, and there is no face swap.
2. **Voice**: the script narrated with the free voice chain (or the user's own
   uploaded audio).
3. **Lip-sync**: the existing speak lipsync path (``speak_lipsync`` job, a
   commercial-safe provider only), paid for by the scene, so the child job
   carries 0 credits (MO12 owns the provider files; this module only calls it).
4. **Checks before it is shown**: duration within 0.25 s of the narration,
   mouth-audio offset under 80 ms (measured by cross-correlating the audio
   envelope with mouth-region motion), and the disclosure line burned on.
   A render that fails a check is failed and refunded, never shipped.

Price (AI-video credits, quoted first): the scene still at 3x its recorded
image price plus the lipsync render at the speak route's price.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

from loguru import logger

SCENES_DIR = Path(__file__).resolve().parents[3] / "assets" / "presets" / "scenes"
PRESENTER_LIVE_ENV = "PRESENTER_LIVE"
JOB_KIND = "scene_run"
SPEAK_KIND = "speak_lipsync"
MAX_OFFSET_MS = 80.0
MAX_DURATION_DELTA_S = 0.25
MAX_SCRIPT = 900
STILL_USD = 0.04
STILL_PRICE_SOURCE = "https://fal.ai/models/fal-ai/flux-pro/kontext"
LIPSYNC_WAIT_S = 20 * 60
LIPSYNC_POLL_S = 30
TASK_STATE_COMPLETE = 1
TASK_STATE_FAILED = -1
TASK_STATE_PROCESSING = 4
_FILE = re.compile(r"^(?P<id>[a-z0-9-]+)@v(?P<version>\d+)\.json$")


class SceneError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def presenter_live(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return (source.get(PRESENTER_LIVE_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Scene:
    id: str
    version: int
    name: str
    blurb: str
    look: str
    layout: str
    needs_product: bool
    disclosure: str


@lru_cache(maxsize=1)
def scenes() -> tuple[Scene, ...]:
    out = []
    for path in sorted(SCENES_DIR.glob("*@v*.json")):
        match = _FILE.match(path.name)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not match or data["id"] != match["id"] or int(data["version"]) != int(match["version"]):
            raise ValueError(f"scene file {path.name} does not match its id and version")
        out.append(Scene(id=data["id"], version=int(data["version"]), name=data["name"], blurb=data["blurb"],
                         look=data["look"], layout=data["layout"], needs_product=bool(data["needs_product"]),
                         disclosure=data["disclosure"]))
    return tuple(out)


def get(scene_id: str) -> Scene | None:
    return next((s for s in scenes() if s.id == str(scene_id or "").strip().lower()), None)


def require_live() -> None:
    if not presenter_live():
        raise SceneError(404, "not_found", "not found")


# --------------------------------------------------------------------------- #
# Price
# --------------------------------------------------------------------------- #
def quote() -> dict[str, Any]:
    from app.domains.speak.router import _available_providers, _speak_ai_video_credits
    from app.domains.speak.selection import NoLipsyncProviderError, choose_lipsync_provider
    from app.services.billing.premium_credits import ai_video_credits_for_usd

    try:
        provider = choose_lipsync_provider({}, {}, commercial=True, available=_available_providers())
    except NoLipsyncProviderError as exc:
        raise SceneError(503, "no_lipsync", "talking scenes are not available right now") from exc
    still = max(1, ai_video_credits_for_usd(STILL_USD))
    lipsync = int(_speak_ai_video_credits(provider))
    return {"credit_kind": "ai_video", "ai_video_credits": still + lipsync, "still_credits": still,
            "lipsync_credits": lipsync, "provider": provider, "price_source": STILL_PRICE_SOURCE}


# --------------------------------------------------------------------------- #
# Start
# --------------------------------------------------------------------------- #
def _character(session: Any, user_id: str, character_id: str) -> dict[str, Any]:
    from app.domains.characters import hub

    try:
        character = hub.character_for_user(session, user_id, character_id)
    except hub.HubError as exc:
        raise SceneError(exc.status_code, exc.code, str(exc)) from exc
    if character.get("kind") not in (hub.KIND_REAL_FACE, hub.KIND_ORIGINAL):
        raise SceneError(400, "character_kind", "use yourself (with spoken consent) or an original character")
    if not character.get("reference_images"):
        raise SceneError(400, "no_reference", "this character has no photo to place in the scene")
    return character


def start(session: Any, user_id: str, scene_id: str, *, character_id: str, script: str, quoted_credits: int,
          product_key: str = "") -> Any:
    from app.models.db.repositories import JobRepository
    from app.services.billing import premium_credits as pc

    require_live()
    scene = get(scene_id)
    if scene is None:
        raise SceneError(404, "not_found", "scene not found")
    text = " ".join(str(script or "").split())[:MAX_SCRIPT]
    if not text:
        raise SceneError(400, "script_required", "write what they should say")
    character = _character(session, user_id, character_id)
    if scene.needs_product and not product_key:
        raise SceneError(400, "product_required", "add a product photo for this scene")
    if product_key:
        from app.domains.media.service import MediaDomainError, require_owned_asset

        try:
            require_owned_asset(session, user_id=user_id, key=product_key)
        except MediaDomainError as exc:
            raise SceneError(403, "not_yours", "that product photo is not in your uploads") from exc
    price = quote()
    if int(quoted_credits) != price["ai_video_credits"]:
        raise SceneError(409, "quote_changed", "the price changed; check the new price first")
    job = JobRepository(session).create(user_id=user_id, kind=JOB_KIND, params={
        "scene_id": scene.id, "scene_version": scene.version, "character_id": character["id"],
        "reference_key": character["reference_images"][0], "product_key": product_key or None, "script": text,
        "provider": price["provider"], "credits_cost": 0, "ai_video_credits": price["ai_video_credits"],
        "workspace_id": None, "disclosure": scene.disclosure})
    try:
        pc.debit(session, user_id, pc.KIND_AI_VIDEO, price["ai_video_credits"], f"{pc.DEBIT_REASON}:{job.id}", job.id)
    except pc.InsufficientPremiumCredits as exc:
        raise SceneError(402, "ai_video_credits_required",
                         f"this scene needs {exc.needed} AI-video credits; you have {exc.available}") from exc
    job.state = TASK_STATE_PROCESSING
    session.flush()
    return job


def refund(session: Any, job: Any) -> int:
    from app.services.billing import premium_credits as pc

    params = dict(job.params or {})
    if params.get("_refunded"):
        return 0
    amount = int(params.get("ai_video_credits") or 0)
    if amount:
        pc.grant(session, str(job.user_id), pc.KIND_AI_VIDEO, amount, f"{pc.REFUND_REASON}:{job.id}", job.id)
    job.params = {**params, "_refunded": True}
    session.flush()
    return amount


# --------------------------------------------------------------------------- #
# Checks (pure where possible)
# --------------------------------------------------------------------------- #
def duration_ok(video_s: float, audio_s: float) -> bool:
    return abs(float(video_s) - float(audio_s)) <= MAX_DURATION_DELTA_S


def best_lag_ms(audio_env, mouth_env, *, fps: float, max_lag_ms: float = 300.0) -> float:
    """Lag (ms) that best aligns mouth motion to the audio envelope; positive = video late."""
    import numpy as np

    a = np.asarray(audio_env, dtype="float64")
    m = np.asarray(mouth_env, dtype="float64")
    n = min(len(a), len(m))
    if n < 8:
        raise SceneError(422, "sync_unmeasured", "the clip is too short to measure lip-sync")
    a, m = a[:n] - a[:n].mean(), m[:n] - m[:n].mean()
    if not a.any() or not m.any():
        raise SceneError(422, "sync_unmeasured", "no speech or no mouth movement to measure")
    max_lag = int(round(max_lag_ms / 1000.0 * fps))
    best, best_score = 0, -np.inf
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            score = float(np.dot(a[: n - lag], m[lag:]))
        else:
            score = float(np.dot(a[-lag:], m[: n + lag]))
        if score > best_score:
            best, best_score = lag, score
    return best * 1000.0 / fps


def measure_offset_ms(video_path: str, *, fps: int = 25, seconds: float = 20.0) -> float:
    """Mouth-audio offset: audio RMS per video frame against mouth-region motion (lower-centre crop)."""
    import numpy as np

    from app.domains.apps_shelf.runners import SAMPLE_RATE, decode_audio
    from app.domains.film.story8_render import ffmpeg_bin

    w, h = 96, 64
    crop = "crop=iw*0.4:ih*0.18:iw*0.3:ih*0.55"
    done = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-i", video_path, "-t", f"{seconds}",
                           "-vf", f"fps={fps},{crop},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                          capture_output=True, timeout=120, check=False)
    frames = np.frombuffer(done.stdout, dtype=np.uint8)
    count = len(frames) // (w * h)
    if count < 8:
        raise SceneError(422, "sync_unmeasured", "the clip is too short to measure lip-sync")
    stack = frames[: count * w * h].reshape(count, h, w).astype("float32") / 255.0
    mouth = np.concatenate([[0.0], np.abs(np.diff(stack, axis=0)).mean(axis=(1, 2))])
    samples = decode_audio(video_path, seconds=seconds)
    per_frame = SAMPLE_RATE / fps
    audio = np.array([np.sqrt(np.mean(samples[int(i * per_frame):int((i + 1) * per_frame)] ** 2) or 0.0)
                      if int(i * per_frame) < len(samples) else 0.0 for i in range(count)])
    # Mouth motion follows the change in loudness, not the loudness itself.
    audio_change = np.abs(np.diff(audio, prepend=audio[0]))
    return best_lag_ms(audio_change, mouth, fps=fps)


def disclosure_ass(text: str, seconds: float) -> str:
    """A small top-left disclosure line for the whole clip (ASS)."""
    from app.services.captions.ass_karaoke import _format_ts

    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 720", "PlayResY: 1280", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        "Style: Disclosure,Arial,26,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,7,24,24,40,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{_format_ts(0.0)},{_format_ts(max(0.1, seconds))},Disclosure,,0,0,0,,{text}", ""])


# --------------------------------------------------------------------------- #
# Worker steps
# --------------------------------------------------------------------------- #
def _default_edit(prompt: str, image_url: str) -> bytes:
    from app.domains.apps_shelf.runners import edit_image

    return edit_image(prompt, image_url)


def _default_narrate(text: str, audio_path: str) -> float:
    from app.domains.film.story8_tasks import free_narration

    words = free_narration(text, "", audio_path)
    return float(words[-1][2]) if words else 0.0


def _default_submit_speak(session: Any, scene_job: Any, image_key: str, audio_key: str) -> str:
    from app.models.db.repositories import JobRepository

    params = {"_correlation_id": f"scene:{scene_job.id}", "image_key": image_key, "audio_key": audio_key,
              "provider": scene_job.params["provider"], "license_class": "commercial", "credits_cost": 0,
              "ai_video_credits": 0, "provider_usd_estimate": 0, "workspace_id": None, "scene_parent": scene_job.id}
    job = JobRepository(session).create(user_id=scene_job.user_id, kind=SPEAK_KIND, params=params)
    session.flush()
    return job.id


def _default_enqueue_speak(job_id: str) -> None:
    from app.workers.tasks import generate_speak_lipsync_task

    generate_speak_lipsync_task.apply_async(args=[{"job_id": job_id, "request_id": f"scene:{job_id}"}])


def _default_schedule(job_id: str) -> None:
    from app.domains.apps_shelf.tasks import check_scene_task

    check_scene_task.apply_async(args=[job_id], countdown=LIPSYNC_POLL_S, queue="generation")


def _signed(key: str) -> str:
    from app.domains.gallery.service import media_url

    return media_url(key)


def _upload(path: str, key: str, content_type: str) -> None:
    from app.platform.storage.r2 import get_r2_client

    get_r2_client().upload_file(path, key, content_type=content_type)


def _fetch(key: str) -> bytes:
    from app.domains.characters.hub import fetch_bytes

    return fetch_bytes(key)


@dataclass
class Deps:
    edit_image: Callable[[str, str], bytes] = _default_edit
    narrate: Callable[[str, str], float] = _default_narrate
    submit_speak: Callable[[Any, Any, str, str], str] = _default_submit_speak
    enqueue_speak: Callable[[str], None] = _default_enqueue_speak
    schedule_check: Callable[[str], None] = _default_schedule
    signed_url: Callable[[str], str] = _signed
    upload: Callable[[str, str, str], None] = _upload
    fetch: Callable[[str], bytes] = _fetch
    measure_offset_ms: Callable[[str], float] = measure_offset_ms
    burn: Callable[[str, str, str, float], None] | None = None
    now: Callable[[], float] = time.time


def _still_prompt(scene: Scene, has_product: bool) -> str:
    product = " holding the product from the second photo" if has_product else ""
    return (f"The same person, face and identity unchanged, {scene.look}{product}. Looking at the camera, mouth "
            "closed, photorealistic, vertical 9:16.")


def _fail(session: Any, job: Any, message: str) -> None:
    job.state = TASK_STATE_FAILED
    job.error, job.failed_stage = message[:300], "scene"
    refund(session, job)


def run(job_id: str, deps: Deps | None = None) -> dict[str, Any]:
    """Scene still and voice, then hand over to the lipsync job and the checks."""
    from app.models.db.base import get_session
    from app.models.db.models import Job

    deps = deps or Deps()
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None or job.kind != JOB_KIND or job.state != TASK_STATE_PROCESSING:
            return {"job_id": job_id, "state": getattr(job, "state", None)}
        try:
            scene = get(job.params["scene_id"])
            if scene is None:
                raise SceneError(404, "not_found", "scene not found")
            prefix = f"jobs/{job.id}/scene"
            with tempfile.TemporaryDirectory(prefix="scene-") as work:
                still = deps.edit_image(_still_prompt(scene, bool(job.params.get("product_key"))),
                                        deps.signed_url(job.params["reference_key"]))
                still_path = os.path.join(work, "still.png")
                Path(still_path).write_bytes(still)
                deps.upload(still_path, f"{prefix}/still.png", "image/png")
                audio_path = os.path.join(work, "voice.mp3")
                audio_s = deps.narrate(job.params["script"], audio_path)
                deps.upload(audio_path, f"{prefix}/voice.mp3", "audio/mpeg")
            speak_id = deps.submit_speak(session, job, f"{prefix}/still.png", f"{prefix}/voice.mp3")
            job.params = {**dict(job.params or {}), "_still_key": f"{prefix}/still.png",
                          "_audio_key": f"{prefix}/voice.mp3", "_audio_s": audio_s, "_speak_job": speak_id,
                          "_speak_started": deps.now()}
            session.commit()
            deps.enqueue_speak(speak_id)
            deps.schedule_check(job_id)
            return {"job_id": job_id, "stage": "lipsync"}
        except Exception as exc:  # noqa: BLE001 - a failed scene refunds everything
            logger.warning(f"scene {job_id} failed: {exc}")
            _fail(session, job, str(exc) if isinstance(exc, SceneError) else "the scene could not be made")
            return {"job_id": job_id, "stage": "failed"}


def default_burn(video_path: str, out_path: str, text: str, seconds: float) -> None:
    from app.domains.film.story8_render import ffmpeg_bin, has_filter, run as run_ffmpeg

    if not has_filter("ass"):
        raise SceneError(500, "no_ass", "this server cannot burn the disclosure line")
    ass_path = out_path + ".ass"
    Path(ass_path).write_text(disclosure_ass(text, seconds), encoding="utf-8")
    run_ffmpeg([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", video_path, "-vf", f"ass={ass_path}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy",
                "-movflags", "+faststart", out_path])


def check(job_id: str, deps: Deps | None = None) -> dict[str, Any]:
    """Wait for the lipsync job, run the checks, burn the disclosure line and finish (or fail and refund)."""
    from app.domains.apps_shelf.runners import probe_seconds
    from app.models.db.base import get_session
    from app.models.db.models import Job

    deps = deps or Deps()
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None or job.kind != JOB_KIND or job.state != TASK_STATE_PROCESSING:
            return {"job_id": job_id, "state": getattr(job, "state", None)}
        params = dict(job.params or {})
        speak = session.get(Job, params.get("_speak_job"))
        if speak is None:
            _fail(session, job, "the lip-sync step was lost")
            return {"job_id": job_id, "stage": "failed"}
        if speak.state not in (TASK_STATE_COMPLETE, TASK_STATE_FAILED):
            if deps.now() - float(params.get("_speak_started") or deps.now()) < LIPSYNC_WAIT_S:
                deps.schedule_check(job_id)
                return {"job_id": job_id, "stage": "lipsync"}
            _fail(session, job, "lip-sync took too long")
            return {"job_id": job_id, "stage": "failed"}
        if speak.state == TASK_STATE_FAILED or not speak.result_key:
            _fail(session, job, "lip-sync failed")
            return {"job_id": job_id, "stage": "failed"}
        try:
            with tempfile.TemporaryDirectory(prefix="scene-") as work:
                raw = os.path.join(work, "talking.mp4")
                Path(raw).write_bytes(deps.fetch(speak.result_key))
                seconds = probe_seconds(raw)
                if not duration_ok(seconds, float(params.get("_audio_s") or 0)):
                    raise SceneError(422, "duration", "the video length does not match the voice")
                offset = deps.measure_offset_ms(raw)
                if abs(offset) >= MAX_OFFSET_MS:
                    raise SceneError(422, "lipsync_offset", "the lips and voice are out of sync")
                final = os.path.join(work, "final.mp4")
                (deps.burn or default_burn)(raw, final, params["disclosure"], seconds)
                key = f"jobs/{job.id}/scene/final.mp4"
                deps.upload(final, key, "video/mp4")
            job.result_key, job.preview_key = key, key
            job.state, job.progress = TASK_STATE_COMPLETE, 100
            job.params = {**params, "_checks": {"duration_s": round(seconds, 2), "offset_ms": round(offset, 1),
                                                "disclosure": True}}
            return {"job_id": job_id, "stage": "finished"}
        except Exception as exc:  # noqa: BLE001 - a scene that fails a check is never shipped
            logger.warning(f"scene {job_id} check failed: {exc}")
            _fail(session, job, str(exc) if isinstance(exc, SceneError) else "the scene could not be finished")
            return {"job_id": job_id, "stage": "failed"}


def scene_view(scene: Scene) -> dict[str, Any]:
    return {"id": scene.id, "name": scene.name, "blurb": scene.blurb, "needs_product": scene.needs_product}


def job_view(job: Any) -> dict[str, Any]:
    from app.domains.gallery.service import media_url

    params = dict(job.params or {})
    return {"job_id": job.id, "scene_id": params.get("scene_id"), "state": job.state,
            "video_url": media_url(job.result_key or ""), "checks": params.get("_checks"), "error": job.error or "",
            "refunded": bool(params.get("_refunded"))}


__all__ = ["JOB_KIND", "MAX_DURATION_DELTA_S", "MAX_OFFSET_MS", "Deps", "SceneError", "best_lag_ms", "check",
           "disclosure_ass", "duration_ok", "get", "job_view", "measure_offset_ms", "presenter_live", "quote",
           "refund", "run", "scene_view", "scenes", "start"]
