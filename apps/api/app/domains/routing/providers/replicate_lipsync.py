"""sync lipsync-2 on Replicate (``sync/lipsync-2``): the payoff lip-sync when no MuseTalk is configured.

Input schema (read 2026-10-05): ``video`` (mp4), ``audio`` (wav), ``sync_mode``
(loop, bounce, cut_off, silence, remap), ``temperature`` 0-1, ``active_speaker``.
Licence: sync. hosted API, ``sync`` is ``commercial_api`` in license_class.
Async: :func:`submit` creates the prediction, :func:`poll` reads it and never raises.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.domains.gateway import replicate_run

MODEL = "sync/lipsync-2"
PROVIDER = "replicate-lipsync"


def is_enabled() -> bool:
    return replicate_run.is_enabled()


def build_input(video_url: str, audio_url: str) -> dict:
    if not video_url or not audio_url:
        raise ValueError("lip-sync needs a video and an audio URL")
    return {"video": video_url, "audio": audio_url, "sync_mode": "cut_off", "temperature": 0.3,
            "active_speaker": False}


def submit(video_url: str, audio_url: str, correlation_id: str = "", session: Any = None) -> dict:
    """Start the lip-sync; raises RuntimeError so the caller can fall back to the voice-over."""
    try:
        payload = replicate_run.submit(MODEL, build_input(video_url, audio_url), session=session)
    except Exception as exc:  # noqa: BLE001 - one error type for the caller's fallback
        raise RuntimeError(f"lip-sync did not start: {exc}") from exc
    run_id = str(payload.get("id") or "")
    if not run_id:
        raise RuntimeError("lip-sync did not start: no prediction id")
    return {"provider": PROVIDER, "run_id": run_id, "correlation_id": correlation_id,
            "get_url": str((payload.get("urls") or {}).get("get") or ""),
            "state": _state(str(payload.get("status") or "starting"))}


def _state(status: str) -> str:
    if status == "succeeded":
        return "completed"
    if status in ("failed", "canceled"):
        return "failed"
    return "running"


def poll(run: Mapping[str, Any], session: Any = None) -> tuple[str, str]:
    """``(state, result_url)``; state is running, completed or failed. Never raises."""
    url = str(run.get("get_url") or "")
    if not url and run.get("run_id"):
        url = f"https://api.replicate.com/v1/predictions/{run['run_id']}"
    if not url:
        return "failed", ""
    try:
        payload = replicate_run.get(url, session=session)
    except Exception:  # noqa: BLE001 - poll never raises
        return "failed", ""
    state = _state(str(payload.get("status") or ""))
    if state != "completed":
        return state, ""
    output = payload.get("output")
    result = output if isinstance(output, str) else (output[0] if isinstance(output, list) and output else "")
    return ("completed", str(result)) if result else ("failed", "")


__all__ = ["MODEL", "PROVIDER", "build_input", "is_enabled", "poll", "submit"]
