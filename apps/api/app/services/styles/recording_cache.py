"""Share one page recording across a reel's variants (worker-local cache).

A one-flow create renders 3 variants of the same pasted page. Each variant
used to open headless Chromium and record the page scrolling in real time
(up to 40 s plus browser start) even though the clip is identical: the scene
stream-loops it to each variant's length. This keeps the first recording for
a short while and hands the same file to the next variants.

Only public pages are recorded (the SSRF guard in ``page_recording`` runs
before anything reaches here), without cookies or a session, so a cached clip
holds nothing private. An exclusive lock per page makes a second variant wait
for the first recording instead of starting its own browser.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import time
from typing import Callable

from loguru import logger

TTL_S = 20 * 60
_CLIP = "clip.webm"


def _root() -> str:
    from app.utils import utils

    return os.path.join(utils.storage_dir(), "cache", "page-recordings")


def _key(url: str, width: int, height: int) -> str:
    return hashlib.sha256(f"{url}|{int(width)}x{int(height)}".encode()).hexdigest()[:32]


def _fresh(path: str, now: float) -> bool:
    try:
        return os.path.getsize(path) > 0 and now - os.path.getmtime(path) < TTL_S
    except OSError:
        return False


def _prune(root: str, now: float, keep: str) -> None:
    try:
        entries = os.listdir(root)
    except OSError:
        return
    for name in entries:
        folder = os.path.join(root, name)
        if folder == keep or not os.path.isdir(folder):
            continue
        try:
            stale = not _fresh(os.path.join(folder, _CLIP), now) and now - os.path.getmtime(folder) > TTL_S
        except OSError:
            continue
        if stale:
            shutil.rmtree(folder, ignore_errors=True)


def cached_recording(
    url: str,
    width: int,
    height: int,
    record: Callable[[], str],
    *,
    root: str | None = None,
    now: Callable[[], float] = time.time,
) -> str:
    """Return a recent recording of ``url`` at this size, recording it once."""
    base = root or _root()
    folder = os.path.join(base, _key(url, width, height))
    clip = os.path.join(folder, _CLIP)
    recorded = ""
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, ".lock"), "w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if _fresh(clip, now()):
                logger.info("page recording: reusing this page's recent clip")
                return clip
            recorded = record()
            if not recorded or not os.path.isfile(recorded):
                return ""
            tmp = f"{clip}.{os.getpid()}.tmp"
            shutil.copyfile(recorded, tmp)
            os.replace(tmp, clip)
            _prune(base, now(), keep=folder)
            return clip
    except Exception as exc:  # noqa: BLE001 - the cache must never cost a render
        logger.warning(f"page recording cache skipped: {type(exc).__name__}: {exc}")
        return recorded if recorded and os.path.isfile(recorded) else record()


__all__ = ["TTL_S", "cached_recording"]
