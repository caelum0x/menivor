"""ReelForge Cover / Thumbnail Generator v1 API controller.

Adds one on-demand endpoint under ``/api/v1`` that lets a creator render a
custom cover image for a reel:

* ``POST /jobs/{job_id}/cover`` — render a 1080x1920 JPG cover for an *owned*
  job (auth + ownership). The headline is either supplied by the caller or
  derived from the job's script hook / ``video_subject`` param; the job's poster
  frame (``poster_key``, else a style gradient) is the background. The rendered
  JPG is uploaded to R2 (``jobs/{job_id}/cover.jpg``), its key persisted on
  ``Job.cover_key`` via :meth:`JobRepository.set_cover`, and a presigned GET URL
  returned. Regenerable — a new headline/style simply overwrites the key.

Design notes
------------
* **DRY + import-safe.** Reuses the guarded persistence import and the auth
  helpers (``_require_db`` / ``_resolve_user`` / ``get_session`` / ``Job`` /
  ``JobRepository``) from :mod:`app.controllers.v1.jobs`, which owns the
  canonical guard block. A missing DB layer degrades to a clean ``503`` rather
  than an import crash.
* **Pure Pillow rendering** is delegated to :mod:`app.services.cover`; that
  module import-guards ``from PIL import ...`` so this controller still
  ``py_compile``\\s even without Pillow (which is installed in the venv).
* **Temp files are always cleaned up** (a per-request temp dir is removed in a
  ``finally`` block). A poster download failure degrades to the style gradient
  rather than failing the request.
* Every response uses the MPT envelope ``utils.get_response`` and every error is
  raised as :class:`HttpException`.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import tempfile
import urllib.request
from typing import Any

from fastapi import Path, Request
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router

# Reuse the guarded persistence import + auth helpers from jobs.py (the module
# that owns the canonical guard). When the DB layer is absent these are ``None``
# and ``_require_db`` raises a 503.
from app.controllers.v1.jobs import (
    Job,
    JobRepository,
    _require_db,
    _resolve_user,
    get_session,
)
from app.models.exception import HttpException
from app.models.schema import CoverRequest, CoverResponse
from app.services import cover
from app.utils import utils

router = new_router()

# R2 key template for a job's generated cover. One key per job so regenerating
# with a new headline/style overwrites the previous cover in place.
_COVER_KEY_TEMPLATE: str = "jobs/{job_id}/cover.jpg"
_COVER_CONTENT_TYPE: str = "image/jpeg"
# Bound on the poster download so a pathological / wrong object cannot stream
# unbounded bytes into the request's temp dir.
_MAX_POSTER_BYTES: int = 25 * 1024 * 1024  # 25 MiB


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _resolve_headline(
    supplied: str | None, script: str, params: dict[str, Any]
) -> str:
    """Pick the cover headline.

    Priority: the caller-supplied ``headline`` (trimmed), else the job's script
    *hook* (its first non-empty line — UGC scripts persist ``hook + segments +
    cta``), else the job's ``video_subject`` param. Returns ``""`` when nothing
    is available (the renderer then draws just the styled background + scrim).
    """
    given = (supplied or "").strip()
    if given:
        return given

    for line in (script or "").splitlines():
        candidate = line.strip()
        if candidate:
            return candidate

    return str(params.get("video_subject", "") or "").strip()


def _download_poster(poster_key: str, dest_path: str, request_id: str) -> None:
    """Download the job's poster object from R2 to ``dest_path``.

    Uses a short-lived presigned GET URL (public interface only) and streams the
    body to disk with a hard byte cap. Raises on any failure so the caller can
    decide to degrade to the style gradient.
    """
    from app.services.storage.r2 import get_r2_client

    url = get_r2_client().presign_get(poster_key)
    # A read timeout keeps a stalled R2 transfer from holding the worker thread
    # open forever; 30s is generous for a <=25 MiB object.
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - presigned R2 URL
        with open(dest_path, "wb") as out:
            written = 0
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_POSTER_BYTES:
                    raise ValueError(
                        f"poster {poster_key!r} exceeds {_MAX_POSTER_BYTES} bytes"
                    )
                out.write(chunk)
    logger.debug(
        f"downloaded poster {poster_key!r} for cover render, request_id: {request_id}"
    )


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
@router.post(
    "/jobs/{job_id}/cover",
    response_model=CoverResponse,
    summary="Generate a cover/thumbnail for a job",
)
def generate_job_cover(
    request: Request,
    body: CoverRequest,
    job_id: str = Path(..., description="Job ID"),
):
    """Render + persist a cover image for an owned job.

    Order: auth -> ownership (404 on unknown/foreign job) -> style validation
    (400 on unknown style) -> rank catalog styles for the headline (Jev cover
    ranker; auto-picks the winner when no style was supplied) -> render (poster or
    gradient background + headline) -> upload to R2 -> persist ``cover_key`` ->
    return ``{cover_key, cover_url, style, auto_selected, recommendation}``. Temp
    files are always cleaned up.
    """
    request_id = base.get_task_id(request)
    _require_db(request_id)

    # An explicitly supplied style is validated up front so an unknown style is a
    # clean 400 (cover.get_cover_style would otherwise silently fall back to the
    # default). When the caller omits the style we auto-select one below, after
    # the headline + poster are known.
    supplied_style = (body.style or "").strip()
    if supplied_style and supplied_style not in cover.COVER_STYLES:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: unknown cover style {supplied_style!r}",
        )

    # Auth + ownership, then snapshot the fields we need outside the session.
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        job = session.get(Job, job_id)
        if job is None or job.user_id != user.id:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: job not found",
            )
        poster_key = str(getattr(job, "poster_key", "") or "").strip()
        script = str(getattr(job, "script", "") or "")
        params = dict(getattr(job, "params", {}) or {})

    headline = _resolve_headline(body.headline, script, params)

    # Rank every catalog style for this headline with the Jev-scored cover ranker
    # (generates one candidate cover per style). The full ranked list is surfaced
    # in the response so the UI can show *why* one style wins; a missing headline
    # leaves nothing to rank. Any failure (no key, ranker error) is non-fatal.
    topic = str(params.get("video_subject", "") or "").strip()
    recommendation: cover.CoverRecommendation | None = None
    if headline:
        try:
            recommendation = cover.recommend_cover(
                headline, has_poster=bool(poster_key), topic=topic
            )
        except Exception as exc:  # noqa: BLE001 - recommendation is best-effort
            logger.warning(
                f"cover recommendation failed for job {job_id}, request_id: "
                f"{request_id}: {exc}"
            )

    # Resolve the final style: honor an explicit style verbatim; otherwise
    # auto-select the ranker's winning style. When no live recommendation is
    # available (no headline, no key, or a ranker error) fall back to
    # DEFAULT_STYLE_ID so cover generation never depends on a recommendation.
    auto_selected = False
    if supplied_style:
        style_id = supplied_style
    elif (
        recommendation is not None
        and not recommendation.degraded
        and recommendation.recommended_style in cover.COVER_STYLES
    ):
        style_id = recommendation.recommended_style
        auto_selected = True
    else:
        style_id = cover.DEFAULT_STYLE_ID

    work_dir = tempfile.mkdtemp(prefix="reelforge_cover_")
    out_path = os.path.join(work_dir, "cover.jpg")
    try:
        # 1) Optional poster background (degrade to gradient on any failure).
        base_image_path: str | None = None
        if poster_key:
            candidate = os.path.join(work_dir, "poster")
            try:
                _download_poster(poster_key, candidate, request_id)
                base_image_path = candidate
            except Exception as exc:  # noqa: BLE001 - degrade to gradient, never fatal
                logger.warning(
                    f"poster download failed for job {job_id}, rendering gradient "
                    f"instead, request_id: {request_id}: {exc}"
                )

        # 2) Render the cover JPG.
        try:
            cover.generate_cover(
                headline,
                out_path,
                base_image_path=base_image_path,
                style=style_id,
            )
        except Exception as exc:  # noqa: BLE001 - render failure -> 502
            logger.error(
                f"cover render failed for job {job_id}, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to render cover",
            )

        # 3) Upload to R2 + presign a GET URL for the client.
        cover_key = _COVER_KEY_TEMPLATE.format(job_id=job_id)
        try:
            from app.services.storage.r2 import get_r2_client

            r2 = get_r2_client()
            r2.upload_file(out_path, cover_key, _COVER_CONTENT_TYPE)
            cover_url = r2.presign_result_get(cover_key)
        except Exception as exc:  # noqa: BLE001 - external storage failure -> 502
            logger.error(
                f"cover upload failed for job {job_id}, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to upload cover",
            )

        # 4) Persist the cover key on the job (owner already verified above).
        try:
            with get_session() as session:
                JobRepository(session).set_cover(job_id, cover_key)
        except Exception as exc:  # noqa: BLE001 - persistence failure -> 502
            logger.error(
                f"cover set_cover failed for job {job_id}, request_id: {request_id}: {exc}"
            )
            raise HttpException(
                task_id=request_id,
                status_code=502,
                message=f"{request_id}: failed to persist cover",
            )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    payload: dict[str, Any] = {
        "cover_key": cover_key,
        "cover_url": cover_url,
        "style": style_id,
        "auto_selected": auto_selected,
    }
    if recommendation is not None:
        payload["recommendation"] = dataclasses.asdict(recommendation)
    return utils.get_response(200, payload)
