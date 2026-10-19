"""Pre-encoded background loops (1080x1920 and 540x960, 30 fps, 2 s GOP).

The packaged loops are rendered offline at 720x1280 with ``-preset slow``.
Every reel used to scale them per frame, and the style pipeline re-encoded a
variant mix of them per reel. This module prepares each loop once per worker
into a normalised copy:

* ``1080`` tier: 1080x1920, 30 fps, yuv420p, High profile, fixed 60-frame GOP.
* ``540`` tier: 540x960 with the same settings, for fast previews.

Because every prepared copy of a tier shares codec, size, frame rate and GOP,
a variant mix is a stream copy through the concat demuxer (no encode), and the
compose reads frames that already have the output size.

Preparation is lazy and cached on disk (``MENIVOR_LOOP_CACHE``, default
``<tmp>/menivor-loops``) behind a per-file lock, so concurrent renders on one
worker prepare a loop once. Run ``python -m app.services.loops.prepared`` (or
``scripts/background-loops/prepare-loops.sh``) at image build to pre-warm.
Any failure returns the source clip: a loop problem never fails a reel.

Honest note: the sources are 720p, so the 1080 tier adds no detail; it removes
the per-reel scale and the per-reel mix encode.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from loguru import logger

FPS = 30
GOP = FPS * 2
TIERS: dict[str, tuple[int, int]] = {"1080": (1080, 1920), "540": (540, 960)}
DEFAULT_TIER = "1080"
# Bump when the encode recipe changes so stale cache entries are ignored.
RECIPE_VERSION = "1"
_DEFAULT_PRESET = "medium"
_PRESETS = frozenset({"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"})
_CRF = "20"
_TIMEOUT_S = 300

Runner = Callable[..., subprocess.CompletedProcess]


def cache_dir() -> Path:
    """Where prepared loops live (created on demand)."""
    root = os.environ.get("MENIVOR_LOOP_CACHE", "").strip()
    return Path(root) if root else Path(tempfile.gettempdir()) / "menivor-loops"


def _preset() -> str:
    value = os.environ.get("MENIVOR_LOOP_PRESET", "").strip().lower()
    return value if value in _PRESETS else _DEFAULT_PRESET


def prepare_command(
    src: str, dest: str, width: int, height: int, *, ffmpeg: str = "ffmpeg", preset: str = ""
) -> list[str]:
    """The FFmpeg argv that writes the normalised copy of ``src`` (pure)."""
    graph = (
        f"fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,format=yuv420p"
    )
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
        "-vf", graph, "-an",
        "-c:v", "libx264", "-preset", preset or _preset(), "-crf", _CRF,
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        # Fixed GOP: a keyframe exactly every 2 s, never an extra one on a
        # scene cut, so any prepared segment starts and ends on the same grid.
        "-g", str(GOP), "-keyint_min", str(GOP), "-sc_threshold", "0",
        "-r", str(FPS), "-video_track_timescale", "15360",
        "-movflags", "+faststart", dest,
    ]


def concat_copy_command(listing: str, dest: str, *, ffmpeg: str = "ffmpeg") -> list[str]:
    """Join prepared segments listed in ``listing`` by stream copy (no encode)."""
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", listing,
        "-an", "-c", "copy", "-movflags", "+faststart", dest,
    ]


def cache_path(src: str, tier: str = DEFAULT_TIER) -> Path:
    """The cache file for ``src`` at ``tier`` (keyed by path, size and mtime)."""
    if tier not in TIERS:
        raise ValueError(f"unknown loop tier {tier!r}")
    stat = os.stat(src)
    digest = hashlib.sha256(
        f"{os.path.abspath(src)}|{stat.st_size}|{int(stat.st_mtime)}|{RECIPE_VERSION}|{tier}".encode()
    ).hexdigest()[:20]
    return cache_dir() / f"{Path(src).stem}.{tier}.{digest}.mp4"


@contextlib.contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """An exclusive advisory lock next to ``path`` (no-op where unsupported)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(f"{path}.lock", "a+")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):  # pragma: no cover - non-POSIX hosts
            pass
        yield
    finally:
        handle.close()


def is_prepared(path: str) -> bool:
    """True when ``path`` is a prepared loop from this cache."""
    try:
        return Path(path).resolve().parent == cache_dir().resolve()
    except OSError:
        return False


def prepared_loop(
    src: str,
    tier: str = DEFAULT_TIER,
    *,
    ffmpeg: str = "",
    runner: Runner | None = None,
) -> str:
    """The prepared copy of ``src`` at ``tier``; ``src`` itself on any failure."""
    if not src or not os.path.isfile(src):
        return src
    if is_prepared(src):
        return src
    try:
        target = cache_path(src, tier)
    except (OSError, ValueError) as exc:
        logger.warning(f"loop prepare skipped for {src!r}: {exc}")
        return src
    if target.is_file() and target.stat().st_size > 0:
        return str(target)
    run = runner or subprocess.run
    binary = ffmpeg or _ffmpeg()
    width, height = TIERS[tier]
    try:
        with _file_lock(target):
            if target.is_file() and target.stat().st_size > 0:
                return str(target)  # another render prepared it while we waited
            partial = target.with_suffix(".part.mp4")
            run(
                prepare_command(src, str(partial), width, height, ffmpeg=binary),
                check=True, timeout=_TIMEOUT_S, capture_output=True,
            )
            if not partial.is_file() or partial.stat().st_size <= 0:
                raise RuntimeError("ffmpeg wrote no output")
            os.replace(partial, target)
        logger.info(f"prepared loop {Path(src).name} -> {target.name} ({width}x{height})")
        return str(target)
    except Exception as exc:  # noqa: BLE001 - the source clip still renders
        logger.warning(f"loop prepare failed for {Path(src).name} ({tier}): {exc}")
        return src


def _ffmpeg() -> str:
    try:
        from app.utils import utils

        return utils.get_ffmpeg_binary() or "ffmpeg"
    except Exception:  # noqa: BLE001 - CLI use outside the app config
        return "ffmpeg"


def packaged_loops() -> list[str]:
    """Every packaged loop the worker image ships."""
    from app.domains.content import background_library as bglib

    root = Path(bglib.__file__).resolve().parent / "assets" / "backgrounds"
    return sorted(str(path) for path in root.glob("*.mp4"))


def prewarm(paths: Iterable[str], tiers: Iterable[str] = tuple(TIERS)) -> dict[str, int]:
    """Prepare ``paths`` at ``tiers``; counts of ``prepared`` and ``failed``."""
    counts = {"prepared": 0, "failed": 0}
    for src in paths:
        for tier in tiers:
            out = prepared_loop(src, tier)
            counts["prepared" if is_prepared(out) else "failed"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    """CLI: pre-warm the cache for every packaged loop (or the given files)."""
    args = list(sys.argv[1:] if argv is None else argv)
    paths = args or packaged_loops()
    counts = prewarm(paths)
    print(f"prepared {counts['prepared']} loop copies, {counts['failed']} failed, cache {cache_dir()}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())


__all__ = [
    "DEFAULT_TIER",
    "FPS",
    "GOP",
    "TIERS",
    "cache_dir",
    "cache_path",
    "concat_copy_command",
    "is_prepared",
    "packaged_loops",
    "prepare_command",
    "prepared_loop",
    "prewarm",
]
