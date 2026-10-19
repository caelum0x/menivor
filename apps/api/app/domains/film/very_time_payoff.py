"""Very ___ Time payoff shot: who speaks the line.

Three modes for the deadpan beat (``PAYOFF_MODES``):

* ``native``: the video model speaks the line itself (the shot brief asks for it);
  :func:`speech_present` checks the returned shot really carries speech, and when
  it does not the caller falls back to ``lipsync``;
* ``lipsync``: the payoff frame plus the chosen voice take go through the open
  MuseTalk lip-sync (MIT) via the existing routing adapter
  (``routing.providers._lipsync``), driven by :func:`submit_lipsync` and
  :func:`poll_lipsync`; it needs ``MUSETALK_API_KEY`` and ``MUSETALK_BASE_URL``
  (the self-hosted endpoint, e.g. RunPod serverless);
* ``voiceover``: the shot stays as it is and the narrated take plays over it
  (the always-available last fallback).

Submitting raises a plain ``RuntimeError`` (so the caller falls back); polling
never raises: a provider error is reported as ``failed``.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Mapping

from loguru import logger

PAYOFF_MODES = ("native", "lipsync", "voiceover")
PROVIDER = "musetalk"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"

_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


# --------------------------------------------------------------------------- #
# Native speech check
# --------------------------------------------------------------------------- #
def _audio_seconds_and_silence(clip_path: str, ffmpeg: str, threshold_db: float) -> tuple[float, float]:
    """(audio duration, total silent seconds) from one ``silencedetect`` pass."""
    done = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", clip_path, "-vn",
                           "-af", f"silencedetect=noise={threshold_db:g}dB:d=0.2", "-f", "null", "-"],
                          capture_output=True, text=True, timeout=180, check=False)
    text = done.stderr or ""
    match = _DURATION.search(text)
    duration = (int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))) if match else 0.0
    starts = [float(v) for v in _SILENCE_START.findall(text)]
    ends = [float(v) for v in _SILENCE_END.findall(text)]
    silent = 0.0
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else duration
        silent += max(0.0, end - max(0.0, start))
    return duration, silent


def speech_present(clip_path: str, *, min_lufs: float = -40.0, min_seconds: float = 0.8,
                   ffmpeg: str | None = None) -> bool:
    """True when the shot has an audio stream, loud enough, with ``min_seconds`` of sound."""
    from app.services.audio.leveling import measure_integrated_lufs

    from .very_time_audio import ffmpeg_bin, has_audio_stream

    ffmpeg = ffmpeg or ffmpeg_bin()
    if not has_audio_stream(clip_path, ffmpeg=ffmpeg):
        return False
    lufs = measure_integrated_lufs(clip_path, ffmpeg=ffmpeg)
    if lufs is None or lufs < float(min_lufs):
        return False
    try:
        duration, silent = _audio_seconds_and_silence(clip_path, ffmpeg, -45.0)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"very-time payoff: silence check failed: {exc}")
        return False
    return duration - silent >= float(min_seconds)


# --------------------------------------------------------------------------- #
# MuseTalk lip-sync (open, MIT) through the routing adapter
# --------------------------------------------------------------------------- #
def lipsync_configured() -> bool:
    """MuseTalk is usable: an API key and an explicit base URL are set."""
    from app.domains.routing.providers._lipsync import base_url_env

    return bool(os.getenv("MUSETALK_API_KEY", "").strip() and os.getenv(base_url_env(PROVIDER), "").strip())


def _adapter(adapter: Any = None) -> Any:
    if adapter is not None:
        return adapter
    from app.domains.routing.providers._lipsync import build_lipsync_adapter

    return build_lipsync_adapter(PROVIDER)


def _state(raw: str) -> str:
    from app.domains.routing.base import RUN_CANCELED, RUN_COMPLETED, RUN_FAILED

    if raw == RUN_COMPLETED:
        return STATE_COMPLETED
    if raw in (RUN_FAILED, RUN_CANCELED):
        return STATE_FAILED
    return STATE_RUNNING


def submit_lipsync(*, image_url: str, audio_url: str, correlation_id: str, adapter: Any = None) -> dict[str, str]:
    """Start a lip-sync run; ``RuntimeError`` when it cannot start (the caller falls back)."""
    if not image_url or not audio_url:
        raise RuntimeError("lip-sync needs the payoff frame and the voice take")
    if adapter is None and not lipsync_configured():
        raise RuntimeError("lip-sync is not configured")
    try:
        run = _adapter(adapter).submit({"image_url": image_url, "audio_url": audio_url}, {}, correlation_id)
    except Exception as exc:  # noqa: BLE001 - ProviderError or transport failure: fall back
        raise RuntimeError(f"lip-sync did not start: {exc}") from exc
    return {"provider": PROVIDER, "run_id": str(run.run_id), "state": _state(run.state)}


def poll_lipsync(run: Mapping[str, Any], adapter: Any = None) -> tuple[str, str]:
    """(``running`` | ``completed`` | ``failed``, result url). Never raises."""
    from app.domains.routing.base import ProviderRun

    run_id = str((run or {}).get("run_id") or "")
    if not run_id:
        return STATE_FAILED, ""
    try:
        current = _adapter(adapter).poll(ProviderRun(provider_key=PROVIDER, run_id=run_id))
    except Exception as exc:  # noqa: BLE001 - a poll failure ends the lip-sync, not the video
        logger.warning(f"very-time payoff: lip-sync poll failed: {exc}")
        return STATE_FAILED, ""
    state = _state(current.state)
    if state == STATE_COMPLETED and not current.result_ref:
        return STATE_FAILED, ""
    return state, str(current.result_ref or "") if state == STATE_COMPLETED else ""


__all__ = ["PAYOFF_MODES", "PROVIDER", "STATE_COMPLETED", "STATE_FAILED", "STATE_RUNNING", "lipsync_configured",
           "poll_lipsync", "speech_present", "submit_lipsync"]
