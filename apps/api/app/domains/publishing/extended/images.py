"""Image posts (Design Studio pages) through the extended publish connectors.

An image post is a normal :class:`~.models.PlatformPost` with an empty
``job_id`` and the R2 keys of its pages in ``progress["image_keys"]``; the
due-runner (:mod:`.posts`) turns those keys into public URLs or local files
right before the connector runs, so a post scheduled days ahead never holds an
expired URL.

Which platforms take images, and how:

* URL ingest (the platform fetches the page): Instagram, Facebook, Threads, Pinterest.
* Byte upload (we send the bytes): X, LinkedIn, Bluesky, Telegram, Discord, Mastodon.
* Not supported, with a per-platform reason: TikTok, YouTube, the app stores,
  websites and "other" (see :data:`UNSUPPORTED`).

Instagram accepts only JPEG, so Instagram posts get JPEG copies of the pages;
Bluesky caps an image blob at about 1 MB, so larger pages are re-encoded as
JPEG at run time.
"""

from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from loguru import logger

from . import repository as repo
from .catalog import AVAILABLE, X, is_channel, server_availability, spec_for, x_monthly_post_cap
from .formats import fit
from .models import CONN_CONNECTED, POST_SCHEDULED

try:
    from app.models.db.base import get_session

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    get_session = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

IMAGE_KEYS = "image_keys"
INSTAGRAM = "instagram"

#: Platforms that fetch the images themselves from a public URL.
URL_INGEST: frozenset[str] = frozenset({INSTAGRAM, "facebook", "threads", "pinterest"})
#: Platforms whose API needs the image bytes uploaded.
BYTE_UPLOAD: frozenset[str] = frozenset({"x", "linkedin", "bluesky", "telegram", "discord", "mastodon"})
IMAGE_PLATFORMS: frozenset[str] = URL_INGEST | BYTE_UPLOAD

#: Most images one post may carry, per platform API.
MAX_IMAGES: dict[str, int] = {
    INSTAGRAM: 10, "facebook": 10, "threads": 20, "pinterest": 5, "x": 4, "linkedin": 20,
    "bluesky": 4, "telegram": 10, "discord": 10, "mastodon": 4,
}
#: Byte ceilings enforced by re-encoding before upload.
MAX_BYTES: dict[str, int] = {"bluesky": 976_000, "x": 5 * 1024 * 1024}
INSTAGRAM_CAPTION_MAX = 2200

UNSUPPORTED: dict[str, str] = {
    "tiktok": "TikTok photo posts are not wired in Menivor yet; post this design from the TikTok app.",
    "youtube": "YouTube does not accept image posts through its API.",
    "app_store": "App Store screenshots are uploaded in App Store Connect; download the PNGs and upload them there.",
    "play_store": "Play Store screenshots are uploaded in the Play Console; download the PNGs and upload them there.",
    "website": "Websites are not a posting destination; download the PNGs and add them to your site.",
    "other": "There is no connector for this destination; download the PNGs and post them yourself.",
}


class ImagePostError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, details: list | None = None) -> None:
        self.status_code = status_code
        self.details = details or []
        super().__init__(message)


def unsupported_reason(platform: str) -> str:
    """``""`` when ``platform`` can publish images, else a plain per-platform reason."""
    key = str(platform or "").strip().lower()
    if key in IMAGE_PLATFORMS:
        return ""
    return UNSUPPORTED.get(key) or f"{key or 'This platform'} does not support image posts in Menivor."


def is_image_post(progress: dict | None) -> bool:
    return bool((progress or {}).get(IMAGE_KEYS))


def image_keys(progress: dict | None) -> list[str]:
    return [str(k) for k in ((progress or {}).get(IMAGE_KEYS) or []) if str(k or "").strip()]


def keep_media(progress: dict | None) -> dict:
    """What a retry/re-queue must keep from ``progress`` (the pages to post)."""
    keys = image_keys(progress)
    return {IMAGE_KEYS: keys, "source": dict((progress or {}).get("source") or {})} if keys else {}


# --------------------------------------------------------------------------- #
# Image bytes
# --------------------------------------------------------------------------- #
def to_jpeg(data: bytes, *, quality: int = 90) -> bytes:
    """Flatten any image onto white and encode as baseline JPEG."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        img.load()
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.split()[-1])
        else:
            flat = img.convert("RGB")
        out = io.BytesIO()
        flat.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


def shrink(data: bytes, max_bytes: int) -> bytes:
    """Return ``data`` unchanged when small enough, else a JPEG under ``max_bytes``."""
    if len(data) <= max_bytes:
        return data
    from PIL import Image

    for quality in (90, 82, 74, 66, 58, 50):
        encoded = to_jpeg(data, quality=quality)
        if len(encoded) <= max_bytes:
            return encoded
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        scaled = img.copy()
    while True:
        scaled.thumbnail((max(1, int(scaled.width * 0.8)), max(1, int(scaled.height * 0.8))))
        buf = io.BytesIO()
        scaled.convert("RGB").save(buf, format="JPEG", quality=70, optimize=True)
        if buf.tell() <= max_bytes or scaled.width < 200:
            return buf.getvalue()


def jpeg_key(key: str) -> str:
    stem = key.rsplit(".", 1)[0] if "." in key.rsplit("/", 1)[-1] else key
    return f"{stem}.jpg"


def jpeg_copies(keys: list[str], *, r2: Any = None) -> list[str]:
    """Store a JPEG copy next to each page (Instagram accepts JPEG only)."""
    if r2 is None:
        from app.platform.storage.r2 import get_r2_client

        r2 = get_r2_client()
    out: list[str] = []
    for key in keys:
        if key.lower().endswith((".jpg", ".jpeg")):
            out.append(key)
            continue
        with tempfile.TemporaryDirectory(prefix="imgpost-") as work:
            local = r2.download_file(key, os.path.join(work, "page"))
            with open(local, "rb") as fh:
                data = fh.read()
        target = jpeg_key(key)
        r2.upload_bytes(target, to_jpeg(data), content_type="image/jpeg")
        out.append(target)
    return out


@dataclass
class PreparedImages:
    urls: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    workdir: str = ""
    cleanup: list[str] = field(default_factory=list)

    def remove(self) -> None:
        for path in self.cleanup:
            try:
                if os.path.isdir(path):
                    import shutil

                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.exists(path):
                    os.remove(path)
            except OSError:  # pragma: no cover
                pass


def prepare(platform: str, keys: list[str], *, r2: Any = None) -> PreparedImages:
    """Presigned URLs (URL ingest) or local files (byte upload) for one post's pages."""
    if r2 is None:
        from app.platform.storage.r2 import get_r2_client

        r2 = get_r2_client()
    if platform in URL_INGEST:
        return PreparedImages(urls=tuple(r2.presign_get(k) for k in keys))
    work = tempfile.mkdtemp(prefix=f"imgpost-{platform}-")
    prepared = PreparedImages(workdir=work, cleanup=[work])
    paths: list[str] = []
    try:
        for index, key in enumerate(keys):
            local = r2.download_file(key, os.path.join(work, f"page{index + 1}"))
            limit = MAX_BYTES.get(platform)
            if limit and os.path.getsize(local) > limit:
                with open(local, "rb") as fh:
                    data = shrink(fh.read(), limit)
                with open(local, "wb") as fh:
                    fh.write(data)
            paths.append(local)
    except Exception:
        prepared.remove()
        raise
    prepared.paths = tuple(paths)
    return prepared


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Destination:
    platform: str
    target_id: str = ""
    label: str = ""


def _instagram_ready(user_id: str) -> str:
    try:
        from app.domains.publishing.native_service import NativePublishError, require_native_connections

        require_native_connections(user_id, [INSTAGRAM])
    except NativePublishError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - token refresh failure reads as "reconnect"
        logger.warning(f"image posts: instagram connection check failed for {user_id}: {exc}")
        return "Reconnect Instagram under Settings -> Connections."
    return ""


def _channel_destinations(user_id: str, kind: str, channel_ids: list[str]) -> tuple[list[Destination], str]:
    from .channels import list_channels

    label = spec_for(kind).label if spec_for(kind) else kind
    usable = [c for c in list_channels(user_id).get("channels", []) if c["kind"] == kind and c["can_post"]]
    if channel_ids:
        usable = [c for c in usable if c["id"] in channel_ids]
    if not usable:
        return [], f"Connect a {label} channel first."
    if len(usable) > 1 and not channel_ids:
        return [], f"You have several {label} channels; choose which ones when scheduling."
    return [Destination(kind, c["id"], c["label"]) for c in usable], ""


def resolve(user_id: str, platforms: list[str], *, channel_ids: list[str] | None = None,
            count: int, caption: str, title: str,
            check_connection: Callable[[str, str], str] | None = None) -> tuple[list[tuple[Destination, Any]], list[dict]]:
    """Split ``platforms`` into ready destinations (with the fitted text) and per-platform problems."""
    ready: list[tuple[Destination, Any]] = []
    problems: list[dict] = []
    for platform in platforms:
        reason = unsupported_reason(platform)
        if not reason and count > MAX_IMAGES.get(platform, 1):
            reason = f"{platform} posts take at most {MAX_IMAGES[platform]} images; this design has {count} pages."
        if reason:
            problems.append({"platform": platform, "message": reason})
            continue
        if platform == INSTAGRAM:
            text = caption.strip()
            if len(text) > INSTAGRAM_CAPTION_MAX:
                problems.append({"platform": platform,
                                 "message": f"Instagram captions are limited to {INSTAGRAM_CAPTION_MAX} characters."})
                continue
            note = (check_connection or (lambda _u, _p: _instagram_ready(_u)))(user_id, platform)
            if note:
                problems.append({"platform": platform, "message": note})
                continue
            ready.append((Destination(platform), text))
            continue
        fitted = fit(platform, caption=caption, title=title)
        if not fitted.ok:
            problems.append({"platform": platform, "message": "; ".join(i.message for i in fitted.issues)})
            continue
        if is_channel(platform):
            dests, note = _channel_destinations(user_id, platform, list(channel_ids or []))
            if note:
                problems.append({"platform": platform, "message": note})
                continue
            ready.extend((d, fitted) for d in dests)
            continue
        server_state, note = server_availability(platform)
        if server_state != AVAILABLE:
            problems.append({"platform": platform, "message": note})
            continue
        note = (check_connection or _oauth_state)(user_id, platform)
        if note:
            problems.append({"platform": platform, "message": note})
            continue
        ready.append((Destination(platform), fitted))
    return ready, problems


def _oauth_state(user_id: str, platform: str) -> str:
    from .connections import connection_state
    from .posts import _month_start, _state_message

    spec = spec_for(platform)
    with get_session() as session:  # type: ignore[misc]
        row = repo.get_connection(session, user_id, platform)
        state = connection_state(platform, row)
        if state != CONN_CONNECTED:
            return _state_message(spec.label if spec else platform, state)
        if platform == X and x_monthly_post_cap():
            if repo.published_count_since(session, X, _month_start(repo.utcnow())) >= x_monthly_post_cap():
                return "This server's monthly X posting budget is used up. Try again next month."
    return ""


def create_image_posts(user_id: str, *, image_keys: list[str], platforms: list[str], caption: str = "",
                       title: str = "", scheduled_at: datetime | None = None, source: dict | None = None,
                       channel_ids: list[str] | None = None, now: datetime | None = None,
                       jpeg: Callable[[list[str]], list[str]] | None = None,
                       check_connection: Callable[[str, str], str] | None = None) -> dict:
    """Queue one image post per ready destination.

    Returns ``{"posts": [...], "skipped": [{"platform", "message"}]}``. Raises
    :class:`ImagePostError` (409, with the per-platform reasons) when no
    destination is ready, so nothing is half-scheduled silently.
    """
    if get_session is None:
        raise ImagePostError(f"publishing persistence unavailable: {_IMPORT_ERROR}", status_code=503)
    from .posts import _enqueue, post_record

    keys = [str(k) for k in image_keys if str(k or "").strip()]
    if not keys:
        raise ImagePostError("export the design before posting it", status_code=409)
    wanted = list(dict.fromkeys(str(p or "").strip().lower() for p in platforms if str(p or "").strip()))
    if not wanted:
        raise ImagePostError("choose at least one place to post")
    moment = now or repo.utcnow()
    when = repo.aware(scheduled_at) or moment
    if when < moment:
        when = moment  # approved after its slot: post now rather than never
    ready, problems = resolve(user_id, wanted, channel_ids=channel_ids, count=len(keys), caption=caption,
                              title=title, check_connection=check_connection)
    if not ready:
        raise ImagePostError("none of the chosen platforms can take this design yet", status_code=409,
                             details=problems)
    jpeg_keys: list[str] = []
    if any(d.platform == INSTAGRAM for d, _ in ready):
        jpeg_keys = (jpeg or jpeg_copies)(keys)
    records: list[dict] = []
    with get_session() as session:  # type: ignore[misc]
        for dest, fitted in ready:
            is_ig = dest.platform == INSTAGRAM
            text = fitted if is_ig else fitted.text
            row = repo.add_post(
                session, user_id=user_id, job_id="", platform=dest.platform, status=POST_SCHEDULED,
                scheduled_at=when, next_attempt_at=when, title=("" if is_ig else fitted.title)[:300] or title[:300],
                text=text, hashtags=[] if is_ig else list(fitted.hashtags), target_id=dest.target_id,
            )
            row.progress = {IMAGE_KEYS: list(jpeg_keys if is_ig else keys), "source": dict(source or {})}
            session.flush()
            records.append({**post_record(row), "channel_label": dest.label} if dest.label else post_record(row))
    if when <= moment + timedelta(seconds=5):
        for record in records:
            _enqueue(record["id"])
    return {"posts": records, "skipped": problems}


__all__ = [
    "BYTE_UPLOAD",
    "IMAGE_KEYS",
    "IMAGE_PLATFORMS",
    "ImagePostError",
    "MAX_IMAGES",
    "PreparedImages",
    "UNSUPPORTED",
    "URL_INGEST",
    "create_image_posts",
    "image_keys",
    "is_image_post",
    "jpeg_copies",
    "keep_media",
    "prepare",
    "resolve",
    "shrink",
    "to_jpeg",
    "unsupported_reason",
]
