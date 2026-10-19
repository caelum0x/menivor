"""Render the landing showcase reels with Menivor's pipeline, in-process, locally.

Stages: script (typed) -> tts (free edge-tts voice) -> avatar (none) -> captions
-> compose, exactly as ``apps/api/tools/ops/render_style_samples.py``, with the
local-mode storage patch from the script-sheet tool: storage is a folder, no
R2, no job row, no brand lookup. The product panel is a Pexels footage montage
instead of a page recording (except our own two products, recorded live).

Run with the repo venv and no dotenv (so no prod DB/R2/Redis is ever reached),
and an FFmpeg with libass + drawtext (the imageio-ffmpeg binary has both):

    python apps/api/tools/ops/showcase/fetch_pexels.py <ids from plan.py>
    # narrator.png (cartoon narrator, 440x440) goes in $SHOWCASE_WORK
    IMAGEIO_FFMPEG_EXE=$(python -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())") \
    REELFORGE_DISABLE_DOTENV=1 python apps/api/tools/ops/showcase/runner.py [keys...]
    apps/api/tools/ops/showcase/encode_web.sh <key> [hero]
    python apps/api/tools/ops/showcase/checks.py --media --json /tmp/showcase-qa.json
    python apps/api/tools/ops/showcase/publish.py --qa /tmp/showcase-qa.json --apply

Renders are bulk work: they run in the lowest render lane (``plan.RENDER_LANE``)
at the lowest CPU priority, and only inside the off-peak window
(``SHOWCASE_OFFPEAK_HOURS``, default ``1-7`` in the host's local time) unless
``--now`` is passed (a dev machine with no users on it).

Paths: $SHOWCASE_WORK (default /tmp/menivor-showcase) holds stock clips and
scratch; $SHOWCASE_OUT (default <repo>/public-samples-staging) gets masters/.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
REPO = os.path.abspath(os.path.join(API, "..", ".."))
WORK = os.environ.get("SHOWCASE_WORK", "/tmp/menivor-showcase")
STOCK = os.path.join(WORK, "stock")
LOOPS = os.path.join(API, "app/domains/content/assets/backgrounds")
STAGING = os.environ.get("SHOWCASE_OUT", os.path.join(REPO, "public-samples-staging"))
STORE = os.path.join(WORK, ".store")
SEG_S = 2.6
MIN_FREE_GB = 12.0

sys.path.insert(0, API)
sys.path.insert(0, HERE)

from loguru import logger  # noqa: E402

import plan  # noqa: E402


def run(argv: list[str]) -> None:
    subprocess.run(argv, check=True, timeout=900)


def probe_duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip() or 0)


def montage(key: str, ids: list[str], work: str, total_s: float = 26.0) -> str:
    """Hard-cut montage of the reel's clips: A B C A' B' C' ... (1080x1920, 30 fps)."""
    out = os.path.join(work, f"{key}-footage.mp4")
    if os.path.exists(out):
        return out
    clips = [os.path.join(STOCK, f"px-{vid}.mp4") for vid in ids]
    parts = []
    count = int(total_s / SEG_S) + 1
    for index in range(count):
        clip = clips[index % len(clips)]
        span = max(0.1, probe_duration(clip) - SEG_S - 0.1)
        start = (0.2 + (index // len(clips)) * SEG_S) % span
        part = os.path.join(work, f"{key}-seg{index}.mp4")
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-stream_loop", "-1", "-t", f"{SEG_S}", "-i", clip,
             "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30",
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", part])
        parts.append(part)
    listing = os.path.join(work, f"{key}-list.txt")
    with open(listing, "w") as handle:
        handle.writelines(f"file '{p}'\n" for p in parts)
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", out])
    for p in parts:
        os.remove(p)
    return out


def loop_file(spec: str, footage: str) -> str:
    if spec == "@footage":
        return footage
    if spec.startswith("px:"):
        return os.path.join(STOCK, f"px-{spec[3:]}.mp4")
    return os.path.join(LOOPS, spec) if spec else ""


@contextlib.contextmanager
def patched(target, **attrs):
    saved = {name: getattr(target, name) for name in attrs}
    for name, value in attrs.items():
        setattr(target, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(target, name, value)


class LocalStore:
    def __init__(self, root: str) -> None:
        self.root = root

    def path(self, key: str) -> str:
        return os.path.join(self.root, key.lstrip("/"))

    def upload_file(self, path: str, key: str, content_type: str = "") -> str:
        dest = self.path(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.abspath(path) != os.path.abspath(dest):
            shutil.copyfile(path, dest)
        return f"file://{dest}"

    def public_url(self, key: str) -> str:
        return f"file://{self.path(key)}"

    def presign_get(self, key: str, expires: int = 900) -> str:
        return f"file://{self.path(key)}"


def render(reel: dict) -> dict:
    from app.domains.content import background_library as bglib
    from app.domains.styles.catalog import get_style, style_overrides
    from app.services import reelforge
    from app.services.styles import pipeline, visuals

    key = reel["key"]
    work = os.path.join(WORK, "work", key)
    os.makedirs(work, exist_ok=True)
    footage = montage(key, reel["footage"], work) if reel["footage"] else ""
    loop = loop_file(reel["loop"], footage)
    store = LocalStore(STORE)

    def download(obj_key: str, dest_path: str, expires: int = 900) -> str:
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        if os.path.abspath(store.path(obj_key)) != os.path.abspath(dest_path):
            shutil.copyfile(store.path(obj_key), dest_path)
        return dest_path

    style = get_style(reel["style"]) if reel["style"] else None
    overrides = style_overrides(style) if style else {
        "layout": "captions_only", "background_id": "block-runner", "caption_style": reel["captions"]}
    params = reelforge.ReelForgeParams(
        video_subject=reel["niche"],
        video_script=reel["script"],
        voice_name=reel["voice"],
        aspect="9:16",
        language="en",
        target_duration_s=plan.TARGET_DURATION_S,
        source_url=reel.get("page") or "https://example.com",
        **overrides,
    )
    job_id = f"landing-{key}-{uuid.uuid4().hex[:6]}"
    original_record = pipeline._record_page

    def record(url, dest, width, height, duration_s):
        if reel.get("page"):
            return original_record(reel["page"], dest, width, height, duration_s)
        return footage

    narrator = os.path.join(WORK, "narrator.png")
    started = time.time()
    ctx: dict = {}
    with patched(reelforge, _r2=lambda: store, _download_from_r2=download,
                 _persist_script=lambda j, s: None, _load_user_brand=lambda j: None), \
         patched(pipeline, _record_page=record, _loop_path=lambda *a, **k: loop), \
         patched(bglib, materialize=lambda clip, **k: [footage]), \
         patched(visuals, character_image=lambda dest, **k: ([narrator], 0.0)):
        for stage in (reelforge.stage_script, reelforge.stage_tts, reelforge.stage_avatar,
                      reelforge.stage_captions, reelforge.stage_compose):
            ctx = {**ctx, **(stage(job_id, params, ctx) or {})}
    final = str(ctx.get("final_video") or "")
    if not final or not os.path.isfile(final):
        raise RuntimeError(f"{key}: compose produced no final video")
    os.makedirs(STAGING, exist_ok=True)
    master = os.path.join(STAGING, "masters", f"{key}.mp4")
    os.makedirs(os.path.dirname(master), exist_ok=True)
    shutil.copyfile(final, master)
    shutil.rmtree(os.path.dirname(final), ignore_errors=True)
    return {"key": key, "seconds": round(time.time() - started, 1),
            "duration_s": round(float(ctx.get("audio_duration") or 0), 2),
            "voice": reel["voice"], "lane": plan.RENDER_LANE, "master": master}


def offpeak_hours(raw: str | None = None) -> tuple[int, int]:
    """``SHOWCASE_OFFPEAK_HOURS`` as ``(start, end)`` hours, end exclusive."""
    value = (raw if raw is not None else os.environ.get("SHOWCASE_OFFPEAK_HOURS", "1-7")).strip()
    start, _, end = value.partition("-")
    return int(start) % 24, int(end or start) % 24


def in_offpeak(now: _dt.datetime, window: tuple[int, int]) -> bool:
    start, end = window
    if start == end:
        return True
    if start < end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end


def main() -> None:
    parser = argparse.ArgumentParser(description="Render landing showcase reels (bulk lane, off-peak)")
    parser.add_argument("keys", nargs="*")
    parser.add_argument("--now", action="store_true", help="skip the off-peak window (dev machine only)")
    args = parser.parse_args()
    if not args.now and not in_offpeak(_dt.datetime.now(), offpeak_hours()):
        raise SystemExit("outside the off-peak window (SHOWCASE_OFFPEAK_HOURS); pass --now on a dev machine")
    with contextlib.suppress(OSError, AttributeError):
        os.nice(19)
    keys = args.keys or [r["key"] for r in plan.REELS]
    reels = {r["key"]: r for r in plan.REELS}
    results = []
    for key in keys:
        free_gb = shutil.disk_usage("/").free / 1e9
        if free_gb < MIN_FREE_GB:
            logger.warning(f"only {free_gb:.1f} GB free; stopping before {key}")
            break
        try:
            results.append(render(reels[key]))
        except Exception as exc:  # noqa: BLE001 - keep going
            logger.exception(f"{key} failed")
            results.append({"key": key, "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(results[-1]), flush=True)
    with open(os.path.join(WORK, f"results-{int(time.time())}.json"), "w") as handle:
        json.dump(results, handle, indent=1)


if __name__ == "__main__":
    main()
