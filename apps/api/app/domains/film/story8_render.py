"""FFmpeg steps for the story in 8 frames (MH5): Ken Burns frames, clip fitting, final mux.

Pure command builders plus thin runners, so the commands are unit-tested and
the runners are exercised with the real ``ffmpeg`` in an integration test.
Every output is 720x1280, 30 fps, H.264 with a 2 s GOP, AAC 44.1 kHz stereo,
narration normalised to about -15 LUFS (target). Captions are burned with the
existing karaoke ASS builder (M2.4 rules: 2 to 4 words a line) or, for presets
with static captions (very-time), whole sentences in the look's caption style.

Grade (LUT) application point: the final mux. A preset look's ``lut3d`` grade
and the optional console 480-line degrade run on the concatenated video in
the same encode that burns the captions, BEFORE the ``ass`` filter, so the
subtitle colour is never graded and the video is encoded once more only (no
extra pass). When this ffmpeg has no ``lut3d`` filter the LUT is skipped with a
log line and the render carries on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from loguru import logger

WIDTH, HEIGHT, FPS = 720, 1280, 30
GOP = FPS * 2
ZOOM = 0.12
# Scale up before zoompan so slow moves do not jitter on integer pixel steps.
_OVERSCAN = 2


def ffmpeg_bin() -> str:
    found = os.getenv("IMAGEIO_FFMPEG_EXE") or shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def has_filter(name: str, ffmpeg: str | None = None) -> bool:
    from app.services.compose.compose_ffmpeg import ffmpeg_has_filter

    return bool(ffmpeg_has_filter(name, ffmpeg or ffmpeg_bin()))


def _zoompan(camera: str, frames: int) -> str:
    d = max(1, int(frames))
    size = f"{WIDTH}x{HEIGHT}"
    centre_x, centre_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if camera == "pull_out":
        z, x, y = f"{1 + ZOOM}-{ZOOM}*on/{d}", centre_x, centre_y
    elif camera == "pan_right":
        z, x, y = "1.08", f"(iw-iw/zoom)*on/{d}", centre_y
    elif camera == "pan_left":
        z, x, y = "1.08", f"(iw-iw/zoom)*(1-on/{d})", centre_y
    elif camera == "hold":  # locked-off: no move at all
        z, x, y = "1", centre_x, centre_y
    else:  # push_in and anything unknown
        z, x, y = f"1+{ZOOM}*on/{d}", centre_x, centre_y
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={d}:s={size}:fps={FPS}"


def _video_out(out_path: str) -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-g", str(GOP), "-keyint_min", str(GOP), "-sc_threshold", "0", "-r", str(FPS), out_path]


def ken_burns_command(image_path: str, out_path: str, *, seconds: float, camera: str,
                      ffmpeg: str | None = None) -> list[str]:
    frames = max(1, int(round(float(seconds) * FPS)))
    big_w, big_h = WIDTH * _OVERSCAN, HEIGHT * _OVERSCAN
    vf = (f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,crop={big_w}:{big_h},"
          f"{_zoompan(camera, frames)},setsar=1,format=yuv420p")
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", image_path,
            "-vf", vf, "-frames:v", str(frames), "-an", *_video_out(out_path)]


def fit_clip_command(clip_path: str, out_path: str, *, seconds: float, ffmpeg: str | None = None) -> list[str]:
    """An animated shot fitted to the frame slot: cover-crop, 30 fps, padded or cut to ``seconds``."""
    vf = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps={FPS},"
          f"tpad=stop_mode=clone:stop_duration={float(seconds):.3f},setsar=1,format=yuv420p")
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", clip_path, "-vf", vf,
            "-t", f"{float(seconds):.3f}", "-an", *_video_out(out_path)]


def concat_command(clips: Sequence[str], out_path: str, *, ffmpeg: str | None = None) -> list[str]:
    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", clip]
    streams = "".join(f"[{i}:v]" for i in range(len(clips)))
    graph = f"{streams}concat=n={len(clips)}:v=1:a=0[v]"
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", *inputs,
            "-filter_complex", graph, "-map", "[v]", *_video_out(out_path)]


def _escape_filter_path(path: str) -> str:
    from app.services.compose.compose_ffmpeg import _escape_ass_filter_path

    return _escape_ass_filter_path(path)


def mux_command(video_path: str, audio_path: str, out_path: str, *, ass_path: str | None = None,
                fonts_dir: str | None = None, ffmpeg: str | None = None, video_filters: Sequence[str] = (),
                audio_delay_s: float = 0.0, audio_filter: str | None = None) -> list[str]:
    """Final encode: the video track (graded first when ``video_filters`` are given), the narration
    (loudness-normalised; delayed and padded to the video when ``audio_delay_s`` > 0) and burned captions.

    ``audio_filter`` replaces the whole audio chain (no loudnorm, no delay): use it for a track that
    is already mixed and mastered to the video length (very-time's -14 LUFS mix), e.g. ``"anull"``."""
    parts = [str(f) for f in video_filters if f]
    if ass_path:
        burn = f"ass={_escape_filter_path(ass_path)}"
        if fonts_dir:
            burn += f":fontsdir={_escape_filter_path(fonts_dir)}"
        parts.append(burn)
    vf = ",".join(parts) or "null"
    audio = "loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100"
    if audio_filter is not None:
        audio = str(audio_filter).strip() or "anull"
    elif audio_delay_s and audio_delay_s > 0:
        audio += f",adelay=delays={int(round(float(audio_delay_s) * 1000))}:all=1,apad"
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", video_path, "-i", audio_path,
            "-filter_complex", f"[0:v]{vf}[v];[1:a]{audio}[a]",
            "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-shortest",
            "-movflags", "+faststart", *_video_out(out_path)]


def poster_command(video_path: str, out_path: str, *, at_s: float = 0.5, ffmpeg: str | None = None) -> list[str]:
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at_s:.2f}",
            "-i", video_path, "-frames:v", "1", "-q:v", "3", out_path]


class RenderError(RuntimeError):
    pass


def run(command: Sequence[str], *, timeout_s: float = 600.0) -> None:
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg timed out after {timeout_s:.0f} s") from exc
    if done.returncode != 0:
        raise RenderError((done.stderr or "ffmpeg failed").strip()[-600:])


KARAOKE = "karaoke"


def captions_ass(words: Sequence[Sequence[object]], style: str = KARAOKE, *,
                 lines: Sequence[tuple[str, float, float]] | None = None, language: str = "") -> str:
    """ASS captions from ``[[text, start_s, end_s], ...]``.

    ``karaoke`` (default): 2 to 4 words a line, word by word. Any static style id
    (``game_yellow``, ``serif_lower_third``): whole sentences from ``lines``
    (``(text, start_s, end_s)``) or, without them, the words as one sentence.
    """
    if style != KARAOKE:
        from app.services.captions.ass_static import build_static_ass

        if lines is None:
            spoken = [w for w in words if str(w[0]).strip()]
            lines = [(" ".join(str(w[0]) for w in spoken), float(spoken[0][1]), float(spoken[-1][2]))] if spoken else []
        return build_static_ass(lines, style, WIDTH, HEIGHT, language=language)
    from app.services.captions.ass_karaoke import KaraokeStyle, build_ass
    from app.services.captions.words import WordTiming, group_words_into_phrases

    timings = [WordTiming(str(w[0]), float(w[1]), float(w[2])) for w in words if str(w[0]).strip()]
    lines = group_words_into_phrases(timings, max_words=4, min_words=2)
    style = KaraokeStyle(fontsize=58, margin_v=250, margin_lr=40, play_w=WIDTH, play_h=HEIGHT, outline=4)
    return build_ass(lines, style)


def look_filters(look: Mapping[str, Any] | None, *, ffmpeg: str | None = None,
                 lut_available: bool | None = None) -> list[str]:
    """Grade filters for a preset look (``{"lut": id, "degrade": "console"}``), applied at the final mux.

    The LUT needs ffmpeg's ``lut3d`` filter; without it the grade is skipped with a
    log line (never a failed render). The console degrade is plain ``scale``.
    """
    if not look:
        return []
    from app.services.compose import vfx

    lut_id = str(look.get("lut") or "")
    available = True
    if lut_id:
        available = has_filter("lut3d", ffmpeg) if lut_available is None else bool(lut_available)
        if not available:
            logger.info(f"story render: ffmpeg has no lut3d filter; skipping the {lut_id} grade")
    return vfx.look_filters(lut_id, width=WIDTH, height=HEIGHT, degrade=str(look.get("degrade") or "none"),
                            lut_available=available)


__all__ = [
    "FPS", "GOP", "HEIGHT", "KARAOKE", "RenderError", "WIDTH", "captions_ass", "concat_command", "ffmpeg_bin",
    "fit_clip_command", "has_filter", "ken_burns_command", "look_filters", "mux_command", "poster_command", "run",
]
