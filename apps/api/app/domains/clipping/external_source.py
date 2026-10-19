"""Bounded, SSRF-safe external video ingestion for clipping jobs.

External bytes are materialized once into the clipping job's scoped temporary
directory. FFmpeg only ever receives that local file, so playlists and remote
sub-resource fetches cannot turn media probing into a second SSRF surface.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from loguru import logger

MAX_EXTERNAL_SOURCE_BYTES = 1_073_741_824  # 1 GiB
MAX_EXTERNAL_SOURCE_URL_LENGTH = 2_048
MAX_EXTERNAL_REDIRECTS = 3
DOWNLOAD_CONNECT_TIMEOUT_S = 10
DOWNLOAD_READ_TIMEOUT_S = 120
DOWNLOAD_CHUNK_BYTES = 1 << 20
USER_AGENT = "Menivor-Clipping-Ingest/1.0"

_ALLOWED_APPLICATION_TYPES = frozenset(
    {
        "application/mp4",
        "application/octet-stream",
        "application/ogg",
        "application/x-matroska",
        "binary/octet-stream",
    }
)
_VIDEO_EXTENSIONS = frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class ExternalSourceError(ValueError):
    """Safe external-ingest failure with an HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def normalize_external_source_url(raw_url: str) -> str:
    """Return one canonical HTTPS URL or reject unsafe URL syntax."""
    url = (raw_url or "").strip()
    if not url or len(url) > MAX_EXTERNAL_SOURCE_URL_LENGTH:
        raise ExternalSourceError(422, "external video URL is invalid")
    if any(
        ord(character) < 32 or character.isspace() or character == "\\"
        for character in url
    ):
        raise ExternalSourceError(422, "external video URL is invalid")
    try:
        parsed = urlparse(url)
        _ = parsed.port
    except (TypeError, ValueError) as exc:
        raise ExternalSourceError(422, "external video URL is invalid") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ExternalSourceError(422, "external video URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ExternalSourceError(422, "external video URL cannot contain credentials")
    if parsed.fragment:
        raise ExternalSourceError(422, "external video URL cannot contain a fragment")
    return urlunparse(parsed._replace(scheme="https", fragment=""))


def safe_external_source_ref(url: str) -> str:
    """Return a stable non-secret reference instead of projecting URL query data."""
    normalized = normalize_external_source_url(url)
    return f"external:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def external_source_suffix(url: str) -> str:
    suffix = os.path.splitext(urlparse(normalize_external_source_url(url)).path)[1]
    return suffix.lower() if suffix.lower() in _VIDEO_EXTENSIONS else ".mp4"


def _content_length(response: Any) -> int | None:
    raw = str(response.headers.get("Content-Length", "") or "").strip()
    if not raw:
        return None
    try:
        length = int(raw)
    except ValueError:
        return None
    return max(0, length)


def _validate_content_type(response: Any) -> None:
    content_type = str(response.headers.get("Content-Type", "") or "")
    content_type = content_type.split(";", 1)[0].strip().lower()
    if (
        content_type
        and not content_type.startswith("video/")
        and content_type not in _ALLOWED_APPLICATION_TYPES
    ):
        raise ExternalSourceError(415, "external source is not a downloadable video")


def _open_public_response(
    url: str,
    *,
    session_factory: Callable[[], Any],
) -> tuple[Any, Any]:
    """Open one DNS-pinned request with redirects and environment proxies off."""
    from app.services import webhooks

    error, pinned_ip = webhooks._validate_and_resolve(url)
    # This is a user-authored media URL, so the webhook operator override must
    # never weaken its policy. Validate the pinned connection target again with
    # the unconditional address classifier.
    if error is not None or not pinned_ip or webhooks._ip_is_internal(pinned_ip):
        raise ExternalSourceError(422, "external video URL is not publicly routable")
    session = session_factory()
    try:
        if hasattr(session, "trust_env"):
            session.trust_env = False
        adapter_cls = webhooks._PinnedHTTPAdapter
        if adapter_cls is None:
            raise ExternalSourceError(503, "external video ingestion is unavailable")
        adapter = adapter_cls(pinned_ip)
        session.mount("https://", adapter)
        response = session.get(
            url,
            stream=True,
            timeout=(DOWNLOAD_CONNECT_TIMEOUT_S, DOWNLOAD_READ_TIMEOUT_S),
            allow_redirects=False,
            headers={
                "Accept": "video/*,application/octet-stream;q=0.8",
                "User-Agent": USER_AGENT,
            },
        )
        return session, response
    except Exception:
        session.close()
        raise


def download_external_video(
    raw_url: str,
    destination: str,
    *,
    session_factory: Callable[[], Any] | None = None,
) -> str:
    """Stream one public HTTPS video to ``destination`` atomically.

    Every redirect target is normalized, independently DNS-vetted, and pinned
    before its request. A partial or rejected download never becomes visible at
    the final path.
    """
    from app.services import webhooks

    requests = webhooks.requests
    if requests is None:
        raise ExternalSourceError(503, "external video ingestion is unavailable")
    make_session = session_factory or requests.Session
    current_url = normalize_external_source_url(raw_url)
    seen = {current_url}
    part_path = f"{destination}.part"
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
    try:
        for redirect_count in range(MAX_EXTERNAL_REDIRECTS + 1):
            session = response = None
            try:
                session, response = _open_public_response(
                    current_url,
                    session_factory=make_session,
                )
                status = int(response.status_code)
                if status in _REDIRECT_STATUSES:
                    if redirect_count >= MAX_EXTERNAL_REDIRECTS:
                        raise ExternalSourceError(
                            422, "external video redirected too many times"
                        )
                    location = str(response.headers.get("Location", "") or "").strip()
                    if not location:
                        raise ExternalSourceError(
                            422, "external video redirect is invalid"
                        )
                    target = normalize_external_source_url(
                        urljoin(current_url, location)
                    )
                    if target in seen:
                        raise ExternalSourceError(
                            422, "external video redirect loop detected"
                        )
                    seen.add(target)
                    current_url = target
                    continue
                if status >= 400:
                    raise ExternalSourceError(502, "external video download failed")
                _validate_content_type(response)
                announced = _content_length(response)
                if announced is not None and announced > MAX_EXTERNAL_SOURCE_BYTES:
                    raise ExternalSourceError(
                        413, "external video exceeds the 1 GiB limit"
                    )

                written = 0
                with open(part_path, "wb") as output:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_EXTERNAL_SOURCE_BYTES:
                            raise ExternalSourceError(
                                413, "external video exceeds the 1 GiB limit"
                            )
                        output.write(chunk)
                    if written == 0:
                        raise ExternalSourceError(422, "external video is empty")
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(part_path, destination)
                return destination
            finally:
                if response is not None:
                    response.close()
                if session is not None:
                    session.close()
        raise ExternalSourceError(422, "external video redirected too many times")
    except ExternalSourceError:
        try:
            os.unlink(part_path)
        except FileNotFoundError:
            pass
        raise
    except Exception as exc:  # noqa: BLE001 - normalize transport/disk boundary
        try:
            os.unlink(part_path)
        except FileNotFoundError:
            pass
        logger.warning(
            f"clipping external download failed: {type(exc).__name__}: {exc}"
        )
        raise ExternalSourceError(502, "could not download external video") from exc


__all__ = [
    "ExternalSourceError",
    "MAX_EXTERNAL_SOURCE_BYTES",
    "download_external_video",
    "external_source_suffix",
    "normalize_external_source_url",
    "safe_external_source_ref",
]
