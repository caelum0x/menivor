"""Background-music LIBRARY over ``resource/songs/``.

MoneyPrinterTurbo already ships a small catalogue of royalty-free tracks under
``resource/songs``. Phase-6 Creator Studio needs a *stable, addressable* view of
that catalogue so a client can:

  1. enumerate the available tracks (:func:`list_music`), and
  2. resolve a chosen track back to a real, sandbox-safe file path
     (:func:`get_music_path`) that feeds ``compose``'s existing ``music_path``
     argument.

Design notes
------------
* Track ids are **slugs of the filename** — deterministic and stable across
  processes, so a client can persist an id and resolve it later. Slug
  collisions (two files that slugify identically) are disambiguated with a
  numeric suffix in a fully deterministic order, so the same id maps to the same
  file on every scan.
* Every resolved path is re-validated with
  :func:`file_security.resolve_path_within_directory`, which uses
  ``os.path.commonpath`` on *real* paths. This defends against directory
  traversal (``../``) and symlinks that escape ``resource/songs`` — an attacker
  who dropped a symlink in the songs directory could otherwise hand an arbitrary
  file to FFmpeg via ``music_path``.
* Duration probing is best-effort: it uses ``ffprobe`` when available and never
  fails the listing. ``duration_s`` is therefore an *optional* key.
* Licences (M2.4): each listed track carries ``licence`` and ``cleared`` from
  :mod:`app.services.audio.licences`. With ``MENIVOR_MUSIC_CLEARED_ONLY=1`` only
  tracks whose licence is verified are listed or resolvable.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess

try:  # loguru ships with MPT, but keep the library import-safe without it.
    from loguru import logger
except Exception:  # pragma: no cover - fallback only when loguru is absent.
    import logging

    logger = logging.getLogger(__name__)

from app.utils import file_security, utils


# Only expose semantically-unambiguous audio containers as background music.
# Kept intentionally narrow (per the Phase-6 spec: mp3/m4a/wav) so a stray
# ``.mp4`` or ``.txt`` in the songs directory can never surface as a track.
SUPPORTED_MUSIC_EXTENSIONS: tuple[str, ...] = (".mp3", ".m4a", ".wav")

_DURATION_PROBE_TIMEOUT_SECONDS = 30
_MUSIC_ID_MAX_LENGTH = 128


def _songs_dir() -> str:
    """Return the built-in songs directory (``resource/songs``)."""
    return utils.song_dir()


def _slug(filename: str) -> str:
    """Return a stable, URL-safe slug derived from ``filename``'s stem."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", stem).strip("-").lower()
    slug = slug[:_MUSIC_ID_MAX_LENGTH].strip("-")
    return slug or "track"


def _display_name(filename: str) -> str:
    """Return a human-friendly track name derived from ``filename``."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    pretty = re.sub(r"[_-]+", " ", stem).strip()
    return pretty or filename


def _scan() -> list[tuple[str, str]]:
    """Scan the songs directory, returning ``(music_id, filename)`` pairs.

    Files are visited in a deterministic, case-insensitive order so that slug
    collisions resolve to the same id on every call. Any entry that fails the
    safe-path check (e.g. a symlink escaping the directory) is skipped.
    """
    songs_dir = _songs_dir()
    if not os.path.isdir(songs_dir):
        return []

    entries: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    try:
        names = sorted(os.listdir(songs_dir), key=str.lower)
    except OSError as exc:
        logger.warning(f"failed to list music directory: dir={songs_dir}, error={exc}")
        return []

    for name in names:
        if os.path.splitext(name)[1].lower() not in SUPPORTED_MUSIC_EXTENSIONS:
            continue
        candidate = os.path.join(songs_dir, name)
        try:
            # Re-validate the real path stays inside the songs directory; this
            # rejects symlinks that point outside the whitelist before FFmpeg
            # ever sees the file.
            file_security.resolve_path_within_directory(songs_dir, candidate)
        except ValueError as exc:
            logger.warning(f"skip unsafe music file: name={name}, error={exc}")
            continue

        if _cleared_only() and not _track_cleared(candidate):
            continue

        base_id = _slug(name)
        music_id = base_id
        suffix = 1
        while music_id in seen_ids:
            suffix += 1
            music_id = f"{base_id}-{suffix}"
        seen_ids.add(music_id)
        entries.append((music_id, name))

    return entries


def _cleared_only() -> bool:
    try:
        from app.services.audio.licences import cleared_only_enabled

        return cleared_only_enabled()
    except Exception:  # noqa: BLE001 - licence module unavailable: no filter
        return False


def _track_cleared(path: str) -> bool:
    try:
        from app.services.audio.licences import is_cleared

        return is_cleared(path)
    except Exception:  # noqa: BLE001 - unknown licence is never cleared
        return False


def _licence_fields(path: str) -> dict:
    """``licence`` and ``cleared`` for a track (``unknown``/False if unrecorded)."""
    try:
        from app.services.audio.licences import licence_for

        record = licence_for(path)
    except Exception:  # noqa: BLE001 - listing must never fail on licence data
        record = None
    if not record:
        return {"licence": "unknown", "cleared": False}
    return {
        "licence": str(record.get("licence") or "unknown"),
        "cleared": record.get("cleared_for_output") is True,
    }


def _ffprobe_binary() -> str | None:
    """Return an ``ffprobe`` executable path, or ``None`` if unavailable.

    Prefers an ``ffprobe`` sitting next to the project's configured FFmpeg, then
    falls back to ``PATH``. Duration is best-effort, so ``None`` is acceptable.
    """
    try:
        ffmpeg = utils.get_ffmpeg_binary()
    except Exception:  # pragma: no cover - defensive; config may be incomplete.
        ffmpeg = None

    if ffmpeg:
        sibling = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
        if os.path.isfile(sibling) and os.access(sibling, os.X_OK):
            return sibling

    return shutil.which("ffprobe")


def _probe_duration(path: str) -> float | None:
    """Best-effort probe of an audio file's duration in seconds.

    Returns ``None`` on any failure (missing ffprobe, unreadable file, timeout,
    unparsable output) so that listing never breaks on a single bad track.
    """
    ffprobe = _ffprobe_binary()
    if not ffprobe:
        return None

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=_DURATION_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug(f"ffprobe duration probe failed: path={path}, error={exc}")
        return None

    if completed.returncode != 0:
        return None

    raw = completed.stdout.strip()
    if not raw:
        return None
    try:
        duration = float(raw)
    except ValueError:
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return round(duration, 3)


def list_music() -> list[dict]:
    """Enumerate available background-music tracks.

    Returns a list of dicts with keys ``id``, ``name``, ``filename``,
    ``licence``, ``cleared`` and an optional ``duration_s`` (present only when it
    could be probed).
    """
    songs_dir = _songs_dir()
    tracks: list[dict] = []
    for music_id, filename in _scan():
        track: dict = {
            "id": music_id,
            "name": _display_name(filename),
            "filename": filename,
            **_licence_fields(os.path.join(songs_dir, filename)),
        }
        duration = _probe_duration(os.path.join(songs_dir, filename))
        if duration is not None:
            track["duration_s"] = duration
        tracks.append(track)
    return tracks


def get_music_path(music_id: str | None) -> str | None:
    """Resolve ``music_id`` to a safe absolute path inside ``resource/songs``.

    Returns ``None`` for ``None``, blank, or unknown ids. Because only ids
    produced by :func:`_scan` can match, traversal payloads (``../..``) resolve
    to nothing; the final :func:`file_security.resolve_path_within_directory`
    call is defence-in-depth that guarantees the returned path is inside the
    songs directory.
    """
    if music_id is None:
        return None
    normalized = str(music_id).strip()
    if not normalized:
        return None

    songs_dir = _songs_dir()
    for candidate_id, filename in _scan():
        if candidate_id != normalized:
            continue
        try:
            return file_security.resolve_path_within_directory(
                songs_dir, os.path.join(songs_dir, filename)
            )
        except ValueError as exc:
            logger.warning(
                f"resolved music path rejected: id={normalized}, error={exc}"
            )
            return None
    return None
