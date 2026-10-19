"""Turn a finished capture into reel-pipeline job requests (``POST /jobs``).

The capture's MP4 becomes ``params.screen_recording_key``, so everything the
reel pipeline already does (captions, voice, avatar, watermark, auto-publish
via ``platforms``, the winner loop on published jobs) applies unchanged.

Ad modes:

* ``captions``  - ``captions_only`` layout: the capture with the script as
  timed on-screen captions. No AI provider, no voice.
* ``voiceover`` - ``captions_only`` plus a narration generated here with a free
  voice (edge-tts) and passed as ``voiceover_key``; the pipeline transcribes it
  for word-timed captions.
* ``avatar``    - ``pip`` layout: an AI avatar reads the script over the
  capture (the Ad Studio UGC path). Uses the caller's normal reel credits.

The script is built from what the capture actually found (page/listing title
and description); users edit it before submitting.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.domains.capture.models import KIND_APP_STORE, KIND_NATIVE_GAME, KIND_PLAY_STORE, KIND_WEB_GAME
from app.domains.capture.slideshow import description_lines

AD_MODES = ("captions", "voiceover", "avatar")
FREE_VOICES = ("en-US-AriaNeural-Female", "en-US-GuyNeural-Male", "tr-TR-EmelNeural-Female")
MAX_SCRIPT_CHARS = 1200


class AdRequestError(ValueError):
    pass


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _title(capture: Any) -> str:
    meta = capture.meta or {}
    listing = meta.get("listing") or {}
    page = meta.get("page") or {}
    title = str(listing.get("title") or page.get("site_name") or page.get("title") or "").strip()
    return title[:80] or _domain(capture.source_url) or "this"


def draft_script(capture: Any) -> dict[str, Any]:
    """Hook, body lines and CTA from the capture's real metadata."""
    meta = capture.meta or {}
    listing = meta.get("listing") or {}
    page = meta.get("page") or {}
    title = _title(capture)
    description = str(listing.get("description") or page.get("description") or "")
    lines = description_lines(description, limit=3, max_chars=120)
    kind = capture.source_kind
    if kind in (KIND_APP_STORE, KIND_PLAY_STORE):
        hook = lines.pop(0) if lines else f"Meet {title}."
        store = "Google Play" if kind == KIND_PLAY_STORE else "the App Store"
        cta = f"Get {title} on {store}."
    elif kind == KIND_NATIVE_GAME:
        hook = f"This is {title}. Watch a round."
        platform = str(page.get("platform") or "")
        store = {"ios": " on the App Store", "android": " on Google Play"}.get(platform, "")
        cta = f"Play {title}{store}."
    elif kind == KIND_WEB_GAME:  # legacy rows only; web game capture was removed
        hook = f"This is {title}. Watch a round."
        cta = f"Play {title} at {_domain(capture.source_url)}."
    else:
        hook = lines.pop(0) if lines else f"Take a look at {title}."
        cta = f"See more at {_domain(capture.source_url)}."
    script = "\n".join([hook, *lines, cta])[:MAX_SCRIPT_CHARS]
    return {"hook": hook, "lines": lines, "cta": cta, "script": script, "title": title}


def _target_seconds(output: dict[str, Any]) -> int:
    duration_ms = int(output.get("duration_ms") or 0)
    return max(10, min(60, round(duration_ms / 1000) or 30))


def build_job_request(
    capture: Any,
    output: dict[str, Any],
    *,
    mode: str,
    script: str,
    language: str = "en",
    avatar_id: str = "",
    voice_id: str = "",
    caption_style: str = "",
    voiceover_key: str = "",
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """The exact ``POST /jobs`` body for one capture output (one aspect)."""
    if mode not in AD_MODES:
        raise AdRequestError(f"unknown ad mode {mode!r}")
    key = str(output.get("key") or "")
    if not key:
        raise AdRequestError("this format has no finished video yet")
    script = (script or "").strip()[:MAX_SCRIPT_CHARS]
    if not script:
        raise AdRequestError("write a script (or keep the drafted one) before making ads")
    params: dict[str, Any] = {
        "video_subject": _title(capture),
        "video_script": script,
        "aspect": str(output.get("aspect") or "9:16"),
        "language": language if language in ("en", "tr") else "auto",
        "target_duration_s": _target_seconds(output),
        "platforms": list(platforms or []),
        "screen_recording_key": key,
        "layout": "pip" if mode == "avatar" else "captions_only",
    }
    body: dict[str, Any] = {"params": params, "variants": 1, "tos_disclosure": True}
    if mode == "avatar":
        if not avatar_id:
            raise AdRequestError("pick an avatar for avatar ads")
        params["avatar_id"] = avatar_id
        body["avatar_id"] = avatar_id
        if voice_id:
            body["voice_id"] = voice_id
    if mode == "voiceover":
        if not voiceover_key:
            raise AdRequestError("the narration could not be generated")
        body["voiceover_key"] = voiceover_key
    if caption_style:
        body["caption_style"] = caption_style
    return body


def synthesize_voiceover(script: str, voice_name: str, work_path: str) -> str:
    """Narrate ``script`` with a free edge-tts voice into ``work_path`` (mp3)."""
    if voice_name not in FREE_VOICES:
        raise AdRequestError("pick one of the free narration voices")
    try:
        from app.services import voice
    except Exception as exc:  # noqa: BLE001 - optional TTS stack missing
        raise AdRequestError("narration is unavailable on this server") from exc
    text = " ".join(line.strip() for line in script.splitlines() if line.strip())
    try:
        result = voice.tts(text, voice_name, 1.0, work_path)
    except Exception as exc:  # noqa: BLE001 - network/TTS failure
        raise AdRequestError("the narration voice service did not respond; try again") from exc
    if result is None:
        raise AdRequestError("the narration voice service did not respond; try again")
    return work_path


__all__ = ["AD_MODES", "AdRequestError", "FREE_VOICES", "build_job_request", "draft_script", "synthesize_voiceover"]
