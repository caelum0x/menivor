"""Encode commands for the OTT ladder (MV2). Box 1 and burst use libx264; the Mac uses VideoToolbox.

Each rung is encoded to its own MP4 with a fixed 2 s GOP (``-g``, ``-keyint_min``,
``-sc_threshold 0`` for x264, forced keyframes for VideoToolbox), so the
packager can cut aligned CMAF segments. The ladder "height" is the short side
for vertical video (a 9:16 1080p rung is 1080 wide), so both orientations use
the same rung names.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.ott_package.ladder_profiles import AUDIO_KBPS, GOP_SECONDS, Rung, rungs_for

ENCODER_X264 = "libx264"
ENCODER_VT = "h264_videotoolbox"


@dataclass(frozen=True)
class Source:
    width: int
    height: int
    fps: float
    seconds: float
    has_audio: bool = True

    @property
    def short_side(self) -> int:
        return min(self.width, self.height)

    @property
    def vertical(self) -> bool:
        return self.height > self.width


def _size(source: Source, rung: Rung) -> tuple[int, int]:
    short = rung.height
    long = round(max(source.width, source.height) * short / max(source.short_side, 1))
    long -= long % 2
    return (short, long) if source.vertical else (long, short)


def plan(source: Source) -> list[tuple[Rung, int, int]]:
    return [(rung, *_size(source, rung)) for rung in rungs_for(source.short_side)]


def rung_command(ffmpeg: str, src: str, out: str, source: Source, rung: Rung, width: int, height: int, *,
                 encoder: str = ENCODER_X264) -> list[str]:
    fps = source.fps if 0 < source.fps <= 60 else 30.0
    gop = max(1, round(fps * GOP_SECONDS))
    common = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-map", "0:v:0", "-an",
              "-vf", f"scale={width}:{height}:flags=lanczos,setsar=1,format=yuv420p", "-r", f"{fps:g}"]
    rate = ["-b:v", f"{rung.video_kbps}k", "-maxrate", f"{rung.max_kbps}k", "-bufsize", f"{rung.max_kbps * 2}k"]
    if encoder == ENCODER_VT:
        codec = ["-c:v", ENCODER_VT, "-profile:v", rung.profile, "-g", str(gop),
                 "-force_key_frames", f"expr:gte(t,n_forced*{GOP_SECONDS})", "-allow_sw", "1"]
    else:
        codec = ["-c:v", ENCODER_X264, "-preset", "medium", "-profile:v", rung.profile, "-g", str(gop),
                 "-keyint_min", str(gop), "-sc_threshold", "0", "-x264-params", "open-gop=0"]
    return [*common, *codec, *rate, "-movflags", "+faststart", out]


def audio_command(ffmpeg: str, src: str, out: str) -> list[str]:
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-map", "0:a:0", "-vn", "-c:a", "aac",
            "-b:a", f"{AUDIO_KBPS}k", "-ac", "2", "-ar", "48000", out]


__all__ = ["ENCODER_VT", "ENCODER_X264", "Source", "audio_command", "plan", "rung_command"]
