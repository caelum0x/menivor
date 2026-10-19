"""On-demand publish service for ReelForge job outputs.

A thin, standalone service that re-publishes an *already-rendered* job's final
video to social platforms after the fact (the in-pipeline ``stage_upload`` only
runs when platforms were requested at job-creation time). It reuses:

* :func:`app.services.upload_post.cross_post_video` for the actual cross-post,
* :func:`app.services.llm.generate_social_metadata` for title/caption/hashtags,
* :mod:`app.services.storage.r2` to presign + download the stored final output,
* :func:`app.telemetry.events.record_event` to append ``JobEvent`` audit rows.

Design notes
------------
* **Import-safe.** The persistence layer (SQLAlchemy) is pulled in through a
  guarded block so merely importing this module never crashes app startup;
  :func:`publish_job_output` raises a clear ``RuntimeError`` at call time when
  the DB layer is absent (the controller surfaces it as a ``503``).
* **Never leak an exception silently.** External I/O (R2 download, upload-post)
  is wrapped; failures record a ``failed`` ``JobEvent`` and are re-raised with
  context so the caller can render a typed error.
* **Best-effort telemetry.** ``record_event`` returning ``None`` is tolerated.
"""

from __future__ import annotations

import os
import tempfile

from loguru import logger

from app.models import const

# --------------------------------------------------------------------------- #
# Guarded persistence-layer import (authored by sibling agents; may be absent
# at compile time). Keeps this module import-safe.
# --------------------------------------------------------------------------- #
try:
    from app.models.db.base import get_session
    from app.models.db.models import Asset, Job

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    get_session = None  # type: ignore[assignment]
    Asset = Job = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


_PUBLISH_STAGE: str = "publish"
_DEFAULT_YOUTUBE_PRIVACY: str = "private"
_DOWNLOAD_TIMEOUT_S: int = 300
_MAX_TITLE_LEN: int = 100


class PublishError(RuntimeError):
    """Raised when a job's output cannot be resolved or published."""


def _record(job_id: str, status: str, message: str = "", payload: dict | None = None) -> None:
    """Best-effort ``JobEvent`` write for the ``publish`` stage (never raises)."""
    try:
        from app.telemetry.events import record_event

        record_event(job_id, _PUBLISH_STAGE, status, message=message, payload=payload)
    except Exception as exc:  # noqa: BLE001 - telemetry must not break publishing
        logger.warning(f"[{job_id}] failed to record publish event ({status}): {exc}")


def _load_job_snapshot(job_id: str) -> dict:
    """Resolve the job's final output key + publish params from the DB.

    Returns a plain (JSON-safe) snapshot so no live ORM object escapes the
    session. Raises :class:`PublishError` when the job is missing, not complete,
    or has no resolvable final output.
    """
    with get_session() as session:  # type: ignore[misc]
        job = session.get(Job, job_id)
        if job is None:
            raise PublishError(f"job not found: {job_id}")
        if job.state != const.TASK_STATE_COMPLETE:
            raise PublishError(f"job is not complete (state={job.state}): {job_id}")
        # MN5: a video soft-blocked after a content report is not published either.
        from app.domains.compliance.takedown import BLOCKED_MESSAGE, is_blocked

        if is_blocked(str(job_id)):
            raise PublishError(BLOCKED_MESSAGE)

        final_key = str(getattr(job, "result_key", "") or "").strip()
        if not final_key:
            asset = (
                session.query(Asset)
                .filter(Asset.job_id == job_id, Asset.kind == "final")
                .order_by(Asset.created_at.desc())
                .first()
            )
            if asset is not None:
                final_key = str(getattr(asset, "r2_key", "") or "").strip()
        if not final_key:
            raise PublishError(f"job has no final output to publish: {job_id}")

        params = dict(getattr(job, "params", {}) or {})
        return {
            "user_id": job.user_id,
            "final_key": final_key,
            "video_subject": str(params.get("video_subject", "") or ""),
            "video_script": str(params.get("video_script", "") or ""),
            "language": str(params.get("language", "auto") or "auto"),
            "params_privacy": str(
                params.get("youtube_privacy_status", "") or ""
            ),
        }


def _download_final(final_key: str, job_id: str) -> str:
    """Presign + stream the final R2 object to a local temp mp4; return path."""
    import requests

    from app.services.storage.r2 import get_r2_client

    url = get_r2_client().presign_get(final_key)
    fd, local_path = tempfile.mkstemp(prefix=f"publish_{job_id}_", suffix=".mp4")
    try:
        with requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
            resp.raise_for_status()
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
    except Exception:
        # mkstemp created the file; clean it up on any download failure.
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
        raise
    logger.info(f"[{job_id}] downloaded final output to {local_path}")
    return local_path


def _build_youtube_extra(
    metadata: dict, platforms: list[str], privacy_status: str
) -> dict | None:
    """Assemble the ``youtube_extra`` payload only when a YouTube target exists."""
    if not any(str(p).startswith("youtube") for p in platforms):
        return None
    return {
        "youtube_title": str(metadata.get("title", ""))[:_MAX_TITLE_LEN],
        "youtube_description": str(metadata.get("caption", "")),
        "tags": list(metadata.get("hashtags", []) or []),
        "privacyStatus": privacy_status,
    }


def publish_job_output(
    job_id: str,
    platforms: list[str],
    youtube_privacy_status: str | None = None,
) -> dict:
    """Publish a completed job's final video to ``platforms`` on demand.

    Loads the job's final output key from the DB (``Job.result_key`` falling
    back to the newest ``Asset(kind="final")``), presigns + downloads it from
    R2, generates social metadata, cross-posts it, and records ``JobEvent``
    rows for the ``publish`` stage.

    Args:
        job_id: The completed job to publish.
        platforms: Target platforms (e.g. ``["tiktok", "youtube"]``).
        youtube_privacy_status: Optional YouTube privacy override; falls back to
            the job's stored value then ``"private"``.

    Returns:
        A JSON-safe results dict:
        ``{job_id, platforms, success, request_id, metadata, results}``.

    Raises:
        RuntimeError: When the persistence layer is unavailable.
        PublishError: When the job is missing / not complete / has no output.
    """
    if _DB_IMPORT_ERROR is not None or get_session is None:
        raise RuntimeError(
            f"persistence layer is not available: {_DB_IMPORT_ERROR}"
        )

    platforms = [str(p).strip() for p in (platforms or []) if str(p).strip()]
    if not platforms:
        raise PublishError("at least one platform is required to publish")

    snapshot = _load_job_snapshot(job_id)
    privacy = (
        str(youtube_privacy_status).strip()
        if youtube_privacy_status
        else (snapshot["params_privacy"] or _DEFAULT_YOUTUBE_PRIVACY)
    )

    _record(
        job_id,
        const.REELFORGE_STAGE_RUNNING,
        message=f"publishing to {', '.join(platforms)}",
        payload={"platforms": platforms},
    )

    local_path: str | None = None
    try:
        local_path = _download_final(snapshot["final_key"], job_id)

        # Social metadata (title/caption/hashtags). Never fatal — the LLM helper
        # already falls back to a heuristic, so this always returns a usable dict.
        from app.services.llm import generate_social_metadata

        metadata = generate_social_metadata(
            video_subject=snapshot["video_subject"] or "ReelForge video",
            video_script=snapshot["video_script"],
            language=snapshot["language"],
            platform=platforms[0],
        )
        title = (str(metadata.get("title", "")).strip() or "ReelForge video")[
            :_MAX_TITLE_LEN
        ]

        from app.services.upload_post import cross_post_video

        raw = cross_post_video(
            local_path,
            title,
            platforms=platforms,
            youtube_extra=_build_youtube_extra(metadata, platforms, privacy),
        )
        if not isinstance(raw, dict):
            raise PublishError("cross_post_video returned no result")

        success = bool(raw.get("success", False))
        request_id = str(raw.get("request_id", "") or "")
        results = {
            "job_id": job_id,
            "platforms": platforms,
            "success": success,
            "request_id": request_id,
            "metadata": metadata,
            "results": raw,
        }

        if success:
            _record(
                job_id,
                const.REELFORGE_STAGE_COMPLETE,
                message=f"published (request_id={request_id or 'n/a'})",
                payload={"platforms": platforms, "request_id": request_id},
            )
            logger.success(
                f"[{job_id}] published to {', '.join(platforms)} "
                f"request_id={request_id or 'n/a'}"
            )
        else:
            reason = str(raw.get("message") or raw.get("error") or "unknown")
            _record(
                job_id,
                const.REELFORGE_STAGE_FAILED,
                message=f"publish failed: {reason}",
                payload={"platforms": platforms, "reason": reason},
            )
            logger.warning(f"[{job_id}] publish reported failure: {reason}")
        return results
    except Exception as exc:
        _record(
            job_id,
            const.REELFORGE_STAGE_FAILED,
            message=f"publish error: {exc}",
            payload={"platforms": platforms},
        )
        logger.error(f"[{job_id}] publish_job_output failed: {exc}")
        raise
    finally:
        if local_path:
            try:
                os.remove(local_path)
            except OSError:  # pragma: no cover - best-effort cleanup
                pass
