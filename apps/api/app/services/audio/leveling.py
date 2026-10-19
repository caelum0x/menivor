"""Music bed levelling: keep background music well under the narration (M2.4).

The compose audio graph ducks music with ``sidechaincompress`` while the voice
plays, but that only removes a few dB, and library or AI-generated tracks are
often mastered louder than a TTS voice. This module measures both files with
FFmpeg's EBU R128 meter (``ebur128``) and writes a gain-adjusted copy of the
music (the "bed") whose integrated loudness sits ``MUSIC_UNDER_VOICE_LU`` below
the voice. Compose then ducks the bed further under speech, so music ends up at
least ``MIN_SPEECH_MARGIN_DB`` below the voice while words are spoken.

``amix`` and the final ``loudnorm`` in compose scale voice and music together,
so the margin set here survives the mix.

Never raises: if the music cannot be measured or rendered the original path is
returned and compose keeps its current behaviour.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
from typing import Optional

try:  # loguru ships with the API; keep the module import-safe without it.
    from loguru import logger
except Exception:  # pragma: no cover - fallback only when loguru is absent.
    import logging

    logger = logging.getLogger(__name__)

__all__ = [
    "FALLBACK_VOICE_LUFS",
    "MIN_SPEECH_MARGIN_DB",
    "MUSIC_UNDER_VOICE_LU",
    "bed_gain_db",
    "measure_integrated_lufs",
    "parse_ebur128_integrated",
    "prepare_music_bed",
]

#: Integrated loudness of the bed below the voice, before sidechain ducking.
MUSIC_UNDER_VOICE_LU: float = 16.0
#: The acceptance floor: music at least this far under the voice during speech.
MIN_SPEECH_MARGIN_DB: float = 12.0
#: Assumed voice loudness when the narration cannot be measured (typical TTS).
FALLBACK_VOICE_LUFS: float = -18.0
#: Never boost a quiet track by more than this (avoids lifting its noise floor).
MAX_BOOST_DB: float = 6.0
#: Lowest gain applied (a near-silent bed is pointless below this).
MIN_GAIN_DB: float = -60.0
_MEASURE_TIMEOUT_S = 180
_RENDER_TIMEOUT_S = 300

_INTEGRATED_RE = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")


def _ffmpeg() -> str:
    try:
        from app.utils import utils

        return utils.get_ffmpeg_binary() or "ffmpeg"
    except Exception:  # noqa: BLE001 - config may be incomplete in tools/tests
        return "ffmpeg"


def parse_ebur128_integrated(stderr: str) -> Optional[float]:
    """The summary integrated loudness (LUFS) from ``ebur128`` stderr output.

    The filter prints a running ``I:`` value per frame and a final summary; the
    last match is the whole-file value. ``-70`` or lower means silence.
    """
    matches = _INTEGRATED_RE.findall(stderr or "")
    if not matches:
        return None
    try:
        value = float(matches[-1])
    except ValueError:
        return None
    if not math.isfinite(value) or value <= -70.0:
        return None
    return value


def measure_integrated_lufs(
    path: str,
    *,
    start_s: Optional[float] = None,
    duration_s: Optional[float] = None,
    ffmpeg: Optional[str] = None,
) -> Optional[float]:
    """Integrated loudness of ``path`` (optionally a time window), or ``None``."""
    if not path or not os.path.isfile(path):
        return None
    command = [ffmpeg or _ffmpeg(), "-hide_banner", "-nostats"]
    if start_s is not None:
        command += ["-ss", f"{max(0.0, start_s):.3f}"]
    if duration_s is not None:
        command += ["-t", f"{max(0.01, duration_s):.3f}"]
    command += ["-i", path, "-vn", "-af", "ebur128", "-f", "null", "-"]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_MEASURE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug(f"ebur128 measure failed: path={path}, error={exc}")
        return None
    if completed.returncode != 0:
        return None
    return parse_ebur128_integrated(completed.stderr)


def bed_gain_db(
    voice_lufs: Optional[float],
    music_lufs: float,
    *,
    under_lu: float = MUSIC_UNDER_VOICE_LU,
) -> float:
    """Gain (dB) that puts the music ``under_lu`` below the voice.

    An unmeasurable voice uses :data:`FALLBACK_VOICE_LUFS`. The result is
    clamped to ``[MIN_GAIN_DB, MAX_BOOST_DB]``.
    """
    voice = FALLBACK_VOICE_LUFS if voice_lufs is None else float(voice_lufs)
    target = voice - float(under_lu)
    gain = target - float(music_lufs)
    return round(max(MIN_GAIN_DB, min(MAX_BOOST_DB, gain)), 2)


def prepare_music_bed(
    music_path: Optional[str],
    voice_path: Optional[str],
    out_path: str,
    *,
    under_lu: float = MUSIC_UNDER_VOICE_LU,
    ffmpeg: Optional[str] = None,
) -> Optional[str]:
    """Write a levelled copy of ``music_path`` to ``out_path`` and return it.

    Returns ``music_path`` unchanged (never raises) when there is no music, the
    music cannot be measured, or FFmpeg fails. ``out_path`` should end in
    ``.wav``; the bed is 16-bit PCM so compose does not decode a lossy copy of
    a lossy copy.
    """
    if not music_path or not os.path.isfile(music_path):
        return music_path
    binary = ffmpeg or _ffmpeg()
    music_lufs = measure_integrated_lufs(music_path, ffmpeg=binary)
    if music_lufs is None:
        logger.warning(f"music bed: could not measure {os.path.basename(music_path)}; mixing as-is")
        return music_path
    voice_lufs = measure_integrated_lufs(voice_path, ffmpeg=binary) if voice_path else None
    gain = bed_gain_db(voice_lufs, music_lufs, under_lu=under_lu)
    command = [
        binary,
        "-hide_banner",
        "-nostats",
        "-y",
        "-i",
        music_path,
        "-vn",
        "-af",
        f"volume={gain:.2f}dB",
        "-c:a",
        "pcm_s16le",
        out_path,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_RENDER_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"music bed: render failed ({exc}); mixing as-is")
        return music_path
    if completed.returncode != 0 or not os.path.isfile(out_path):
        logger.warning("music bed: ffmpeg returned an error; mixing as-is")
        return music_path
    logger.info(
        f"music bed: voice={voice_lufs if voice_lufs is not None else 'n/a'} LUFS, "
        f"music={music_lufs} LUFS, gain={gain} dB"
    )
    return out_path
