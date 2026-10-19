"""What each app does (MH8). Local tools run on our CPU for $0; image edits call one hosted model.

* ``image_edit``: the hosted edit model on the fal queue (``fal-ai/flux-pro/kontext``,
  $0.04 an image at cost, source and date in each app file), one call per prompt.
* ``transition``: two photos into a 5 s vertical clip with a moving cross-fade (ffmpeg).
* ``remove_bg``: a transparent PNG cut-out with rembg (MIT; BiRefNet model, MIT) when installed.
* ``beat_cut``: the clip re-cut so every cut lands on a beat of a library track
  (onset envelope, then ``loops.beat_cut.snap_cuts_to_beats``), with the track mixed in.
* ``hook_score``: first-3 s signals measured from the clip (motion, early cut,
  audio onset, speech share), scored by ``loops.predict_hook``; text and face
  signals are not measured and are reported as not measured.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.domains.film.story8_render import FPS, GOP, HEIGHT, WIDTH, RenderError, ffmpeg_bin, run

EDIT_ENDPOINT = "https://fal.run/fal-ai/flux-pro/kontext"
TRANSITION_SECONDS = 5.0
BEAT_CUT_MAX_S = 30.0
SAMPLE_RATE = 22050
HOP = 512


class AppRunError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Hosted image edit
# --------------------------------------------------------------------------- #
def edit_image(prompt: str, image_url: str, *, session: Any = None, api_key: str = "") -> bytes:
    import requests

    key = api_key or os.getenv("FAL_KEY", "")
    if not key:
        raise AppRunError("this app is not switched on yet")
    http = session or requests
    response = http.post(EDIT_ENDPOINT, headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
                         json={"prompt": prompt, "image_url": image_url}, timeout=120)
    if response.status_code >= 400:
        raise AppRunError(f"the image model refused this photo ({response.status_code})")
    images = (response.json() or {}).get("images") or []
    url = str((images[0] or {}).get("url") or "") if images else ""
    if not url.startswith("https://"):
        raise AppRunError("the image model returned no image")
    got = http.get(url, timeout=120)
    if got.status_code >= 400:
        raise AppRunError("the edited image could not be downloaded")
    return got.content


def edit_prompts(edit: dict[str, Any], text: str = "") -> list[str]:
    templates = list(edit.get("prompts") or [])
    angles = list(edit.get("angles") or [])
    if angles:
        return [templates[0].format(angle=angle) for angle in angles]
    return [t.format(text=text.strip()) for t in templates]


# --------------------------------------------------------------------------- #
# Transition
# --------------------------------------------------------------------------- #
def transition_command(first: str, second: str, out: str, *, seconds: float = TRANSITION_SECONDS,
                       ffmpeg: str | None = None) -> list[str]:
    half = seconds / 2
    fade = 1.0
    prep = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
            f"zoompan=z='1+0.06*on/{int(half * FPS + fade * FPS)}':d={int(half * FPS + fade * FPS)}:"
            f"s={WIDTH}x{HEIGHT}:fps={FPS},setsar=1,format=yuv420p")
    graph = (f"[0:v]{prep}[a];[1:v]{prep}[b];"
             f"[a][b]xfade=transition=smoothleft:duration={fade}:offset={half - fade / 2:.2f},format=yuv420p[v]")
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-t",
            f"{half + fade:.2f}", "-i", first, "-loop", "1", "-t", f"{half + fade:.2f}", "-i", second,
            "-filter_complex", graph, "-map", "[v]", "-t", f"{seconds:.2f}", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "21", "-pix_fmt", "yuv420p", "-g", str(GOP), "-r", str(FPS), "-movflags", "+faststart", out]


# --------------------------------------------------------------------------- #
# Remove background
# --------------------------------------------------------------------------- #
def remove_background(image: bytes, *, remover: Callable[[bytes], bytes] | None = None) -> bytes:
    if remover is None:
        try:
            from rembg import new_session, remove
        except ImportError as exc:
            raise AppRunError("background removal is not installed on this server") from exc
        session = new_session(os.getenv("APPS_REMBG_MODEL", "birefnet-general-lite"))
        out = remove(image, session=session)
    else:
        out = remover(image)
    from PIL import Image

    with Image.open(io.BytesIO(out)) as im:
        if im.mode != "RGBA":
            raise AppRunError("the cut-out has no transparency")
    return out


# --------------------------------------------------------------------------- #
# Audio analysis shared by beat cut and hook score
# --------------------------------------------------------------------------- #
def decode_audio(path: str, *, seconds: float | None = None, ffmpeg: str | None = None):
    import numpy as np

    command = [ffmpeg or ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-i", path]
    if seconds:
        command += ["-t", f"{seconds:.2f}"]
    command += ["-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    done = subprocess.run(command, capture_output=True, timeout=120, check=False)
    if done.returncode != 0:
        raise RenderError("could not read the audio")
    return np.frombuffer(done.stdout, dtype=np.int16).astype("float32") / 32768.0


def rms_envelope(samples) -> Any:
    import numpy as np

    if len(samples) < HOP:
        return np.zeros(0, dtype="float32")
    frames = len(samples) // HOP
    blocks = samples[: frames * HOP].reshape(frames, HOP)
    return np.sqrt((blocks ** 2).mean(axis=1))


def detect_beats(samples, *, min_gap_s: float = 0.28) -> list[float]:
    """Beat times from the positive onset envelope with peak picking (seconds)."""
    import numpy as np

    env = rms_envelope(samples)
    if env.size < 3:
        return []
    onset = np.maximum(0.0, np.diff(env, prepend=env[0]))
    if onset.max() <= 0:
        return []
    threshold = onset.mean() + 1.0 * onset.std()
    hop_s = HOP / SAMPLE_RATE
    min_gap = int(min_gap_s / hop_s)
    beats, last = [], -min_gap
    for i in range(1, len(onset) - 1):
        if onset[i] >= threshold and onset[i] >= onset[i - 1] and onset[i] >= onset[i + 1] and i - last >= min_gap:
            beats.append(round(i * hop_s, 3))
            last = i
    return beats


# --------------------------------------------------------------------------- #
# Beat-synced cut
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Segment:
    source_start: float
    duration: float


def plan_beat_cut(clip_seconds: float, beats: Sequence[float], *, every_s: float = 1.2,
                  jump_s: float = 0.4) -> list[Segment]:
    """Cut points every ~``every_s`` snapped to beats; each cut jumps the source forward a little."""
    from app.services.loops.beat_cut import snap_cuts_to_beats

    length = min(float(clip_seconds), BEAT_CUT_MAX_S)
    if length <= 1.0 or not beats:
        raise AppRunError("the clip or the track is too short to cut on the beat")
    raw = [t for t in _frange(every_s, length, every_s)]
    snapped = sorted({round(c.nudged_s, 3) for c in snap_cuts_to_beats(raw, list(beats), fps=FPS)
                      if 0.3 < c.nudged_s < length - 0.3})
    points = [0.0, *snapped, length]
    segments, offset = [], 0.0
    for start, end in zip(points, points[1:]):
        duration = end - start
        if duration <= 0.05:
            continue
        source = start + offset
        if source + duration > clip_seconds:
            source = max(0.0, clip_seconds - duration)
        segments.append(Segment(source_start=round(source, 3), duration=round(duration, 3)))
        offset += jump_s
    return segments


def _frange(start: float, stop: float, step: float):
    value = start
    while value < stop:
        yield value
        value += step


def beat_cut_command(clip: str, music: str, segments: Sequence[Segment], out: str, *,
                     ffmpeg: str | None = None) -> list[str]:
    parts, labels = [], []
    for i, seg in enumerate(segments):
        parts.append(f"[0:v]trim=start={seg.source_start}:duration={seg.duration},setpts=PTS-STARTPTS,"
                     f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
                     f"fps={FPS},setsar=1[s{i}]")
        labels.append(f"[s{i}]")
    total = sum(s.duration for s in segments)
    graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(segments)}:v=1:a=0[v];" \
        f"[1:a]atrim=duration={total:.3f},loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100[a]"
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", clip, "-i", music,
            "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "21", "-pix_fmt", "yuv420p", "-g", str(GOP), "-r", str(FPS), "-c:a", "aac", "-b:a", "160k",
            "-t", f"{total:.3f}", "-movflags", "+faststart", out]


# --------------------------------------------------------------------------- #
# Hook score signals
# --------------------------------------------------------------------------- #
def probe_seconds(path: str) -> float:
    ffprobe = ffmpeg_bin().replace("ffmpeg", "ffprobe")
    done = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                          capture_output=True, text=True, timeout=30, check=False)
    try:
        return float(json.loads(done.stdout or "{}")["format"]["duration"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AppRunError("we could not read that clip") from exc


def frame_diffs(path: str, *, seconds: float = 3.0, fps: int = 10, ffmpeg: str | None = None) -> list[float]:
    """Mean absolute difference between consecutive 64x114 grey frames (0..1)."""
    import numpy as np

    w, h = 64, 114
    done = subprocess.run([ffmpeg or ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-i", path, "-t",
                           f"{seconds:.2f}", "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                          capture_output=True, timeout=120, check=False)
    if done.returncode != 0:
        raise RenderError("could not read the video")
    frames = np.frombuffer(done.stdout, dtype=np.uint8)
    count = len(frames) // (w * h)
    if count < 2:
        return []
    stack = frames[: count * w * h].reshape(count, h, w).astype("float32") / 255.0
    return [float(x) for x in np.abs(np.diff(stack, axis=0)).mean(axis=(1, 2))]


def hook_signals(path: str, *, hook_end_s: float = 3.0) -> dict[str, Any]:
    import numpy as np

    diffs = frame_diffs(path, seconds=hook_end_s)
    motion = min(1.0, float(np.mean(diffs)) * 8) if diffs else 0.0
    early_cut = 1.0 if any(d > 0.25 for d in diffs[:15]) else 0.0
    try:
        samples = decode_audio(path, seconds=hook_end_s)
    except RenderError:
        samples = np.zeros(0, dtype="float32")
    env = rms_envelope(samples)
    first = env[: int(0.5 * SAMPLE_RATE / HOP)]
    audio_onset = min(1.0, float(first.max()) * 6) if first.size else 0.0
    speech = float((env > 0.02).mean()) if env.size else 0.0
    return {"motion": round(motion, 3), "early_cut": early_cut, "audio_onset": round(audio_onset, 3),
            "speech": round(speech, 3), "text": 0.0, "face_or_subject": 0.0, "hook_end_s": hook_end_s,
            "not_measured": ["text", "face_or_subject"]}


def score_hook(signals: dict[str, Any], opening_line: str = "") -> dict[str, Any]:
    from app.services.loops import HookSignals, predict_hook, suggest_hooks

    fields = {k: signals[k] for k in ("motion", "text", "audio_onset", "early_cut", "speech", "face_or_subject",
                                      "hook_end_s")}
    res = predict_hook(HookSignals(**fields))
    suggestions = ([{"shape": s.shape, "text": s.text} for s in
                    suggest_hooks(opening_line, passes_gate=res.passes_gate, reasons=res.reasons)]
                   if opening_line and not res.passes_gate else [])
    return {"score": res.score, "passes_gate": res.passes_gate, "grade": res.grade, "reasons": list(res.reasons),
            "suggestions": suggestions, "signals": signals}


__all__ = ["AppRunError", "Segment", "beat_cut_command", "detect_beats", "edit_image", "edit_prompts",
           "hook_signals", "plan_beat_cut", "probe_seconds", "remove_background", "score_hook",
           "transition_command", "run"]
