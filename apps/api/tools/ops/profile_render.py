"""Profile the CPU side of one style reel render (ops tool, no provider spend).

Runs the real FFmpeg steps a one-click style reel goes through on the worker
(scene track -> captions burn + narration mux -> poster + preview) on local
inputs only: a synthetic narration tone, the real ASS captions writer, the
packaged block-runner loop and an offline title card. No LLM, TTS, R2 or DB
calls, so it is safe to run anywhere the worker image runs.

    python apps/api/tools/ops/profile_render.py --scene meme --duration 25
    MENIVOR_X264_PRESET=medium python apps/api/tools/ops/profile_render.py

Prints one JSON line with per-step seconds, output sizes and peak child RSS.
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

SCRIPT = (
    "You met me at a very chaotic time in my life.\n\n"
    "Rally writes personal emails, chases replies and books meetings for you. "
    "It finds the right people, checks every address and drafts the first note. "
    "You stay on strategy while the pipeline keeps moving. Check the link to try it."
)


def _peak_child_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # Linux reports KiB, macOS bytes.
    return round(peak / 1024 if sys.platform != "darwin" else peak / (1024 * 1024), 1)


_STEP_RSS: dict[str, float] = {}
_CURRENT_STEP = {"name": ""}
_REAL_RUN = subprocess.run


def _measured_run(argv, *args, **kwargs):
    """``subprocess.run`` that records each child's peak RSS under the current step."""
    capture = bool(kwargs.get("capture_output"))
    text = bool(kwargs.get("text"))
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, stdout=out if capture else None, stderr=err if capture else None)
        _, status, usage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
        out.seek(0)
        err.seek(0)
        stdout, stderr = (out.read(), err.read()) if capture else (None, None)
    if text and capture:
        stdout, stderr = stdout.decode(errors="replace"), stderr.decode(errors="replace")
    rss = usage.ru_maxrss / 1024 if sys.platform != "darwin" else usage.ru_maxrss / (1024 * 1024)
    step = _CURRENT_STEP["name"]
    _STEP_RSS[step] = round(max(_STEP_RSS.get(step, 0.0), rss), 1)
    if kwargs.get("check") and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, argv, stdout, stderr)
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


def _mb(path: str) -> float:
    return round(os.path.getsize(path) / (1024 * 1024), 2) if os.path.isfile(path) else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scene", default="meme")
    parser.add_argument("--duration", type=float, default=25.0)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    from app.domains.content import background_library as bglib
    from app.models.schema import VideoAspect
    from app.services import preview
    from app.services.captions.ass_karaoke import write_ass
    from app.services.captions.presets import get_caption_style
    from app.services.captions.words import WordTiming, group_words_into_phrases
    from app.services.compose.compose_ffmpeg import (
        _x264_speed_args,
        compose_captions_over_screen,
    )
    from app.services.reelforge import _script_words_over_duration
    from app.services.styles import scene as scene_mod
    from app.services.styles.pipeline import hook_line
    from app.utils import utils

    ffmpeg = utils.get_ffmpeg_binary() or "ffmpeg"
    work = tempfile.mkdtemp(prefix="menivor-profile-")
    timings: dict[str, float] = {}

    subprocess.run = _measured_run  # type: ignore[assignment]

    def timed(name: str, fn, *a, **kw):
        _CURRENT_STEP["name"] = name
        started = time.monotonic()
        out = fn(*a, **kw)
        timings[name] = round(time.monotonic() - started, 2)
        return out

    try:
        audio = os.path.join(work, "audio.mp3")
        timed("narration", subprocess.run, [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=220:sample_rate=44100:duration={args.duration}",
            "-c:a", "libmp3lame", "-b:a", "128k", audio,
        ], check=True)

        words = _script_words_over_duration(SCRIPT, args.duration)
        timings_words = [WordTiming(str(w[0]), float(w[1]), float(w[2])) for w in words]
        ass = os.path.join(work, "captions.ass")
        timed("captions", write_ass, ass, group_words_into_phrases(timings_words),
              style=get_caption_style("meme_clean"))

        loop = ""
        if args.scene in scene_mod.LOOP_SCENES:
            clip = bglib.resolve("block-runner")
            loop = bglib.materialize(clip, task_id="profile", duration_s=args.duration)[0]

        screen = os.path.join(work, "style-screen.mp4")
        timed("scene", scene_mod.render_scene,
              scene=args.scene, images=[], loop_path=loop, hook=hook_line(SCRIPT),
              title="Rally", duration_s=args.duration + 0.4,
              font_path=os.path.join(utils.font_dir(), "Montserrat-ExtraBold.ttf"),
              work_dir=os.path.join(work, "scene"), out_path=screen, ffmpeg=ffmpeg)

        final = os.path.join(work, "final.mp4")
        timed("compose", compose_captions_over_screen, screen, audio, final,
              ass_path=ass, aspect=VideoAspect.portrait)

        timed("poster", preview.generate_poster, final, os.path.join(work, "poster.jpg"), at_s=1.0)
        timed("preview", preview.generate_preview_clip, final,
              os.path.join(work, "preview.mp4"), duration_s=5.0)

        print(json.dumps({
            "scene": args.scene,
            "duration_s": args.duration,
            "cpus": os.cpu_count(),
            "x264": _x264_speed_args("libx264"),
            "seconds": timings,
            "total_s": round(sum(timings.values()), 2),
            "sizes_mb": {"scene": _mb(screen), "final": _mb(final)},
            "peak_child_rss_mb": _peak_child_rss_mb(),
            "step_peak_rss_mb": _STEP_RSS,
        }))
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"kept {work}", file=sys.stderr)


if __name__ == "__main__":
    main()
