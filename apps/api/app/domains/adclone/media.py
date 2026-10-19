"""Local, $0 media analysis with ffmpeg: probe, shot cuts, keyframes, audio onsets.

All functions take file paths and return new plain data. Subprocess calls use
argument lists (never a shell). Nothing here writes outside the given workdir.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_SCENE_THRESHOLD = 0.3
MIN_SHOT_S = 0.4
ONSET_SR = 8000
ONSET_HOP_S = 0.05
_PTS = re.compile(r"pts_time:([0-9.]+)")


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Probe:
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool


@dataclass(frozen=True)
class Shot:
    index: int
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, 3)

    @property
    def mid_s(self) -> float:
        return round((self.start_s + self.end_s) / 2, 3)


def _bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaError(f"{name} is not installed")
    return path


def _run(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603


def probe(path: str) -> Probe:
    out = _run([_bin("ffprobe"), "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", path])
    if out.returncode != 0:
        raise MediaError(f"ffprobe failed: {out.stderr.strip()[:200]}")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("no video stream")
    num, _, den = str(video.get("r_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return Probe(duration_s=float((data.get("format") or {}).get("duration") or 0.0),
                 width=int(video.get("width") or 0), height=int(video.get("height") or 0), fps=round(fps, 3),
                 has_audio=any(s.get("codec_type") == "audio" for s in streams))


def duration_s(path: str) -> float:
    """Container duration of any media file (audio-only files included)."""
    out = _run([_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    try:
        return round(float(out.stdout.strip()), 3)
    except ValueError as exc:
        raise MediaError(f"no duration for {os.path.basename(path)}") from exc


def parse_cut_times(showinfo_log: str) -> list[float]:
    return sorted({round(float(m), 3) for m in _PTS.findall(showinfo_log)})


def shots_from_cuts(cuts: list[float], duration_s: float, *, min_shot_s: float = MIN_SHOT_S) -> list[Shot]:
    """Turn cut timestamps into contiguous shots; cuts closer than ``min_shot_s`` are merged."""
    edges = [0.0]
    for t in sorted(cuts):
        if min_shot_s <= t <= duration_s - min_shot_s and t - edges[-1] >= min_shot_s:
            edges.append(round(t, 3))
    edges.append(round(duration_s, 3))
    return [Shot(i, edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def detect_shots(path: str, duration_s: float, *, threshold: float = DEFAULT_SCENE_THRESHOLD) -> list[Shot]:
    """ffmpeg scene-change filter (the PySceneDetect content detector is used when installed)."""
    try:
        from scenedetect import ContentDetector, detect  # noqa: PLC0415 - optional dependency

        scenes = detect(path, ContentDetector(threshold=threshold * 90))
        cuts = [s[0].get_seconds() for s in scenes[1:]]
    except Exception:  # noqa: BLE001 - optional dep absent or failed: fall back to ffmpeg
        out = _run([_bin("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-an", "-vf",
                    f"select=gt(scene\\,{threshold}),showinfo", "-f", "null", "-"])
        cuts = parse_cut_times(out.stderr)
    return shots_from_cuts(cuts, duration_s)


def extract_frame(path: str, at_s: float, out_path: str, *, width: int = 540) -> str:
    out = _run([_bin("ffmpeg"), "-v", "error", "-y", "-ss", f"{max(at_s, 0):.3f}", "-i", path,
                "-frames:v", "1", "-vf", f"scale={width}:-2", out_path])
    if out.returncode != 0 or not os.path.exists(out_path):
        raise MediaError(f"frame extract failed at {at_s:.2f}s")
    return out_path


def sample_times(duration_s: float, step_s: float = 0.5) -> list[float]:
    n = max(int(duration_s / step_s), 1)
    return [round(min(i * step_s + step_s / 2, max(duration_s - 0.05, 0)), 3) for i in range(n)]


def onsets_from_envelope(env: list[float], hop_s: float = ONSET_HOP_S, *, k: float = 1.6) -> list[float]:
    """Peaks of the positive energy flux above ``k`` x its mean (simple, dependency-light onset picker)."""
    if len(env) < 3:
        return []
    flux = [max(env[i] - env[i - 1], 0.0) for i in range(1, len(env))]
    mean = sum(flux) / len(flux) or 1e-9
    picks: list[float] = []
    for i in range(1, len(flux) - 1):
        if flux[i] > k * mean and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]:
            t = round((i + 1) * hop_s, 3)
            if not picks or t - picks[-1] >= 0.15:
                picks.append(t)
    return picks


def bpm_from_onsets(onsets: list[float]) -> float | None:
    """Median inter-onset interval folded into 70-180 BPM; None with too few onsets."""
    gaps = sorted(b - a for a, b in zip(onsets, onsets[1:]) if b - a > 0.2)
    if len(gaps) < 4:
        return None
    bpm = 60.0 / gaps[len(gaps) // 2]
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return round(bpm, 1)


def audio_envelope(path: str, *, hop_s: float = ONSET_HOP_S) -> list[float]:
    """Mono RMS envelope per hop from ffmpeg-decoded PCM (empty when the file has no audio)."""
    import array  # noqa: PLC0415

    out = subprocess.run([_bin("ffmpeg"), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(ONSET_SR),  # noqa: S603
                          "-f", "s16le", "-"], capture_output=True, timeout=300, check=False)
    if out.returncode != 0 or not out.stdout:
        return []
    pcm = array.array("h")
    pcm.frombytes(out.stdout[: len(out.stdout) // 2 * 2])
    hop = max(int(ONSET_SR * hop_s), 1)
    env = []
    for i in range(0, len(pcm) - hop + 1, hop):
        chunk = pcm[i:i + hop]
        env.append((sum(x * x for x in chunk) / hop) ** 0.5 / 32768.0)
    return env
