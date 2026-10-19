"""Ad variant render execution + dispatch.

:func:`run_variant_render` is the single render entrypoint (never raises; every
failure is recorded on the variant and its credit refunded exactly once).
:func:`dispatch_render` sends the render to the Celery ``render`` queue via
:mod:`app.domains.adstudio.tasks`; FFmpeg never runs inside the API process
(MN1). A broker outage raises :class:`RenderQueueUnavailable` so the caller can
fail the ad and return its credit instead of rendering unpaid work inline.
A worker restart mid-render is recovered by the stale-render sweep on the next
project read (the ad flips to ``failed`` and its credit is returned).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from typing import Any

from loguru import logger

from app.domains.adstudio.render import RenderError, extract_poster, render_ad
from app.domains.adstudio.variants import build_job_request, segments_for

STALE_RENDER_S = 30 * 60
RENDER_QUEUE = "render"


class RenderQueueUnavailable(RuntimeError):
    """The render queue could not accept the job (broker down)."""


def dispatch_render(variant_id: str) -> None:
    """Queue one ad render on the Celery ``render`` queue (never inline)."""
    try:
        from app.domains.adstudio.tasks import render_ad_variant_task

        render_ad_variant_task.apply_async(args=[variant_id], queue=RENDER_QUEUE)
    except Exception as exc:  # noqa: BLE001 - surface; the caller refunds
        logger.error(f"adstudio render dispatch failed for {variant_id}: {exc}")
        raise RenderQueueUnavailable(str(exc)) from exc


def _claim(variant_id: str) -> dict[str, Any] | None:
    """Flip queued -> rendering and snapshot everything the render needs."""
    from app.domains.adstudio.repository import AdStudioRepository
    from app.models.db.base import get_session

    with get_session() as session:
        repo = AdStudioRepository(session)
        variant = repo.lock_variant(variant_id)
        if variant is None or variant.status != "queued":
            return None
        project = repo.get_project(variant.project_id)
        if project is None:
            variant.status, variant.error = "failed", "the project no longer exists"
            _refund_in_session(session, variant)
            return None
        variant.status, variant.error = "rendering", ""
        return {
            "user_id": str(variant.user_id),
            "format": variant.format,
            "aspect": variant.aspect,
            "spec": dict(variant.spec or {}),
            "product": dict(project.product or {}),
            "language": project.language or "en",
            "image_keys": [str(i.get("key")) for i in project.images or [] if isinstance(i, dict) and i.get("key")],
        }


def _record(variant_id: str, **fields: Any) -> None:
    from app.domains.adstudio.repository import AdStudioRepository
    from app.models.db.base import get_session

    with get_session() as session:
        variant = AdStudioRepository(session).lock_variant(variant_id)
        if variant is None:
            return
        for key, value in fields.items():
            setattr(variant, key, value)


def _register_assets(user_id: str, variant_id: str, video_key: str, size: int, duration_s: float, poster_key: str) -> None:
    from app.models.db.base import get_session
    from app.models.db.repositories import AssetRepository

    with get_session() as session:
        repo = AssetRepository(session)
        repo.create(
            user_id=user_id, kind="video", r2_key=video_key, content_type="video/mp4",
            size_bytes=size, duration_s=duration_s,
            meta={"filename": f"ad-{variant_id[:8]}.mp4", "source": "adstudio", "variant_id": variant_id, "upload_state": "registered"},
        )
        if poster_key:
            repo.create(
                user_id=user_id, kind="image", r2_key=poster_key, content_type="image/jpeg",
                meta={"filename": f"ad-{variant_id[:8]}.jpg", "source": "adstudio", "variant_id": variant_id, "upload_state": "registered"},
            )


def run_variant_render(variant_id: str) -> dict[str, Any]:
    """Render one variant end to end. Never raises."""
    job = None
    try:
        job = _claim(variant_id)
    except Exception as exc:  # noqa: BLE001 - DB outage
        logger.error(f"adstudio claim failed for {variant_id}: {exc}")
        return {"ok": False, "error": "could not claim the render"}
    if job is None:
        return {"ok": False, "error": "variant is not queued"}
    work = tempfile.mkdtemp(prefix=f"adstudio-{variant_id[:8]}-")
    try:
        from app.platform.storage.r2 import get_r2_client

        r2 = get_r2_client()
        images: list[str] = []
        for index, key in enumerate(job["image_keys"]):
            path = os.path.join(work, f"img-{index}.jpg")
            r2.download_file(key, path)
            images.append(path)
        angle = job["spec"].get("angle") or {}
        segments = segments_for(job["format"], angle, job["product"], job["language"], len(images))
        out_path = os.path.join(work, "ad.mp4")
        duration = render_ad(images, segments, job["aspect"], out_path, work)
        video_key = f"uploads/{uuid.uuid4().hex}.mp4"
        r2.put_file(out_path, video_key, content_type="video/mp4")
        poster_key = ""
        poster_path = os.path.join(work, "poster.jpg")
        if extract_poster(out_path, poster_path, at_s=min(1.2, duration / 2)):
            poster_key = f"uploads/{uuid.uuid4().hex}.jpg"
            r2.put_file(poster_path, poster_key, content_type="image/jpeg")
        _register_assets(job["user_id"], variant_id, video_key, os.path.getsize(out_path), duration, poster_key)
        spec = dict(job["spec"])
        status = "done"
        if job["format"] == "ugc_avatar":
            options = spec.get("options") or {}
            spec["job_request"] = build_job_request(
                angle=angle, product=job["product"], language=job["language"], aspect=job["aspect"],
                montage_key=video_key, avatar_id=str(options.get("avatar_id") or ""),
                voice_id=str(options.get("voice_id") or ""), caption_style=str(options.get("caption_style") or ""),
            )
            status = "ready"
        _record(variant_id, status=status, output_key=video_key, poster_key=poster_key,
                duration_ms=int(duration * 1000), spec=spec, error="")
        return {"ok": True, "variant_id": variant_id, "status": status}
    except RenderError as exc:
        _safe_fail(variant_id, str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - storage/unexpected failures
        logger.error(f"adstudio render crashed for {variant_id}: {type(exc).__name__}: {exc}")
        _safe_fail(variant_id, "rendering failed unexpectedly; retry it")
        return {"ok": False, "error": "render crashed"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _refund_in_session(session: Any, variant: Any) -> int:
    from app.domains.reels import charge

    return charge.refund_ref_once(
        session, user_id=str(variant.user_id), kind=charge.ADSTUDIO_KIND, ref=str(variant.id),
    )


def fail_and_refund(variant_id: str, message: str) -> int:
    """Mark an ad failed and return its credit, in one transaction. Idempotent."""
    from app.domains.adstudio.repository import AdStudioRepository
    from app.models.db.base import get_session

    with get_session() as session:
        variant = AdStudioRepository(session).lock_variant(variant_id)
        if variant is None:
            return 0
        variant.status, variant.error = "failed", message[:500]
        if variant.output_key:
            return 0
        return _refund_in_session(session, variant)


def _safe_fail(variant_id: str, message: str) -> None:
    try:
        fail_and_refund(variant_id, message)
    except Exception as exc:  # noqa: BLE001 - the next project read retries the refund
        logger.error(f"adstudio could not record failure for {variant_id}: {exc}")


__all__ = [
    "RENDER_QUEUE",
    "RenderQueueUnavailable",
    "STALE_RENDER_S",
    "dispatch_render",
    "fail_and_refund",
    "run_variant_render",
]
