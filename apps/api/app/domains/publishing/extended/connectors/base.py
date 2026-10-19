"""Contracts shared by the extended publish connectors.

A post to these platforms is often multi-step (upload, wait for processing,
then create the post). A connector therefore returns a :class:`Step`: either
the post is live (``published``), still being processed by the platform
(``processing`` - the due-runner calls :meth:`resume` later with the saved
``progress``), or it raised :class:`PublishError`.

The only network seam is the injectable
:class:`~app.domains.publishing.connectors.base.Transport` (``requests`` by
default); tests pass a fake transport and assert the exact requests.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.domains.publishing.connectors.base import (
    HttpResponse,
    PublishError,
    RequestsTransport,
    Transport,
    _ok,
    _safe_json,
)

__all__ = [
    "ExtendedConnector",
    "HttpResponse",
    "PublishContext",
    "PublishError",
    "RequestsTransport",
    "Step",
    "Transport",
    "error_text",
    "is_ok",
    "json_of",
    "multipart_body",
    "image_type",
    "multipart_files",
    "read_chunks",
    "status_of",
]

STEP_PUBLISHED = "published"
STEP_PROCESSING = "processing"


def is_ok(resp: Any) -> bool:
    return _ok(resp)


def json_of(resp: Any) -> dict:
    return _safe_json(resp)


def status_of(resp: Any) -> int:
    try:
        return int(getattr(resp, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def error_text(resp: Any, limit: int = 300) -> str:
    """A short, token-free description of a failed platform response."""
    body = json_of(resp)
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        msg = err.get("message") or err.get("error_user_msg") or err.get("type") or ""
    elif isinstance(err, str):
        msg = body.get("error_description") or body.get("message") or err
    else:
        msg = body.get("message") or body.get("detail") or body.get("title") or ""
        errors = body.get("errors")
        if not msg and isinstance(errors, list) and errors and isinstance(errors[0], dict):
            msg = errors[0].get("message") or errors[0].get("detail") or ""
    text = str(msg or "").strip() or f"HTTP {status_of(resp)}"
    return text[:limit]


def retryable(resp: Any) -> bool:
    code = status_of(resp)
    return code == 429 or code >= 500


@dataclass(frozen=True)
class PublishContext:
    """Everything one publish step needs. Tokens live only in memory."""

    platform: str
    access_token: str
    text: str = ""
    title: str = ""
    hashtags: tuple[str, ...] = ()
    video_url: str = ""
    video_path: str = ""
    external_account_id: str = ""
    target_id: str = ""
    target_token: str = ""
    meta: dict = field(default_factory=dict)
    progress: dict = field(default_factory=dict)
    # Image posts (Design Studio pages): public URLs for URL-ingest platforms and
    # local files for byte-upload platforms, in page order. Empty for reels.
    image_urls: tuple[str, ...] = ()
    image_paths: tuple[str, ...] = ()

    @property
    def is_image_post(self) -> bool:
        return bool(self.image_urls or self.image_paths)

    def image_bytes(self) -> list[bytes]:
        """The local image files' bytes, in order (byte-upload platforms)."""
        out: list[bytes] = []
        for path in self.image_paths:
            with open(path, "rb") as fh:
                out.append(fh.read())
        return out

    def video_size(self) -> int:
        if self.video_path and os.path.exists(self.video_path):
            return os.path.getsize(self.video_path)
        return 0


@dataclass(frozen=True)
class Step:
    status: str                    # "published" | "processing"
    external_id: str = ""
    url: str = ""
    progress: dict = field(default_factory=dict)
    note: str = ""

    @property
    def done(self) -> bool:
        return self.status == STEP_PUBLISHED


@runtime_checkable
class ExtendedConnector(Protocol):
    platform: str

    def publish(self, ctx: PublishContext, *, transport: Transport) -> Step: ...

    def resume(self, ctx: PublishContext, *, transport: Transport) -> Step: ...


def read_chunks(path: str, chunk_size: int):
    """Yield ``(index, bytes)`` chunks of a local file."""
    with open(path, "rb") as fh:
        index = 0
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            yield index, chunk
            index += 1


def read_range(path: str, first: int, last: int) -> bytes:
    """Bytes ``first..last`` inclusive of a local file."""
    with open(path, "rb") as fh:
        fh.seek(first)
        return fh.read(max(0, last - first + 1))


def multipart_body(fields: dict[str, str], file_field: str, filename: str, payload: bytes,
                   content_type: str = "video/mp4") -> tuple[bytes, str]:
    """Build a ``multipart/form-data`` body; returns ``(body, content_type_header)``.

    Built by hand so the single :class:`Transport` seam (``data=`` + headers)
    carries file uploads too.
    """
    boundary = f"menivor{secrets.token_hex(12)}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        + payload
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def image_type(payload: bytes) -> tuple[str, str]:
    """``(content_type, extension)`` sniffed from the first bytes (PNG/JPEG/WebP/GIF)."""
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp", "webp"
    if payload[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    return "application/octet-stream", "bin"


def multipart_files(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    """Like :func:`multipart_body` but with several ``(field, filename, bytes, content_type)`` files."""
    boundary = f"menivor{secrets.token_hex(12)}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    for file_field, filename, payload, content_type in files:
        parts.append(
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            + payload
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------------- #
# Registry (separate from the native TikTok/IG/YT registry on purpose)
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, ExtendedConnector] = {}


def register(connector: ExtendedConnector) -> None:
    _REGISTRY[connector.platform] = connector


def get(platform: str) -> ExtendedConnector | None:
    return _REGISTRY.get(str(platform or "").strip().lower())


def registered() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


# Image-only connectors for platforms whose reels go through the native
# registry (Instagram). Kept out of ``_REGISTRY`` so reel scheduling is unchanged.
_IMAGE_ONLY: dict[str, ExtendedConnector] = {}


def register_image_only(connector: ExtendedConnector) -> None:
    _IMAGE_ONLY[connector.platform] = connector


def get_for_images(platform: str) -> ExtendedConnector | None:
    """The connector that publishes an image post to ``platform`` (``None`` = not wired)."""
    key = str(platform or "").strip().lower()
    return _REGISTRY.get(key) or _IMAGE_ONLY.get(key)


def fail(platform: str, message: str, *, resp: Any = None) -> PublishError:
    """A :class:`PublishError` carrying the platform's own reason (never a token)."""
    detail = f": {error_text(resp)}" if resp is not None else ""
    return PublishError(platform, f"{message}{detail}", retryable=bool(resp is not None and retryable(resp)))


def new_default_transport() -> Transport:
    return RequestsTransport(timeout_s=300.0)
