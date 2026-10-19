"""Social-platform link ingestion for long->short clipping jobs.

Pasting a YouTube / TikTok / Vimeo / Twitch / X link is the headline
"paste a link -> auto-clip -> publish" flow every competitor (Opus Clip, Klap,
Vizard) leads with. A platform *page* URL is not a downloadable media file, so
the SSRF-safe raw-file downloader in :mod:`external_source` correctly rejects it
with 415 ("not a downloadable video"). This module recognizes known social hosts
and delegates resolution + a bounded download to ``yt_dlp``, which owns the fetch
to the platform CDN (googlevideo etc.); the raw-file SSRF pinning is therefore
not re-applied here (the extractor owns the transport), but the byte/duration
bounds still hold so an enormous or hours-long source can never land in a worker.

Fail-closed discipline (mirrors :mod:`app.core.launch.policy`):
  * The whole path is gated behind ``clipping_platform_ingest_enabled`` (default
    OFF). A provider credential or an installed dependency never opens it alone.
  * Bounded by ``MAX_EXTERNAL_SOURCE_BYTES`` and ``max_source_duration_s()``.
  * ``yt_dlp`` is an OPTIONAL dependency: when absent this degrades to a clean
    503 and the rest of the app (and the full test suite) is unaffected. Only the
    heavy download function imports it; recognition + the config gates stay
    import-light so schema validation and source branching need nothing installed.
"""

from __future__ import annotations

import glob
import hashlib
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from app.domains.clipping.external_source import (
    MAX_EXTERNAL_SOURCE_BYTES,
    normalize_external_source_url,
)

# Registered exact hosts (matched on the host with a leading ``www.`` stripped)
# and their canonical platform id. A host also matches when it is a subdomain of
# one of these (e.g. ``m.youtube.com`` -> youtube, ``vt.tiktok.com`` -> tiktok).
_PLATFORM_HOSTS: dict[str, str] = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "tiktok.com": "tiktok",
    "vimeo.com": "vimeo",
    "twitch.tv": "twitch",
    "x.com": "x",
    "twitter.com": "x",
}

# Upper bound on an ingested source's duration so an hours-long stream can never
# be pulled into a worker. Overridable via config; 0/blank falls back to this.
DEFAULT_MAX_SOURCE_DURATION_S = 14_400  # 4h
# 0 => rely on the standard wallet quote ceiling only (no extra platform cap).
DEFAULT_PLATFORM_SPEND_CAP_USD = 0
DOWNLOAD_SOCKET_TIMEOUT_S = 30
_USD_MICROS = 1_000_000

# Prefer one progressive (pre-muxed) MP4 so no ffmpeg merge is needed and the
# byte cap applies to a single file; fall back to any muxed stream, then best.
_FORMAT_SELECTOR = (
    "best[ext=mp4][acodec!=none][vcodec!=none]"
    "/best[acodec!=none][vcodec!=none]/best"
)


class PlatformSourceError(ValueError):
    """A caller-facing platform-ingest failure carrying an HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def recognize_platform(raw_url: str) -> str | None:
    """Return the platform id for a known social host, else ``None``.

    Import-light: never touches ``yt_dlp`` or config, so schema validation and
    source branching can classify a URL without the optional dependency present.
    An unparseable or non-HTTPS URL simply is not a recognized platform.
    """
    try:
        url = normalize_external_source_url(raw_url)
    except Exception:  # noqa: BLE001 - a bad URL is just "not a platform" here
        return None
    host = _host_of(url)
    if not host:
        return None
    if host in _PLATFORM_HOSTS:
        return _PLATFORM_HOSTS[host]
    for known, platform in _PLATFORM_HOSTS.items():
        if host.endswith("." + known):
            return platform
    return None


def platform_ingest_enabled() -> bool:
    """Fail-closed feature gate; env wins, then config.toml, then ``False``."""
    from app.config import config

    value = os.getenv(
        "REELFORGE_CLIPPING_PLATFORM_INGEST_ENABLED",
        config.app.get("reelforge_clipping_platform_ingest_enabled", False),
    )
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def max_source_duration_s() -> int:
    """Configured ingest duration ceiling in seconds (>0), else the default."""
    from app.config import config

    try:
        value = int(
            config.app.get(
                "reelforge_clipping_max_source_duration_s",
                DEFAULT_MAX_SOURCE_DURATION_S,
            )
        )
    except (TypeError, ValueError):
        return DEFAULT_MAX_SOURCE_DURATION_S
    return value if value > 0 else DEFAULT_MAX_SOURCE_DURATION_S


def platform_spend_cap_micros() -> int:
    """Optional per-job USD spend ceiling for platform-ingest jobs, in micros.

    Returns ``0`` when unset/invalid, meaning "no extra cap — rely on the
    standard wallet quote ceiling only".
    """
    from app.config import config

    try:
        cap_usd = float(
            config.app.get(
                "reelforge_clipping_platform_spend_cap_usd",
                DEFAULT_PLATFORM_SPEND_CAP_USD,
            )
        )
    except (TypeError, ValueError):
        return 0
    if cap_usd <= 0:
        return 0
    return int(round(cap_usd * _USD_MICROS))


def platform_source_ref(raw_url: str, platform: str | None = None) -> str:
    """Stable, non-secret source reference (never projects URL query/id data)."""
    normalized = normalize_external_source_url(raw_url)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    label = platform or recognize_platform(raw_url) or "platform"
    return f"platform:{label}:{digest}"


def _load_yt_dlp() -> Any:
    try:
        import yt_dlp  # noqa: PLC0415 - optional dependency, imported lazily
    except Exception as exc:  # noqa: BLE001 - absent dep => clean 503, never a crash
        logger.error(f"clipping platform ingest unavailable (yt_dlp missing): {exc}")
        raise PlatformSourceError(
            503, "platform link ingestion is unavailable"
        ) from exc
    return yt_dlp


def _coerce_duration(info: Any) -> float | None:
    raw = info.get("duration") if isinstance(info, dict) else None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _first_entry(info: Any) -> dict:
    """Collapse a (defensive) playlist result to its first real entry."""
    if isinstance(info, dict) and info.get("entries") is not None:
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if not entries:
            raise PlatformSourceError(422, "platform link has no downloadable video")
        return entries[0]
    return info if isinstance(info, dict) else {}


def _downloaded_path(ydl: Any, info: Any, outdir: str, stem: str) -> str:
    """Resolve the concrete file yt_dlp wrote for ``info``."""
    downloads = info.get("requested_downloads") if isinstance(info, dict) else None
    for entry in downloads or []:
        candidate = entry.get("filepath") or entry.get("_filename")
        if candidate and os.path.exists(candidate):
            return candidate
    if isinstance(info, dict):
        guess = ydl.prepare_filename(info)
        if guess and os.path.exists(guess):
            return guess
    base = os.path.basename(stem)
    for candidate in sorted(glob.glob(os.path.join(outdir, f"{base}.*"))):
        if os.path.isfile(candidate) and not candidate.endswith(".part"):
            return candidate
    raise PlatformSourceError(502, "platform source download produced no file")


def download_platform_video(
    raw_url: str,
    dest_stem: str,
    *,
    ydl_factory: Callable[[dict], Any] | None = None,
) -> str:
    """Resolve + download the best progressive MP4 for a recognized platform link.

    ``dest_stem`` is a path *without* an extension inside the job workdir; the
    real file (extension chosen by ``yt_dlp``) is returned. Playlists collapse to
    a single entry (``noplaylist=True``); the download is bounded by
    ``MAX_EXTERNAL_SOURCE_BYTES`` and ``max_source_duration_s()`` (duration is
    checked from resolved metadata *before* the download so an over-long source
    is rejected without pulling bytes).
    """
    platform = recognize_platform(raw_url)
    if platform is None:
        # Reachable only via a defensive/direct call; the service branches on
        # recognize_platform first. Typed so it surfaces as a clean 422.
        raise PlatformSourceError(422, "unsupported source platform")
    if not platform_ingest_enabled():
        raise PlatformSourceError(403, "platform link ingestion is not enabled")

    url = normalize_external_source_url(raw_url)
    outdir = os.path.dirname(dest_stem) or "."
    os.makedirs(outdir, exist_ok=True)
    duration_cap = max_source_duration_s()

    # ``ydl_factory`` is an injected seam (tests); only the production path needs
    # the optional dependency, so import it lazily and never for an injected one.
    factory = ydl_factory if ydl_factory is not None else _load_yt_dlp().YoutubeDL
    options = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "cachedir": False,
        "outtmpl": f"{dest_stem}.%(ext)s",
        "format": _FORMAT_SELECTOR,
        "max_filesize": MAX_EXTERNAL_SOURCE_BYTES,
        "socket_timeout": DOWNLOAD_SOCKET_TIMEOUT_S,
        "retries": 1,
        "restrictfilenames": True,
        "overwrites": True,
    }
    try:
        with factory(options) as ydl:
            probed = _first_entry(ydl.extract_info(url, download=False))
            duration = _coerce_duration(probed)
            if duration is not None and duration > duration_cap:
                raise PlatformSourceError(
                    413, f"source video exceeds the {duration_cap}s ingest limit"
                )
            resolved = _first_entry(ydl.extract_info(url, download=True))
            path = _downloaded_path(ydl, resolved, outdir, dest_stem)
    except PlatformSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize extractor/transport boundary
        logger.warning(
            f"clipping platform download failed ({platform}): "
            f"{type(exc).__name__}: {exc}"
        )
        raise PlatformSourceError(502, "could not download platform video") from exc

    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise PlatformSourceError(
            502, "platform source download is unreadable"
        ) from exc
    if size <= 0:
        _safe_unlink(path)
        raise PlatformSourceError(422, "platform source video is empty")
    if size > MAX_EXTERNAL_SOURCE_BYTES:
        # Belt-and-braces: some hosts do not announce a size for ``max_filesize``
        # to act on, so re-check the file that actually landed on disk.
        _safe_unlink(path)
        raise PlatformSourceError(413, "platform video exceeds the 1 GiB limit")
    return path


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:  # noqa: BLE001 - cleanup is best-effort
        logger.debug(f"clipping platform cleanup failed for {path!r}: {exc}")


__all__ = [
    "PlatformSourceError",
    "download_platform_video",
    "max_source_duration_s",
    "platform_ingest_enabled",
    "platform_source_ref",
    "platform_spend_cap_micros",
    "recognize_platform",
]
