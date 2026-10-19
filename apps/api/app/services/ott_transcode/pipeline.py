"""Encode + package one OTT source into a CMAF ladder (shared by box 1, the Mac node and burst).

Probe -> one MP4 per rung (fixed 2 s GOP) + one AAC rendition -> shaka-packager
(HLS + DASH from the same segments; tier-1 HLS AES-128 when protected) ->
trick-play sprite -> a file list the caller uploads. CPU seconds are measured
from the child processes (``RUSAGE_CHILDREN``).
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from app.services.ott_package import packager, sprites
from app.services.ott_package.tracks import Track

from . import ladder


class PipelineError(RuntimeError):
    pass


@dataclass
class Result:
    out_dir: str
    files: list[str] = field(default_factory=list)
    cpu_seconds: float = 0.0
    rungs: list[str] = field(default_factory=list)
    source: ladder.Source | None = None


def probe(ffprobe: str, path: str) -> ladder.Source:
    done = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                           "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", path],
                          capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise PipelineError("the source could not be read")
    data = json.loads(done.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    seconds = float((data.get("format") or {}).get("duration") or 0)
    if video is None:
        return ladder.Source(0, 0, 0.0, seconds, audio)
    num, _, den = str(video.get("r_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return ladder.Source(int(video["width"]), int(video["height"]), fps, seconds, audio)


def _run(cmd: Sequence[str], timeout: float) -> None:
    done = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        raise PipelineError((done.stderr or "a step failed").strip()[-400:])


def _cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def run(src: str, work: str, *, ffmpeg: str, packager_bin: str, encoder: str = ladder.ENCODER_X264,
        protection: packager.Protection | None = None, tracks: Sequence[Track] = (),
        timeout_s: float = 6 * 3600) -> Result:
    started = _cpu()
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in os.path.basename(ffmpeg) else "ffprobe"
    source = probe(ffprobe, src)
    enc_dir, out_dir = Path(work, "enc"), Path(work, "out")
    enc_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    video: list[tuple[str, str]] = []
    rungs: list[str] = []
    if source.width:
        for rung, width, height in ladder.plan(source):
            path = str(enc_dir / f"{rung.name}.mp4")
            _run(ladder.rung_command(ffmpeg, src, path, source, rung, width, height, encoder=encoder), timeout_s)
            video.append((rung.name, path))
            rungs.append(rung.name)
    audio = None
    if source.has_audio:
        audio = str(enc_dir / "audio.m4a")
        _run(ladder.audio_command(ffmpeg, src, audio), timeout_s)
    if not video and not audio:
        raise PipelineError("the source has no video or audio")
    _run(packager.command(packager_bin, video=video, audio=audio, out_dir=str(out_dir), tracks=tracks), timeout_s)
    if protection is not None:
        packager.protect_hls(str(out_dir), protection)
    if source.width:
        sheet = str(out_dir / "thumbs.jpg")
        _run(sprites.sprite_command(ffmpeg, src, sheet, source.seconds, vertical=source.vertical), timeout_s)
        (out_dir / "thumbs.vtt").write_text(sprites.sprite_vtt(source.seconds, "thumbs.jpg",
                                                               vertical=source.vertical), encoding="utf-8")
    files = sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file())
    return Result(out_dir=str(out_dir), files=files, cpu_seconds=round(_cpu() - started, 2), rungs=rungs,
                  source=source)


CONTENT_TYPES = {".m3u8": "application/vnd.apple.mpegurl", ".mpd": "application/dash+xml", ".m4s": "video/iso.segment",
                 ".mp4": "video/mp4", ".vtt": "text/vtt", ".jpg": "image/jpeg"}


def content_type(name: str) -> str:
    return CONTENT_TYPES.get(os.path.splitext(name)[1], "application/octet-stream")


__all__ = ["CONTENT_TYPES", "PipelineError", "Result", "content_type", "probe", "run"]
