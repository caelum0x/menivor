"""Animated narrator rig (M2.3): lip-synced mouth, blink and bob, CPU only.

The mouth timeline is derived from the narration audio. The primary source is
Rhubarb Lip Sync (MIT, https://github.com/DanielSWolf/rhubarb-lip-sync), run
with its language-independent ``phonetic`` recogniser; set ``RHUBARB_BIN`` or
put ``rhubarb`` on ``PATH``. When Rhubarb is not installed, an energy and
zero-crossing estimate over the same audio produces a coarser timeline in the
same alphabet, so a render never fails for want of the binary. Either way the
mouth is closed (``X``) wherever the audio is silent.

:func:`render_narrator_clip` rasterises the character's locked reference sheet
(:mod:`app.domains.characters.narrator_art`) frame by frame and pipes raw RGB
into FFmpeg, producing a square H.264 clip the story scene overlays.

Art gate (O9): :func:`rig_enabled` is false until the roster's ``art_status``
is ``approved`` or ``MENIVOR_NARRATOR_RIG=1`` is set.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

try:  # loguru ships with the API; keep the module import-safe without it.
    from loguru import logger
except Exception:  # pragma: no cover - fallback only when loguru is absent.
    import logging

    logger = logging.getLogger(__name__)

from app.domains.characters.narrator_art import MOUTH_SHAPES, render_pose, sheet_hash
from app.domains.characters.narrators import ROSTER_PATH, NarratorCharacter

__all__ = [
    "FPS",
    "MouthCue",
    "NarratorClip",
    "blink_track",
    "bob_offsets",
    "energy_cues",
    "mouth_track",
    "render_narrator_clip",
    "rhubarb_binary",
    "rhubarb_cues",
    "rig_enabled",
    "viseme_cues",
]

FPS = 30
SIZE = 440  # matches services.styles.scene.CHARACTER_SIZE
_BOB_PX = 7.0
_BOB_HZ = 0.9
_BLINK_FRAMES = 4
_ANALYSIS_RATE = 16000
_SILENCE_FLOOR_DB = -45.0
_SILENCE_BELOW_PEAK_DB = 32.0


@dataclass(frozen=True)
class MouthCue:
    start: float
    end: float
    value: str


@dataclass(frozen=True)
class NarratorClip:
    path: str
    character_id: str
    sheet_sha256: str
    source: str  # "rhubarb" or "energy"
    cues: tuple[MouthCue, ...]
    frames: int


def rig_enabled() -> bool:
    """True once the owner approved the art (roster) or the env override is on."""
    if os.environ.get("MENIVOR_NARRATOR_RIG", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        raw = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return str(raw.get("art_status", "")).strip().lower() == "approved"


def _ffmpeg() -> str:
    try:
        from app.utils import utils

        return utils.get_ffmpeg_binary() or "ffmpeg"
    except Exception:  # noqa: BLE001
        return "ffmpeg"


# --------------------------------------------------------------------------- #
# Viseme timeline
# --------------------------------------------------------------------------- #
def rhubarb_binary() -> Optional[str]:
    explicit = (os.environ.get("RHUBARB_BIN") or "").strip()
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return explicit
    return shutil.which("rhubarb")


def _parse_rhubarb(stdout: str) -> list[MouthCue]:
    data = json.loads(stdout)
    cues = []
    for cue in data.get("mouthCues", []):
        value = str(cue.get("value", "X"))
        cues.append(MouthCue(float(cue["start"]), float(cue["end"]), value if value in MOUTH_SHAPES else "X"))
    return cues


def _to_wav(audio_path: str, out_path: str, ffmpeg: str) -> None:
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", audio_path,
         "-vn", "-ac", "1", "-ar", str(_ANALYSIS_RATE), "-c:a", "pcm_s16le", out_path],
        check=True, timeout=300, capture_output=True,
    )


def rhubarb_cues(audio_path: str, work_dir: str, *, binary: Optional[str] = None,
                 ffmpeg: Optional[str] = None) -> Optional[list[MouthCue]]:
    """Rhubarb's mouth cues for ``audio_path``, or ``None`` if it is unavailable/fails."""
    rhubarb = binary or rhubarb_binary()
    if not rhubarb:
        return None
    os.makedirs(work_dir, exist_ok=True)
    wav = os.path.join(work_dir, "rig-voice.wav")
    try:
        _to_wav(audio_path, wav, ffmpeg or _ffmpeg())
        completed = subprocess.run(
            [rhubarb, "-q", "-f", "json", "-r", "phonetic", wav],
            capture_output=True, text=True, timeout=600, check=False,
        )
        if completed.returncode != 0:
            logger.warning(f"narrator rig: rhubarb exited {completed.returncode}")
            return None
        return _parse_rhubarb(completed.stdout)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        logger.warning(f"narrator rig: rhubarb failed ({type(exc).__name__}); using energy cues")
        return None


def _pcm_windows(audio_path: str, ffmpeg: str, window: int) -> list[tuple[float, float]]:
    """(rms, zero-crossing rate) per ``window`` samples of 16 kHz mono audio."""
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", audio_path, "-vn",
         "-ac", "1", "-ar", str(_ANALYSIS_RATE), "-f", "s16le", "-"],
        capture_output=True, timeout=300, check=True,
    )
    raw = completed.stdout
    count = len(raw) // 2
    samples = struct.unpack(f"<{count}h", raw[: count * 2])
    out: list[tuple[float, float]] = []
    for start in range(0, count, window):
        chunk = samples[start:start + window]
        if not chunk:
            break
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk)) / 32768.0
        crossings = sum(1 for a, b in zip(chunk, chunk[1:]) if (a < 0) != (b < 0))
        out.append((rms, crossings / max(1, len(chunk) - 1)))
    return out


def energy_cues(audio_path: str, *, fps: int = FPS, ffmpeg: Optional[str] = None) -> list[MouthCue]:
    """Coarse mouth cues from loudness and brightness, in Rhubarb's alphabet.

    Silence (below ``-45`` dBFS or 32 dB under the peak) is ``X``. Speech frames
    map by relative loudness to B (quiet), C (mid) and D (loud); bright, noisy
    frames (fricatives) map to G, and a short closed ``A`` marks each onset.
    """
    window = _ANALYSIS_RATE // fps
    stats = _pcm_windows(audio_path, ffmpeg or _ffmpeg(), window)
    if not stats:
        return []
    levels = [20 * math.log10(max(rms, 1e-7)) for rms, _ in stats]
    peak = max(levels)
    gate = max(_SILENCE_FLOOR_DB, peak - _SILENCE_BELOW_PEAK_DB)
    voiced = sorted(level for level in levels if level > gate)
    median = voiced[len(voiced) // 2] if voiced else peak
    cues: list[MouthCue] = []
    previous = "X"
    step = 1.0 / fps
    for index, (level, (_, zcr)) in enumerate(zip(levels, stats)):
        if level <= gate:
            value = "X"
        elif previous == "X":
            value = "A"
        elif zcr > 0.3:
            value = "G"
        elif level >= median + 4:
            value = "D"
        elif level >= median - 3:
            value = "C"
        else:
            value = "B"
        start = round(index * step, 3)
        if cues and cues[-1].value == value:
            cues[-1] = MouthCue(cues[-1].start, round(start + step, 3), value)
        else:
            cues.append(MouthCue(start, round(start + step, 3), value))
        previous = value
    return cues


def viseme_cues(audio_path: str, work_dir: str, *, fps: int = FPS,
                ffmpeg: Optional[str] = None) -> tuple[list[MouthCue], str]:
    """Mouth cues for the narration: ``(cues, source)``."""
    cues = rhubarb_cues(audio_path, work_dir, ffmpeg=ffmpeg)
    if cues:
        return cues, "rhubarb"
    return energy_cues(audio_path, fps=fps, ffmpeg=ffmpeg), "energy"


# --------------------------------------------------------------------------- #
# Frame schedule
# --------------------------------------------------------------------------- #
def mouth_track(cues: Sequence[MouthCue], frames: int, fps: int = FPS) -> list[str]:
    """The mouth shape at the centre of each frame (``X`` outside any cue)."""
    track: list[str] = []
    ordered = sorted(cues, key=lambda c: c.start)
    pointer = 0
    for frame in range(frames):
        t = (frame + 0.5) / fps
        while pointer < len(ordered) and ordered[pointer].end <= t:
            pointer += 1
        cue = ordered[pointer] if pointer < len(ordered) else None
        track.append(cue.value if cue is not None and cue.start <= t < cue.end else "X")
    return track


def blink_track(character_id: str, frames: int, fps: int = FPS) -> list[bool]:
    """Eyes open (True) per frame; blinks every 2.6-4.6 s, fixed per character."""
    track = [True] * frames
    seed = hashlib.sha256(character_id.encode("utf-8")).digest()
    t, index = 1.2, 0
    while True:
        start = int(t * fps)
        if start >= frames:
            break
        for f in range(start, min(frames, start + _BLINK_FRAMES)):
            track[f] = False
        t += 2.6 + (seed[index % len(seed)] / 255.0) * 2.0
        index += 1
    return track


def bob_offsets(frames: int, fps: int = FPS) -> list[int]:
    return [int(round(_BOB_PX * math.sin(2 * math.pi * _BOB_HZ * f / fps))) for f in range(frames)]


def _probe_duration(path: str, ffmpeg: str) -> float:
    ffprobe = os.path.join(os.path.dirname(ffmpeg), "ffprobe") if os.path.dirname(ffmpeg) else "ffprobe"
    if not (os.path.isfile(ffprobe) or shutil.which(ffprobe)):
        ffprobe = "ffprobe"
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout.strip()
    return float(out)


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render_narrator_clip(
    character: NarratorCharacter,
    audio_path: str,
    out_path: str,
    *,
    work_dir: Optional[str] = None,
    size: int = SIZE,
    fps: int = FPS,
    duration_s: Optional[float] = None,
    ffmpeg: Optional[str] = None,
) -> NarratorClip:
    """Render the lip-synced narrator for ``audio_path`` to a square MP4 (no audio).

    Raises ``RuntimeError`` if FFmpeg fails; callers fall back to the still
    narrator scene.
    """
    from PIL import Image

    binary = ffmpeg or _ffmpeg()
    work = work_dir or os.path.dirname(os.path.abspath(out_path))
    duration = float(duration_s) if duration_s else _probe_duration(audio_path, binary)
    frames = max(1, int(math.ceil(duration * fps)))
    cues, source = viseme_cues(audio_path, work, fps=fps, ffmpeg=binary)
    mouths = mouth_track(cues, frames, fps)
    eyes = blink_track(character.id, frames, fps)
    bobs = bob_offsets(frames, fps)
    lock = sheet_hash(character)

    command = [
        binary, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size}x{size}", "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-g", str(fps * 2), "-movflags", "+faststart",
        "-metadata", f"comment=menivor-narrator:{character.id}:{lock}",
        out_path,
    ]
    backdrop = Image.new("RGB", (size, size), character.look.backdrop)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.stdin is None:  # pragma: no cover - Popen with PIPE always sets it
        raise RuntimeError("narrator rig encode failed: no stdin pipe")
    try:
        for frame in range(frames):
            pose = render_pose(character, mouths[frame], eyes[frame], size)
            canvas = backdrop.copy()
            canvas.paste(pose, (0, bobs[frame]))
            process.stdin.write(canvas.tobytes())
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
        code = process.wait(timeout=600)
    except (BrokenPipeError, subprocess.SubprocessError) as exc:
        process.kill()
        raise RuntimeError(f"narrator rig encode failed: {exc}") from exc
    if code != 0:
        raise RuntimeError(f"narrator rig encode failed: {stderr.strip()[-400:]}")
    return NarratorClip(
        path=out_path,
        character_id=character.id,
        sheet_sha256=lock,
        source=source,
        cues=tuple(cues),
        frames=frames,
    )
