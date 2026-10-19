"""Dubbed audio tracks (MV16): translated cues spoken with edge-tts, placed on the timeline, packaged as HLS.

* Each cue is spoken in the target language (edge-tts voices, the same free
  voices the reels use) and placed at the cue's start time over silence; a
  line longer than its slot is sped up to fit (at most 1.5x) so the track
  stays in sync with the picture.
* The track is encoded to AAC and cut into 2 s fMP4 segments as its own
  media playlist; for protected titles the segments are AES-128 encrypted
  with the title's key (the same tier-1 scheme as the rest of the title).
* The master playlist gains an ``EXT-X-MEDIA:TYPE=AUDIO`` rendition in the
  existing ``audio`` group, so every player offers the language.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from .subtitles import Cue

GROUP = "audio"
MAX_SPEEDUP = 1.5
SEGMENT_S = 2
EDGE_VOICES = {
    "en": "en-US-AriaNeural", "es": "es-ES-ElviraNeural", "fr": "fr-FR-DeniseNeural", "de": "de-DE-KatjaNeural",
    "pt": "pt-BR-FranciscaNeural", "it": "it-IT-ElsaNeural", "tr": "tr-TR-EmelNeural", "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural", "zh": "zh-CN-XiaoxiaoNeural", "hi": "hi-IN-SwaraNeural", "ar": "ar-SA-ZariyahNeural",
    "ru": "ru-RU-SvetlanaNeural", "nl": "nl-NL-ColetteNeural", "pl": "pl-PL-ZofiaNeural",
    "id": "id-ID-GadisNeural",
}

Speak = Callable[[str, str, str], None]


class DubError(Exception):
    pass


def voice_for(language: str) -> str:
    voice = EDGE_VOICES.get(language)
    if voice is None:
        raise DubError(f"no voice for {language}")
    return voice


def edge_speak(text: str, voice: str, out_path: str) -> None:
    from app.services import voice as voice_service

    if voice_service.tts(text, voice, 1.0, out_path) is None or not os.path.exists(out_path):
        raise DubError("speech could not be made")


def _run(cmd: Sequence[str], timeout: float = 600) -> str:
    done = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)  # noqa: S603 - fixed argv
    if done.returncode != 0:
        raise DubError(done.stderr.strip()[-400:] or "ffmpeg failed")
    return done.stdout


def duration(ffprobe: str, path: str) -> float:
    out = _run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], timeout=60)
    return float(out.strip() or 0)


def mix_command(ffmpeg: str, parts: Sequence[tuple[str, float, float]], total_s: float, out_path: str) -> list[str]:
    """``parts`` is ``[(clip path, start seconds, tempo)]``: each clip delayed to its start over silence."""
    args = [ffmpeg, "-y", "-f", "lavfi", "-t", f"{total_s:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    filters = []
    for n, (path, start, tempo) in enumerate(parts, start=1):
        args += ["-i", path]
        delay = int(round(start * 1000))
        filters.append(f"[{n}:a]aresample=48000,atempo={tempo:.3f},adelay={delay}|{delay}[c{n}]")
    inputs = "".join(f"[c{n}]" for n in range(1, len(parts) + 1))
    filters.append(f"[0:a]{inputs}amix=inputs={len(parts) + 1}:duration=first:normalize=0[out]")
    return [*args, "-filter_complex", ";".join(filters), "-map", "[out]", "-c:a", "aac", "-b:a", "128k",
            "-t", f"{total_s:.3f}", out_path]


def hls_command(ffmpeg: str, track: str, out_dir: str, name: str) -> list[str]:
    seg_dir = f"{out_dir}/{name}"
    return [ffmpeg, "-y", "-i", track, "-c:a", "copy", "-f", "hls", "-hls_time", str(SEGMENT_S),
            "-hls_playlist_type", "vod", "-hls_segment_type", "fmp4",
            "-hls_fmp4_init_filename", "init.mp4", "-hls_segment_filename", f"{seg_dir}/%d.m4s",
            f"{seg_dir}/index.m3u8"]


def build(cues: Sequence[Cue], language: str, *, total_s: float, work: str, ffmpeg: str, ffprobe: str,
          speak: Speak | None = None) -> str:
    """Make the dubbed AAC track for ``cues``; returns its path."""
    if not cues:
        raise DubError("nothing to dub")
    voice = voice_for(language)
    say = speak or edge_speak
    root = Path(work)
    root.mkdir(parents=True, exist_ok=True)
    parts: list[tuple[str, float, float]] = []
    for n, cue in enumerate(cues):
        clip = str(root / f"line-{n:04d}.mp3")
        say(cue.text, voice, clip)
        slot = max(0.3, cue.end - cue.start)
        spoken = duration(ffprobe, clip)
        tempo = min(MAX_SPEEDUP, max(1.0, spoken / slot))
        parts.append((clip, cue.start, tempo))
    track = str(root / f"dub-{language}.m4a")
    _run(mix_command(ffmpeg, parts, total_s, track))
    return track


def package(track: str, out_dir: str, *, language: str, ffmpeg: str, protection=None) -> str:
    """Cut the track into an HLS media playlist at ``out_dir/a_dub_<lang>.m3u8``; returns that file name."""
    from app.services.ott_package import packager

    name = f"a_dub_{language}"
    Path(out_dir, name).mkdir(parents=True, exist_ok=True)
    _run(hls_command(ffmpeg, track, out_dir, name))
    source = Path(out_dir, name, "index.m3u8")
    lines = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            line = f"{name}/{line}"
        elif line.startswith("#EXT-X-MAP:"):
            line = line.replace('URI="', f'URI="{name}/')
        lines.append(line)
    Path(out_dir, f"{name}.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")
    source.unlink()
    if protection is not None:
        packager.protect_hls(out_dir, protection)
    return f"{name}.m3u8"


__all__ = ["DubError", "EDGE_VOICES", "GROUP", "build", "duration", "edge_speak", "hls_command", "mix_command",
           "package", "voice_for"]
