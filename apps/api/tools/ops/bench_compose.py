"""Benchmark one 30 s faceless style reel: old render path vs new (M1.1/M1.2).

``before``: FFmpeg ``medium`` preset, the scene encoded to an intermediate,
the loop mix re-encoded, then the captions compose (three full encodes).
``after``: ``veryfast``/CRF 21/2 s GOP, the pre-encoded loops joined by stream
copy and the single-pass compose (one full encode).

Local inputs only (packaged loops, a synthetic page clip and narration tone,
a one-line ASS file): no LLM, TTS, R2 or DB. Needs an FFmpeg with libass and
drawtext (set ``IMAGEIO_FFMPEG_EXE`` if the one on PATH lacks them).

    python apps/api/tools/ops/bench_compose.py --duration 30
    python apps/api/tools/ops/bench_compose.py --style meme_hook --keep /tmp/bench

Prints one JSON line per mode with wall seconds, peak child RSS (MB), full
encodes, and output size, plus the speed-up.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,2,40,40,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:{end:05.2f},Default,,0,0,0,,One click makes the reel
"""


def _peak_child_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return round(peak / 1024 if sys.platform != "darwin" else peak / (1024 * 1024), 1)


def _inputs(work: str, ffmpeg: str, duration: float) -> dict:
    ff = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    page = os.path.join(work, "page.mp4")
    subprocess.run([*ff, "-f", "lavfi", "-i", f"testsrc2=s=1080x960:r=30:d={duration}", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", page], check=True)
    audio = os.path.join(work, "voice.m4a")
    subprocess.run([*ff, "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration}", "-c:a", "aac", audio],
                   check=True)
    ass = os.path.join(work, "captions.ass")
    with open(ass, "w", encoding="utf-8") as handle:
        handle.write(_ASS.format(end=min(59.0, duration)))
    return {"page": page, "audio": audio, "ass": ass}


def _run_mode(mode: str, style_id: str, media: dict, work: str, duration: float) -> dict:
    from app.domains.styles.catalog import get_style
    from app.services.compose import encode_count
    from app.services.compose.compose_ffmpeg import compose_captions_over_screen
    from app.services.compose.single_pass import compose_scene_with_captions
    from app.services.styles import pipeline, scene

    style = get_style(style_id)
    if mode == "before":
        os.environ["MENIVOR_X264_PRESET"] = "medium"
        os.environ["MENIVOR_LOOP_CACHE"] = os.path.join(work, "no-cache")
        from app.services.loops import prepared

        real_prepared = prepared.prepared_loop
        prepared.prepared_loop = lambda src, *a, **k: src  # the old path had no prepared loops
    else:
        os.environ.pop("MENIVOR_X264_PRESET", None)
        os.environ["MENIVOR_LOOP_CACHE"] = os.path.join(work, "loop-cache")
        from app.services.loops import prepared

        prepared.prewarm(prepared.packaged_loops(), ("1080",))  # done at image build, not per reel
        real_prepared = None
    try:
        start = time.monotonic()
        mode_dir = os.path.join(work, mode)
        with encode_count.tally() as counts:
            loop = pipeline._loop_path(style.background_id or "block-runner", f"bench-{mode}", duration,
                                       os.path.join(mode_dir, "loop"))
            kwargs = {
                "scene": style.scene, "images": [], "loop_path": loop,
                "hook": "You met me at a very chaotic time in my life.", "title": "Menivor",
                "duration_s": duration, "font_path": pipeline._font_path(),
                "work_dir": os.path.join(mode_dir, "scene"), "ffmpeg": pipeline._ffmpeg(),
                "visual_video": media["page"] if style.visual == "page" else "",
            }
            out = os.path.join(mode_dir, "final.mp4")
            if mode == "before":
                screen = scene.render_scene(out_path=os.path.join(mode_dir, "screen.mp4"), **kwargs)
                compose_captions_over_screen(screen, media["audio"], out, ass_path=media["ass"])
            else:
                spec = scene.prepare_scene(**kwargs)
                compose_scene_with_captions(spec, media["audio"], out, ass_path=media["ass"])
        wall = round(time.monotonic() - start, 2)
    finally:
        if real_prepared is not None:
            prepared.prepared_loop = real_prepared
    return {
        "mode": mode, "style": style_id, "duration_s": duration, "wall_s": wall,
        "peak_child_rss_mb": _peak_child_rss_mb(), "full_encodes": encode_count.total(counts),
        "by_kind": counts, "output_mb": round(os.path.getsize(out) / 1e6, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--style", default="gameplay_split")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--keep", default="", help="keep outputs in this directory")
    args = parser.parse_args()

    from app.utils import utils

    ffmpeg = utils.get_ffmpeg_binary()
    work = args.keep or tempfile.mkdtemp(prefix="menivor-bench-")
    os.makedirs(work, exist_ok=True)
    try:
        media = _inputs(work, ffmpeg, args.duration)
        # Separate processes would isolate RSS; ru_maxrss is a running peak, so
        # "before" runs first and "after" reports max(before, after).
        before = _run_mode("before", args.style, media, work, args.duration)
        print(json.dumps(before))
        after = _run_mode("after", args.style, media, work, args.duration)
        print(json.dumps(after))
        print(json.dumps({"speedup": round(before["wall_s"] / max(0.01, after["wall_s"]), 2)}))
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
