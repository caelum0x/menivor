"""Render the filter preset preview loops for the shelf ($0, our own lanes).

Each filter preset gets a 4 s muted 540x960 loop and a poster, rendered with
the same FFmpeg fragments the compose stage uses (``build_vfx_filters``) over
a licensed stock clip (Pexels License, fetched by the showcase tooling into
``$SHOWCASE_WORK/stock``). Output goes to the staging folder; the manifest
entry is written as ``staged``. Uploading the loops to the public bucket and
switching ``PRESET_PREVIEWS_LIVE=1`` is a deploy step.

Model presets are never rendered here: their previews are paid renders from
the owner promo budget (item M1).

    python -m app.domains.presets_hub.preview_render [--now] [ids...]
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

from . import catalog, previews

REPO = Path(__file__).resolve().parents[5]
STAGING = Path(os.environ.get("SHOWCASE_OUT", REPO / "public-samples-staging")) / "presets"
STOCK = Path(os.environ.get("SHOWCASE_WORK", "/tmp/menivor-showcase")) / "stock"
SECONDS = 4.0
SIZE = (540, 960)
FPS = 30
MIN_FREE_GB = 12.0

#: One licensed stock clip per filter preset (Pexels video ids; no clip twice).
SOURCE_CLIPS: dict[str, str] = {
    "crash-zoom": "29892299",
    "dreamy-push": "8131891",
    "vintage-film": "34601858",
    "whip-pan": "35291926",
    "orbit": "31992241",
    "drone-rush": "28615730",
    "handheld-vlog": "31921071",
    "glitch-punch": "34124550",
    "dutch-drama": "7697102",
    "crane-reveal": "37522009",
    "speed-ramp": "6289336",
    "rack-focus": "6748362",
}


def filter_chain(preset: catalog.Preset) -> str:
    from app.services.compose.vfx import build_vfx_filters

    width, height = SIZE
    base = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={FPS}"
    fragments = build_vfx_filters(preset.camera_motion, list(preset.effects), intensity=preset.intensity,
                                  fps=FPS, width=width, height=height, duration_s=SECONDS)
    return ",".join([base, *fragments, "format=yuv420p"])


def loop_command(src: str, dest: str, chain: str) -> list[str]:
    return ["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-t", f"{SECONDS}", "-i", src, "-an",
            "-vf", chain, "-t", f"{SECONDS}", "-c:v", "libx264", "-preset", "slow", "-crf", "23",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart", dest]


def poster_command(loop: str, dest: str) -> list[str]:
    return ["ffmpeg", "-v", "error", "-y", "-ss", "1.0", "-i", loop, "-frames:v", "1", "-q:v", "5", dest]


def render(preset: catalog.Preset, src: str, out_dir: Path = STAGING) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    loop = out_dir / f"{preset.id}.mp4"
    poster = out_dir / f"{preset.id}.jpg"
    subprocess.run(loop_command(src, str(loop), filter_chain(preset)), check=True, timeout=600)
    subprocess.run(poster_command(str(loop), str(poster)), check=True, timeout=120)
    return {"loop": f"presets/{preset.id}.mp4", "poster": f"presets/{preset.id}.jpg", "status": "staged",
            "rendered_at": _dt.date.today().isoformat(), "spend_usd": 0.0,
            "source": f"Pexels License stock, video {Path(src).stem.removeprefix('px-')}"}


def write_manifest(entries: dict[str, dict], path: Path = previews.MANIFEST) -> None:
    """Merge ``entries`` into the manifest; existing entries are never removed."""
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    merged = {**dict(data.get("previews") or {}), **entries}
    path.write_text(json.dumps({**data, "previews": dict(sorted(merged.items()))}, indent=1) + "\n",
                    encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render filter preset previews (MH2)")
    parser.add_argument("ids", nargs="*")
    args = parser.parse_args(list(argv) if argv is not None else None)
    with contextlib.suppress(OSError, AttributeError):
        os.nice(19)
    wanted: Sequence[str] = args.ids or list(SOURCE_CLIPS)
    entries: dict[str, dict] = {}
    for pid in wanted:
        preset = catalog.get(pid)
        if preset is None or preset.kind != catalog.KIND_FILTER:
            print(f"skip {pid}: not a filter preset")
            continue
        if shutil.disk_usage("/").free / 1e9 < MIN_FREE_GB:
            print(f"stopping before {pid}: under {MIN_FREE_GB} GB free")
            break
        src = STOCK / f"px-{SOURCE_CLIPS[pid]}.mp4"
        if not src.is_file():
            print(f"skip {pid}: stock clip {src.name} not fetched")
            continue
        entries[pid] = render(preset, str(src))
        print(f"{pid}: {entries[pid]['loop']}")
    if entries:
        write_manifest(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
