"""The ``POST /jobs`` request that turns a reel idea into a Menivor reel.

Same shape the Megaphone dogfood pipeline renders every week: captions-only
layout over a looping background, a voiced script, karaoke captions, 9:16.
The client sends it with the user's credential, so the normal reel price,
credit checks and pilot gates apply. ``Idempotency-Key`` is per idea, so a
double tap never makes two reels.
"""

from __future__ import annotations

#: Bundled, rights-clean loops (see ``content.background_library``), rotated per idea.
BACKGROUNDS = ("block-runner", "marble-loop", "sand-slice-2", "synthwave-road", "marble-loop-2")
VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # mapped to a free voice when premium voice is off
CAPTION_STYLE = "karaoke_yellow"
TARGET_SECONDS = 30


def reel_job(idea_id: str, hook: str, script: str, language: str = "en", position: int = 0) -> dict:
    """``{"body": <JobCreateRequest>, "idempotency_key": str}`` for one reel idea."""
    params = {
        "video_subject": (hook or "")[:200],
        "video_script": script or hook or "",
        "voice_name": f"elevenlabs:{VOICE_ID}",
        "avatar_id": "",
        "avatar_provider": "heygen",
        "caption_style": CAPTION_STYLE,
        "layout": "captions_only",
        "aspect": "9:16",
        "language": (language or "en")[:8],
        "target_duration_s": TARGET_SECONDS,
        "platforms": [],
        "screen_recording_key": "",
        "background_id": BACKGROUNDS[position % len(BACKGROUNDS)],
    }
    return {
        "body": {"params": params, "voice_id": VOICE_ID, "caption_style": CAPTION_STYLE, "variants": 1},
        "idempotency_key": f"month-{idea_id}",
    }


__all__ = ["BACKGROUNDS", "reel_job"]
