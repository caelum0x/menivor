"""Resolve a finished render the caller owns into bytes or a Buffer asset URL.

The client never supplies a URL. Reel jobs, GPU renders and media-gateway
jobs are looked up by id and owner. Buffer needs a URL it can fetch when the
post goes out (no upload API); a presigned link is only used for "post now".
Typefully receives the file bytes.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.domains.x_scheduler.errors import SchedulerError
from app.domains.x_scheduler.http import ProviderHTTPError, default_transport
from app.models.const import TASK_STATE_COMPLETE

MAX_BYTES = 32 * 1024 * 1024
_IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_VIDEO = {".mp4", ".mov", ".webm"}
_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


@dataclass
class MediaAsset:
    kind: str
    filename: str
    content_type: str
    key: str | None = None
    url: str | None = None


def resolve(session: Session, user_id: str, source: str, source_id: str) -> MediaAsset:
    source_id = str(source_id or "").strip()
    if source == "reel":
        return _reel(session, user_id, source_id)
    if source == "render":
        return _render(session, user_id, source_id)
    if source == "media":
        return _media(session, user_id, source_id)
    raise SchedulerError(400, "source must be reel, render, or media")


def buffer_asset_url(asset: MediaAsset, when: str) -> tuple[str, str]:
    """Return ``(url, note)``. Queue and dated posts need a stable URL."""
    stable = _stable_url(asset)
    if stable:
        return stable, ""
    if when != "now":
        raise SchedulerError(
            422,
            "Buffer downloads the file when the post goes out, and this render only has a "
            "temporary link. Post now, send it through Typefully (that uploads the file), "
            "or set R2_PUBLIC_BASE_URL so Buffer gets a stable URL. Nothing was posted.",
        )
    temporary = _temporary_url(asset)
    if not temporary:
        raise SchedulerError(422, "This render has no media Buffer can fetch. Nothing was posted.")
    return temporary, (
        "Buffer downloads the file when the post goes out. This link is temporary, "
        "so a delayed send can fail."
    )


def read_bytes(asset: MediaAsset) -> bytes:
    if asset.key:
        return _read_key(asset.key)
    if asset.url and asset.url.lower().startswith("https://"):
        return _read_url(asset.url)
    raise SchedulerError(422, "This render has no file to upload. Nothing was posted.")


def _reel(session: Session, user_id: str, job_id: str) -> MediaAsset:
    from app.models.db.models import Job

    job = session.get(Job, job_id)
    if job is None or job.user_id != user_id:
        raise SchedulerError(404, "That reel was not found.")
    if int(job.state or 0) != TASK_STATE_COMPLETE or not (job.result_key or "").strip():
        raise SchedulerError(422, "That reel is not finished yet.")
    key = job.result_key.strip()
    return _from_ref(key, fallback_name="reel.mp4")


def _render(session: Session, user_id: str, render_id: str) -> MediaAsset:
    from app.models.db.render import RenderJob

    row = session.get(RenderJob, render_id)
    if row is None or row.user_id != user_id:
        raise SchedulerError(404, "That render was not found.")
    if (row.state or "") != "COMPLETED":
        raise SchedulerError(422, "That render is not finished yet.")
    for ref in (row.output_refs or "").split("\n"):
        ref = ref.strip()
        if not ref:
            continue
        try:
            return _from_ref(ref, fallback_name="render.mp4")
        except SchedulerError:
            continue
    raise SchedulerError(422, "That render finished without a video or image to attach.")


def _media(session: Session, user_id: str, media_id: str) -> MediaAsset:
    from app.models.db.media_jobs import MediaJob

    row = session.get(MediaJob, media_id)
    if row is None or row.user_id != user_id:
        raise SchedulerError(404, "That generation was not found.")
    if (row.status or "") != "completed":
        raise SchedulerError(422, "That generation is not finished yet.")
    if (row.modality or "") not in {"image", "video"}:
        raise SchedulerError(422, "Only a finished image or video can be posted to X.")
    ref = (row.output_url or "").strip()
    if not ref:
        raise SchedulerError(422, "That generation has no file to attach.")
    fallback = "image.png" if row.modality == "image" else "video.mp4"
    return _from_ref(ref, fallback_name=fallback)


def _from_ref(ref: str, *, fallback_name: str) -> MediaAsset:
    from app.services.render.outputs import classify_ref

    kind_ref, value = classify_ref(ref)
    if kind_ref == "unusable":
        raise SchedulerError(422, "That file cannot be attached.")
    filename, content_type, kind = _describe(value, fallback_name)
    if kind_ref == "key":
        return MediaAsset(kind=kind, filename=filename, content_type=content_type, key=value)
    return MediaAsset(kind=kind, filename=filename, content_type=content_type, url=value)


def _describe(ref: str, fallback_name: str) -> tuple[str, str, str]:
    path = urlsplit(ref).path if "://" in ref else ref
    name = path.rsplit("/", 1)[-1] or fallback_name
    ext = ""
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1].lower()
    content_type = mimetypes.guess_type(name)[0] or ""
    if ext not in _IMAGE | _VIDEO:
        ext = _TYPE_EXT.get(content_type, "")
        name = f"{fallback_name.rsplit('.', 1)[0]}{ext}" if ext else fallback_name
    if ext in _IMAGE:
        return _safe_name(name, ext), content_type or "image/jpeg", "image"
    if ext in _VIDEO:
        return _safe_name(name, ext), content_type or "video/mp4", "video"
    raise SchedulerError(422, "X posts from here need an image (jpg, png, gif, webp) or a video (mp4, mov).")


def _safe_name(name: str, ext: str) -> str:
    stem = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in name.rsplit(".", 1)[0])[:80] or "media"
    return f"{stem}{ext}"


def _stable_url(asset: MediaAsset) -> str | None:
    if asset.url and asset.url.lower().startswith("https://") and not _signed(asset.url):
        return asset.url
    if not asset.key:
        return None
    try:
        from app.platform.storage.r2 import get_r2_client

        return get_r2_client().public_url(asset.key)
    except Exception:  # noqa: BLE001 - no public base, or R2 is not configured
        return None


def _temporary_url(asset: MediaAsset) -> str | None:
    if asset.url and asset.url.lower().startswith("https://"):
        return asset.url
    if not asset.key:
        return None
    try:
        from app.platform.storage.r2 import get_r2_client

        return get_r2_client().presign_result_get(asset.key)
    except Exception as exc:  # noqa: BLE001
        raise SchedulerError(422, "Could not build a media link for Buffer. Nothing was posted.") from exc


def _signed(url: str) -> bool:
    query = urlsplit(url).query.lower()
    return any(token in query for token in ("x-amz-", "x-goog-", "signature=", "expires="))


def _read_key(key: str) -> bytes:
    try:
        from app.platform.storage.r2 import get_r2_client

        client = get_r2_client()
        obj = client._s3.get_object(Bucket=client._bucket, Key=key.lstrip("/"))
        data = obj["Body"].read(MAX_BYTES + 1)
    except SchedulerError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SchedulerError(422, "Could not read that render from storage. Nothing was posted.") from exc
    if len(data) > MAX_BYTES:
        raise SchedulerError(422, "That file is over 32 MB, which is too large to upload from here. Nothing was posted.")
    if not data:
        raise SchedulerError(422, "That render file is empty. Nothing was posted.")
    return data


def _read_url(url: str) -> bytes:
    from app.services.render.outputs import classify_ref

    if classify_ref(url)[0] != "url":
        raise SchedulerError(422, "That media URL is not reachable. Nothing was posted.")
    try:
        status, raw = default_transport("GET", url, {}, None)
    except ProviderHTTPError as exc:
        raise SchedulerError(502, "Could not download the finished render. Nothing was posted.") from exc
    if status != 200:
        raise SchedulerError(422, "Could not download the finished render. Nothing was posted.")
    if len(raw) > MAX_BYTES:
        raise SchedulerError(422, "That file is over 32 MB, which is too large to upload from here. Nothing was posted.")
    if not raw:
        raise SchedulerError(422, "That render file is empty. Nothing was posted.")
    return raw
