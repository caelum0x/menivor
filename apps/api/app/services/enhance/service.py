"""Upscale and smooth jobs (MH7): caps, prices, ownership and refunds.

* Image 4x upscale: an owned uploaded image or the poster of an owned render,
  on the CPU sidecar, free inside the daily cap (``esrgan_cpu.daily_cap``).
* Video upscale (SeedVR2 API) and smooth motion (RIFE, GPU lane only): an owned
  finished render, quoted in AI-video credits first, debited at start and
  refunded once if the job fails.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, time, timezone
from typing import Any, Callable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import esrgan_cpu, rife, seedvr_api
from .errors import EnhanceError

JOB_IMAGE = "enhance_image"
JOB_VIDEO = "enhance_video"
OPS = ("upscale", "smooth")
TASK_STATE_COMPLETE = 1
TASK_STATE_FAILED = -1
TASK_STATE_PROCESSING = 4
REFUND_REASON = "enhance_refund"

Probe = Callable[[str], Mapping[str, float]]


def probe_video(url: str) -> dict[str, float]:
    """Width, height, seconds and fps of a video URL (ffprobe, 20 s timeout)."""
    from app.domains.film.story8_render import ffmpeg_bin

    ffprobe = ffmpeg_bin().replace("ffmpeg", "ffprobe")
    done = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,r_frame_rate:format=duration", "-of", "json", url],
                          capture_output=True, text=True, timeout=20, check=False)
    if done.returncode != 0:
        raise EnhanceError(400, "bad_video", "we could not read that video")
    data = json.loads(done.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    num, _, den = str(stream.get("r_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {"width": float(stream.get("width") or 0), "height": float(stream.get("height") or 0),
            "seconds": float((data.get("format") or {}).get("duration") or 0), "fps": fps}


def _media_url(key: str) -> str:
    from app.domains.gallery.service import media_url

    return media_url(key)


def _owned_render(session: Session, user_id: str, job_id: str):
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None or str(job.user_id) != str(user_id) or getattr(job, "deleted_at", None) is not None:
        raise EnhanceError(404, "not_found", "render not found")
    if job.state != TASK_STATE_COMPLETE or not job.result_key:
        raise EnhanceError(409, "not_finished", "pick a finished render")
    return job


def _require_owned_key(session: Session, user_id: str, key: str) -> None:
    from app.domains.media.service import MediaDomainError, require_owned_asset

    try:
        require_owned_asset(session, user_id=user_id, key=key)
    except MediaDomainError as exc:
        raise EnhanceError(403, "not_yours", "that image is not in your uploads") from exc


def used_today(session: Session, user_id: str, *, now: datetime | None = None) -> int:
    from app.models.db.models import Job

    moment = now or datetime.now(timezone.utc)
    midnight = datetime.combine(moment.date(), time.min, tzinfo=timezone.utc)
    return int(session.execute(select(func.count(Job.id)).where(
        Job.user_id == user_id, Job.kind == JOB_IMAGE, Job.created_at >= midnight)).scalar() or 0)


def start_image(session: Session, user_id: str, *, image_key: str = "", source_job_id: str = "") -> Any:
    from app.models.db.repositories import JobRepository

    if bool(image_key) == bool(source_job_id):
        raise EnhanceError(400, "one_source", "pick one image: an upload or a render")
    if image_key:
        _require_owned_key(session, user_id, image_key)
        key = image_key
    else:
        render = _owned_render(session, user_id, source_job_id)
        key = render.poster_key or ""
        if not key:
            raise EnhanceError(409, "no_poster", "this render has no still to upscale")
    cap = esrgan_cpu.daily_cap()
    if used_today(session, user_id) >= cap:
        raise EnhanceError(429, "daily_cap", f"you can upscale {cap} images a day; more tomorrow")
    job = JobRepository(session).create(user_id=user_id, kind=JOB_IMAGE, params={
        "source_key": key, "scale": esrgan_cpu.SCALE, "credits_cost": 0, "workspace_id": None})
    job.state = TASK_STATE_PROCESSING
    session.flush()
    return job


def video_quote(session: Session, user_id: str, *, source_job_id: str, op: str,
                probe: Probe | None = None) -> dict[str, Any]:
    if op not in OPS:
        raise EnhanceError(400, "op", "pick upscale or smooth")
    render = _owned_render(session, user_id, source_job_id)
    if op == "smooth" and not rife.lane_configured():
        raise EnhanceError(503, "gpu_lane_off", "smooth motion runs only on the GPU lane, which is off right now")
    info = (probe or probe_video)(_media_url(render.result_key))
    if op == "upscale":
        price = seedvr_api.quote(width=int(info["width"]), height=int(info["height"]), seconds=info["seconds"],
                                 fps=info["fps"])
    else:
        price = rife.quote(seconds=info["seconds"])
    return {**price, "source_job_id": render.id, "seconds": round(float(info["seconds"]), 2)}


def start_video(session: Session, user_id: str, *, source_job_id: str, op: str, quoted_credits: int,
                probe: Probe | None = None) -> Any:
    from app.models.db.repositories import JobRepository
    from app.services.billing import premium_credits as pc

    price = video_quote(session, user_id, source_job_id=source_job_id, op=op, probe=probe)
    if int(quoted_credits) != int(price["ai_video_credits"]):
        raise EnhanceError(409, "quote_changed", "the price changed; check the new price first")
    job = JobRepository(session).create(user_id=user_id, kind=JOB_VIDEO, params={
        "op": op, "source_job_id": source_job_id, "credits_cost": 0, "ai_video_credits": price["ai_video_credits"],
        "provider_usd_estimate": price["provider_usd"], "workspace_id": None})
    try:
        pc.debit(session, user_id, pc.KIND_AI_VIDEO, price["ai_video_credits"], f"{pc.DEBIT_REASON}:{job.id}", job.id)
    except pc.InsufficientPremiumCredits as exc:
        raise EnhanceError(402, "ai_video_credits_required",
                           f"this needs {exc.needed} AI-video credits; you have {exc.available}") from exc
    job.state = TASK_STATE_PROCESSING
    session.flush()
    return job


def refund_video(session: Session, job: Any) -> int:
    from app.services.billing import premium_credits as pc

    params = dict(job.params or {})
    if params.get("_refunded"):
        return 0
    amount = int(params.get("ai_video_credits") or 0)
    if amount > 0:
        pc.grant(session, str(job.user_id), pc.KIND_AI_VIDEO, amount, f"{pc.REFUND_REASON}:{job.id}", job.id)
    job.params = {**params, "_refunded": True}
    session.flush()
    return amount


def job_view(job: Any) -> dict[str, Any]:
    params = dict(job.params or {})
    return {"job_id": job.id, "kind": job.kind, "op": params.get("op", "upscale"), "state": job.state,
            "result_url": _media_url(job.result_key or ""), "seconds": params.get("_seconds"),
            "output": params.get("_output"), "error": job.error or "", "refunded": bool(params.get("_refunded"))}


__all__ = ["JOB_IMAGE", "JOB_VIDEO", "OPS", "job_view", "probe_video", "refund_video", "start_image",
           "start_video", "used_today", "video_quote"]
