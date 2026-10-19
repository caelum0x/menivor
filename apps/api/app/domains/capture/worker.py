"""Capture execution + dispatch.

:func:`run_capture` is the single entrypoint (never raises; every failure is
recorded on the :class:`CaptureJob`). :func:`dispatch_capture` hands a job to
an executor:

* ``inline`` (default) - a small bounded thread pool in the API process. A
  restart mid-capture is recovered by the stale sweep on the next read.
* ``celery`` - ``[app] capture_executor = "celery"`` sends it to the ``render``
  queue via :mod:`app.domains.capture.tasks` (the worker must include it).

Outputs are uploaded under ``uploads/<uuid>.<ext>`` (the same user-upload
namespace Ad Studio uses, accepted by the reel pipeline's key ownership guard)
and registered as the caller's media assets.
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger

from app.domains.capture import encode
from app.domains.capture.models import (
    KIND_APP_STORE,
    KIND_NATIVE_GAME,
    KIND_PLAY_STORE,
    LEGACY_KINDS,
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
)

STALE_CAPTURE_S = 25 * 60
_POOL: concurrent.futures.ThreadPoolExecutor | None = None
_POOL_LOCK = threading.Lock()
#: One recording per simulator/emulator at a time within this process.
_DEVICE_LOCKS: dict[str, threading.Lock] = {}


class CaptureFailed(RuntimeError):
    """A user-presentable capture failure."""


def _config_value(key: str, default: Any) -> Any:
    try:
        from app.config import config

        return config.app.get(key, default)
    except Exception:  # noqa: BLE001 - config shape drift
        return default


def _pool() -> concurrent.futures.ThreadPoolExecutor:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            workers = max(1, min(4, int(_config_value("capture_workers", 1) or 1)))
            _POOL = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="capture")
        return _POOL


def dispatch_capture(capture_id: str) -> str:
    """Queue ``capture_id``; returns the celery task id ('' when inline)."""
    mode = str(_config_value("capture_executor", "inline") or "inline").lower()
    if mode == "celery":
        try:
            from app.domains.capture.tasks import run_capture_task

            result = run_capture_task.apply_async(args=[capture_id], queue="render")
            return str(getattr(result, "id", "") or "")
        except Exception as exc:  # noqa: BLE001 - broker down -> run inline
            logger.warning(f"capture celery dispatch failed, running inline: {exc}")
    _pool().submit(run_capture, capture_id)
    return ""


# --------------------------------------------------------------------------- #
# Persistence helpers
# --------------------------------------------------------------------------- #
def _lock(session: Any, capture_id: str) -> Any:
    from app.domains.capture.models import CaptureJob

    query = session.query(CaptureJob).filter(CaptureJob.id == capture_id)
    try:
        return query.with_for_update().first()
    except Exception:  # noqa: BLE001 - sqlite has no FOR UPDATE semantics issues
        return query.first()


def _claim(capture_id: str) -> dict[str, Any] | None:
    from app.models.db.base import get_session

    with get_session() as session:
        job = _lock(session, capture_id)
        if job is None or job.status != STATUS_QUEUED:
            return None
        job.status, job.progress, job.error = STATUS_RUNNING, 2, ""
        job.started_at, job.finished_at = datetime.now(timezone.utc), None
        return {
            "user_id": str(job.user_id),
            "kind": job.source_kind,
            "url": job.source_url,
            "options": dict(job.options or {}),
        }


def _record(capture_id: str, **fields: Any) -> str:
    """Apply ``fields`` unless the job was canceled; returns the current status."""
    from app.models.db.base import get_session

    with get_session() as session:
        job = _lock(session, capture_id)
        if job is None:
            return STATUS_CANCELED
        if job.status == STATUS_CANCELED:
            return STATUS_CANCELED
        for key, value in fields.items():
            setattr(job, key, value)
        return job.status


def _register_asset(user_id: str, capture_id: str, key: str, kind: str, content_type: str, path: str, **extra: Any) -> None:
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import AssetRepository

        ext = os.path.splitext(key)[1]
        with get_session() as session:
            AssetRepository(session).create(
                user_id=user_id, kind=kind, r2_key=key, content_type=content_type,
                size_bytes=os.path.getsize(path), **extra,
                meta={"filename": f"capture-{capture_id[:8]}{ext}", "source": "capture",
                      "capture_id": capture_id, "upload_state": "registered"},
            )
    except Exception as exc:  # noqa: BLE001 - the video still exists without the library row
        logger.warning(f"capture {capture_id}: could not register asset {key}: {exc}")


def _image_size(path: str) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return int(img.width), int(img.height)
    except Exception:  # noqa: BLE001
        return 0, 0


def _upload(r2: Any, path: str, ext: str, content_type: str) -> str:
    key = f"uploads/{uuid.uuid4().hex}{ext}"
    r2.put_file(path, key, content_type=content_type)
    return key


# --------------------------------------------------------------------------- #
# Capture kinds
# --------------------------------------------------------------------------- #
Progress = Callable[[int], None]


def _publish_video(ctx: dict[str, Any], r2: Any, path: str, aspect: str, duration: float, work: str) -> dict[str, Any]:
    from app.domains.adstudio.render import extract_poster

    key = _upload(r2, path, ".mp4", "video/mp4")
    _register_asset(ctx["user_id"], ctx["id"], key, "video", "video/mp4", path, duration_s=duration)
    poster_key = ""
    poster = os.path.join(work, f"poster-{aspect.replace(':', 'x')}.jpg")
    if extract_poster(path, poster, at_s=min(1.5, max(0.1, duration / 3))):
        poster_key = _upload(r2, poster, ".jpg", "image/jpeg")
    return {"aspect": aspect, "key": key, "poster_key": poster_key, "duration_ms": int(duration * 1000)}


def _publish_shots(ctx: dict[str, Any], r2: Any, shots: list[tuple[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, label in shots[:8]:
        if not os.path.isfile(path):
            continue
        width, height = _image_size(path)
        key = _upload(r2, path, ".jpg", "image/jpeg")
        _register_asset(ctx["user_id"], ctx["id"], key, "image", "image/jpeg", path)
        out.append({"key": key, "width": width, "height": height, "label": label})
    return out


def _device_lock(key: str) -> threading.Lock:
    with _POOL_LOCK:
        return _DEVICE_LOCKS.setdefault(key, threading.Lock())


def _capture_native(ctx: dict[str, Any], r2: Any, work: str, progress: Progress) -> dict[str, Any]:
    """Record a native game from the simulator/emulator named in ``options.native``."""
    from app.domains.capture.native import NativeCaptureError, NativeTargetError, parse_target, record_native

    options = ctx["options"]
    try:
        target = parse_target(options.get("native"))
    except NativeTargetError as exc:
        raise CaptureFailed(str(exc)) from exc
    duration = float(options.get("duration_s") or 30)
    formats = list(options.get("formats") or ["9:16"])
    progress(5)
    lock = _device_lock(f"{target.platform}:{target.device}")
    if not lock.acquire(timeout=duration * 4 + 60):
        raise CaptureFailed("the device is busy with another recording; retry in a minute")
    try:
        recording = record_native(target, duration, work, capture_id=ctx["id"])
    except NativeCaptureError as exc:
        raise CaptureFailed(str(exc)) from exc
    finally:
        lock.release()
    progress(50)
    outputs: list[dict[str, Any]] = []
    start, length = encode.trim_seconds(recording.recorded_s, 0.0, duration)
    for index, aspect in enumerate(formats):
        out_path = os.path.join(work, f"capture-{aspect.replace(':', 'x')}.mp4")
        seconds = encode.finalize_recording(recording.video_path, out_path, aspect, trim_start=start, max_seconds=length)
        outputs.append(_publish_video(ctx, r2, out_path, aspect, seconds, work))
        progress(50 + int(45 * (index + 1) / len(formats)))
    return {"outputs": outputs, "screenshots": _publish_shots(ctx, r2, recording.screenshots),
            "meta": {"page": recording.page_meta}}


def _capture_browser(ctx: dict[str, Any], r2: Any, work: str, progress: Progress) -> dict[str, Any]:
    from app.domains.capture.website import record_website

    options = ctx["options"]
    recorder = record_website
    duration = float(options.get("duration_s") or 20)
    formats = list(options.get("formats") or ["9:16"])
    outputs: list[dict[str, Any]] = []
    shots: list[tuple[str, str]] = []
    page_meta: dict[str, Any] = {}
    for index, aspect in enumerate(formats):
        progress(5 + int(85 * index / len(formats)))
        recording = recorder(ctx["url"], aspect, duration, work, seed=ctx["seed"], cursor=bool(options.get("cursor", True)))
        page_meta = page_meta or recording.page_meta
        shots.extend(recording.screenshots)
        start, length = encode.trim_seconds(recording.recorded_s + recording.lead_in_s, recording.lead_in_s, duration)
        out_path = os.path.join(work, f"capture-{aspect.replace(':', 'x')}.mp4")
        seconds = encode.finalize_recording(recording.video_path, out_path, aspect, trim_start=start, max_seconds=length)
        outputs.append(_publish_video(ctx, r2, out_path, aspect, seconds, work))
    return {"outputs": outputs, "screenshots": _publish_shots(ctx, r2, shots), "meta": {"page": page_meta}}


def _capture_store(ctx: dict[str, Any], r2: Any, work: str, progress: Progress) -> dict[str, Any]:
    from app.domains.adstudio.render import render_ad
    from app.domains.capture import store
    from app.domains.capture.slideshow import plan_slides
    from app.domains.capture.sources import apple_ref, play_ref

    if ctx["kind"] == KIND_APP_STORE:
        ref = apple_ref(ctx["url"]) or {}
        listing = store.fetch_app_store(ref)
    else:
        ref = play_ref(ctx["url"]) or {}
        listing = store.fetch_play_store(ref)
    progress(15)
    icon = store.download_image(listing["icon_url"], os.path.join(work, "icon.jpg")) if listing.get("icon_url") else None
    screenshots: list[str] = []
    for index, url in enumerate(listing.get("screenshots") or []):
        path = store.download_image(url, os.path.join(work, f"store-{index}.jpg"))
        if path:
            screenshots.append(path)
    if not icon and not screenshots:
        raise CaptureFailed("the listing has no icon or screenshots we could download")
    images = ([icon] if icon else []) + screenshots
    segments = plan_slides(listing, bool(icon), len(screenshots))
    progress(30)
    formats = list(ctx["options"].get("formats") or ["9:16"])
    outputs: list[dict[str, Any]] = []
    for index, aspect in enumerate(formats):
        seg_dir = os.path.join(work, f"seg-{aspect.replace(':', 'x')}")
        os.makedirs(seg_dir, exist_ok=True)
        out_path = os.path.join(work, f"slideshow-{aspect.replace(':', 'x')}.mp4")
        seconds = render_ad(images, segments, aspect, out_path, seg_dir)
        outputs.append(_publish_video(ctx, r2, out_path, aspect, seconds, work))
        progress(30 + int(60 * (index + 1) / len(formats)))
    shots = [(p, "store screenshot") for p in screenshots[:4]]
    if icon:
        shots.insert(0, (icon, "icon"))
    return {"outputs": outputs, "screenshots": _publish_shots(ctx, r2, shots), "meta": {"listing": listing}}


def _expected_errors() -> tuple[type[BaseException], ...]:
    from app.domains.adstudio.render import RenderError
    from app.domains.capture.browser import CaptureBrowserError
    from app.domains.capture.store import StoreError

    return (CaptureFailed, CaptureBrowserError, encode.EncodeError, RenderError, StoreError)


def _error_text(exc: BaseException) -> str:
    return str(getattr(exc, "message", "") or exc)[:500]


def _seed(capture_id: str) -> int:
    try:
        return int(capture_id[:8], 16)
    except ValueError:
        return 7


def run_capture(capture_id: str) -> dict[str, Any]:
    """Run one capture end to end. Never raises."""
    try:
        job = _claim(capture_id)
    except Exception as exc:  # noqa: BLE001 - DB outage
        logger.error(f"capture claim failed for {capture_id}: {exc}")
        return {"ok": False, "error": "could not claim the capture"}
    if job is None:
        return {"ok": False, "error": "capture is not queued"}
    ctx = {**job, "id": capture_id, "seed": _seed(capture_id)}
    work = tempfile.mkdtemp(prefix=f"capture-{capture_id[:8]}-")

    def progress(value: int) -> None:
        if _record(capture_id, progress=max(1, min(99, int(value)))) == STATUS_CANCELED:
            raise CaptureFailed("canceled")

    try:
        from app.platform.storage.r2 import get_r2_client

        r2 = get_r2_client()
        if ctx["kind"] in LEGACY_KINDS:
            raise CaptureFailed("web game capture was removed; start a native game capture instead")
        if ctx["kind"] in (KIND_APP_STORE, KIND_PLAY_STORE):
            result = _capture_store(ctx, r2, work, progress)
        elif ctx["kind"] == KIND_NATIVE_GAME:
            result = _capture_native(ctx, r2, work, progress)
        else:
            result = _capture_browser(ctx, r2, work, progress)
        outputs = result["outputs"]
        if not outputs:
            raise CaptureFailed("nothing was recorded")
        meta = {**result["meta"], "outputs": outputs}
        page = meta.get("page") or {}
        if page.get("capture_mode"):
            meta["capture_mode"] = page["capture_mode"]
        _record(
            capture_id, status=STATUS_SUCCEEDED, progress=100, output_video_key=outputs[0]["key"],
            screenshots=result["screenshots"], meta=meta, error="", finished_at=datetime.now(timezone.utc),
        )
        return {"ok": True, "capture_id": capture_id, "outputs": len(outputs)}
    except _expected_errors() as exc:
        message = _error_text(exc)
        if message != "canceled":
            _safe_fail(capture_id, message)
        return {"ok": False, "error": message}
    except Exception as exc:  # noqa: BLE001 - storage/unexpected failures
        logger.error(f"capture crashed for {capture_id}: {type(exc).__name__}: {exc}")
        _safe_fail(capture_id, "the capture failed unexpectedly; retry it")
        return {"ok": False, "error": "capture crashed"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _safe_fail(capture_id: str, message: str) -> None:
    try:
        _record(capture_id, status=STATUS_FAILED, error=message[:500], finished_at=datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - nothing more we can do
        logger.error(f"capture could not record failure for {capture_id}: {exc}")


__all__ = ["STALE_CAPTURE_S", "CaptureFailed", "dispatch_capture", "run_capture"]
