"""Very ___ Time sound: room tone, per-beat SFX and the voice, ducked and mastered.

Pure command builders plus thin runners (like ``story8_render``), so the
commands are unit-tested and the runners are exercised with the real ffmpeg.

The mix (one ``filter_complex``):

* **voice** (VO): delayed to its beat (``adelay ... all=1``), split into the
  voice itself and a sidechain key;
* **bed**: the room tone (the video model's own audio per shot, or silence) and
  each SFX delayed to its beat start, summed with ``amix normalize=0`` (no
  automatic gain riding);
* the bed is ducked under the voice with
  ``sidechaincompress=threshold=0.03:ratio=8:attack=5:release=350`` keyed on
  the voice, then summed with the voice (``amix normalize=0``) and trimmed to
  the video length, 48 kHz stereo wav;
* the result is mastered with two-pass ``loudnorm`` to -14 LUFS integrated,
  -1.5 dBTP, LRA 11 (the social target in the Very Turkish Time method).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from loguru import logger

TARGET_LUFS = -14.0
TRUE_PEAK = -1.5
LRA = 11.0
SAMPLE_RATE = 48000
DUCK = "sidechaincompress=threshold=0.03:ratio=8:attack=5:release=350"
_FORMAT = f"aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
_SLOT = re.compile(r"\{(\w+)\}")
_SILENT_LUFS = -70.0


class AudioError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    from . import story8_render

    return story8_render.ffmpeg_bin()


def ffprobe_bin(ffmpeg: str | None = None) -> str:
    binary = ffmpeg or ffmpeg_bin()
    sibling = os.path.join(os.path.dirname(binary), "ffprobe")
    if os.path.dirname(binary) and os.path.isfile(sibling):
        return sibling
    return shutil.which("ffprobe") or ""


def run(command: Sequence[str], *, timeout_s: float = 600.0) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"ffmpeg timed out after {timeout_s:.0f} s") from exc
    if done.returncode != 0:
        raise AudioError((done.stderr or "ffmpeg failed").strip()[-600:])
    return done


def _ms(seconds: float) -> int:
    return max(0, int(round(float(seconds) * 1000)))


def _total(seconds: float) -> str:
    return f"{max(0.01, float(seconds)):.3f}"


def _wav_out(out: str) -> list[str]:
    return ["-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_s16le", out]


# --------------------------------------------------------------------------- #
# Probing
# --------------------------------------------------------------------------- #
def has_audio_stream(path: str, *, ffmpeg: str | None = None) -> bool:
    """Whether ``path`` carries at least one audio stream."""
    if not path or not os.path.isfile(path):
        return False
    probe = ffprobe_bin(ffmpeg)
    if probe:
        try:
            done = subprocess.run([probe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                   "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60, check=False)
            if done.returncode == 0:
                return bool(done.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    try:  # fallback: ffmpeg prints the stream list on stderr
        done = subprocess.run([ffmpeg or ffmpeg_bin(), "-hide_banner", "-i", path], capture_output=True, text=True,
                              timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(re.search(r"Stream #\d+:\d+.*: Audio:", done.stderr or ""))


# --------------------------------------------------------------------------- #
# Room tone
# --------------------------------------------------------------------------- #
def native_audio_command(clip: str, out: str, *, seconds: float, ffmpeg: str | None = None) -> list[str]:
    """The shot's own audio as 48 kHz stereo wav, padded or cut to ``seconds``."""
    total = _total(seconds)
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", clip, "-vn",
            "-af", f"{_FORMAT},apad,atrim=0:{total},asetpts=N/SR/TB", "-t", total, *_wav_out(out)]


def silence_command(out: str, seconds: float, ffmpeg: str | None = None) -> list[str]:
    total = _total(seconds)
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo", "-t", total, *_wav_out(out)]


def concat_audio_command(parts: Sequence[str], out: str, ffmpeg: str | None = None) -> list[str]:
    inputs: list[str] = []
    for part in parts:
        inputs += ["-i", part]
    streams = "".join(f"[{i}:a]" for i in range(len(parts)))
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", *inputs,
            "-filter_complex", f"{streams}concat=n={len(parts)}:v=0:a=1[a]", "-map", "[a]", *_wav_out(out)]


def room_tone_track(clips: Sequence[tuple[str | None, float]], out: str, work: str,
                    ffmpeg: str | None = None) -> str:
    """One wav of the whole video: each slot's native audio when it has some, else silence."""
    if not clips:
        raise AudioError("no slots for the room tone")
    ffmpeg = ffmpeg or ffmpeg_bin()
    parts = []
    for index, (clip, seconds) in enumerate(clips):
        part = os.path.join(work, f"room-{index + 1}.wav")
        if clip and has_audio_stream(clip, ffmpeg=ffmpeg):
            run(native_audio_command(clip, part, seconds=seconds, ffmpeg=ffmpeg))
        else:
            run(silence_command(part, seconds, ffmpeg=ffmpeg))
        parts.append(part)
    run(concat_audio_command(parts, out, ffmpeg=ffmpeg))
    return out


# --------------------------------------------------------------------------- #
# Mix
# --------------------------------------------------------------------------- #
def mix_command(*, out: str, total_s: float, vo: str | None, vo_delay_s: float = 0.0,
                sfx: Sequence[tuple[str, float]] = (), room: str | None = None, room_gain: float = 0.5,
                sfx_gain: float = 0.6, ffmpeg: str | None = None) -> list[str]:
    """Voice over a ducked bed of room tone and SFX, trimmed to ``total_s``, 48 kHz stereo wav."""
    total = _total(total_s)
    inputs: list[str] = []
    chains: list[str] = []
    bed: list[str] = []
    index = 0
    if vo:
        inputs += ["-i", vo]
        index += 1
    if room:
        inputs += ["-i", room]
        chains.append(f"[{index}:a]{_FORMAT},volume={float(room_gain):g},apad,atrim=0:{total}[room]")
        bed.append("[room]")
        index += 1
    for number, (path, start) in enumerate(sfx):
        inputs += ["-i", path]
        chains.append(f"[{index}:a]{_FORMAT},volume={float(sfx_gain):g},adelay=delays={_ms(start)}:all=1,"
                      f"apad,atrim=0:{total}[sfx{number}]")
        bed.append(f"[sfx{number}]")
        index += 1
    if bed:
        if len(bed) == 1:
            chains.append(f"{bed[0]}anull[bed]")
        else:
            chains.append(f"{''.join(bed)}amix=inputs={len(bed)}:duration=longest:normalize=0[bed]")
    if vo:
        voice = f"[0:a]{_FORMAT},adelay=delays={_ms(vo_delay_s)}:all=1,apad,atrim=0:{total}"
        if bed:
            chains.insert(0, f"{voice},asplit=2[vo][key]")
            chains.append(f"[bed][key]{DUCK}[duck]")
            chains.append(f"[vo][duck]amix=inputs=2:duration=longest:normalize=0,atrim=0:{total}[mix]")
        else:
            chains.insert(0, f"{voice}[mix]")
    elif bed:
        chains.append(f"[bed]atrim=0:{total}[mix]")
    else:
        inputs += ["-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo"]
        chains.append(f"[0:a]atrim=0:{total}[mix]")
    return [ffmpeg or ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", *inputs,
            "-filter_complex", ";".join(chains), "-map", "[mix]", "-t", total, *_wav_out(out)]


# --------------------------------------------------------------------------- #
# Mastering
# --------------------------------------------------------------------------- #
def _loudnorm(target: float, tp: float, lra: float) -> str:
    return f"loudnorm=I={float(target):g}:TP={float(tp):g}:LRA={float(lra):g}"


def parse_loudnorm_json(stderr: str) -> dict[str, str]:
    """The last ``{...}`` block loudnorm prints with ``print_format=json``."""
    start = (stderr or "").rfind("{")
    end = (stderr or "").rfind("}")
    if start < 0 or end < start:
        raise AudioError("loudnorm printed no measurement")
    try:
        data = json.loads(stderr[start:end + 1])
    except ValueError as exc:
        raise AudioError("loudnorm measurement is not JSON") from exc
    return {str(k): str(v) for k, v in data.items()}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def loudnorm_two_pass(src: str, out: str, *, target: float = TARGET_LUFS, tp: float = TRUE_PEAK,
                      lra: float = LRA, ffmpeg: str | None = None) -> dict[str, str]:
    """Measure, then normalise linearly to ``target`` LUFS / ``tp`` dBTP; 48 kHz wav. Returns pass-1 values.

    A silent input (integrated loudness -inf or below -70 LUFS) is copied, not normalised.
    """
    ffmpeg = ffmpeg or ffmpeg_bin()
    measure = [ffmpeg, "-hide_banner", "-nostats", "-i", src, "-vn",
               "-af", f"{_loudnorm(target, tp, lra)}:print_format=json", "-f", "null", "-"]
    measured = parse_loudnorm_json(run(measure).stderr)
    keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    values = {k: _finite(measured.get(k)) for k in keys}
    if values["input_i"] is None or values["input_i"] <= _SILENT_LUFS or any(v is None for v in values.values()):
        logger.info("very-time audio: silent mix, loudness normalisation skipped")
        run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vn", *_wav_out(out)])
        return measured
    chain = (f"{_loudnorm(target, tp, lra)}:measured_I={values['input_i']:g}:measured_TP={values['input_tp']:g}"
             f":measured_LRA={values['input_lra']:g}:measured_thresh={values['input_thresh']:g}"
             f":offset={values['target_offset']:g}:linear=true,aresample={SAMPLE_RATE}")
    run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-af", chain, *_wav_out(out)])
    return measured


def sfx_prompt(beat_sfx_template: str, slots: Mapping[str, str]) -> str:
    """Fill ``{slot}`` names in a beat's SFX template; unknown slots stay as written."""
    text = _SLOT.sub(lambda m: str(slots.get(m.group(1), m.group(0))), str(beat_sfx_template or ""))
    return " ".join(text.split())


__all__ = [
    "AudioError", "DUCK", "LRA", "SAMPLE_RATE", "TARGET_LUFS", "TRUE_PEAK", "concat_audio_command",
    "has_audio_stream", "loudnorm_two_pass", "mix_command", "native_audio_command", "parse_loudnorm_json",
    "room_tone_track", "sfx_prompt", "silence_command",
]
