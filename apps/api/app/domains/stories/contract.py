"""THE shared draft/job contract for the reddit-story pipeline (REDDIT-owned).

The series RUNNER imports from **this module only** (read-only) to drive
reddit-story fan-out, so the two builders never edit the same file. It centralizes:

* :class:`StoryDraftResult` — the ``{url, thread, script, reel_draft}`` product.
* :func:`build_story_reel_draft` — compile the ``minecraft-reddit-split`` template
  into a submittable ``JobCreateRequest``-shaped draft, pinning the looping
  minecraft-parkour background (no gameplay clip required).
* :func:`story_params` — the single source of truth for the
  ``JobCreateRequest → ReelForgeParams`` fold, so the RUNNER never duplicates the
  layout / caption / background / voice / platforms mapping.

``platforms`` defaults to ``()`` so the render chain SKIPS ``stage_upload`` — the
RUNNER schedules publishing separately through the scheduling policy + beat.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.stories.parse import RedditThread
from app.domains.stories.script import build_story_script
from app.domains.templates.service import instantiate_draft
from app.services.reelforge import ReelForgeParams

__all__ = [
    "RedditThread",
    "StoryDraftResult",
    "MINECRAFT_SLUG",
    "DEFAULT_MAX_WORDS",
    "build_story_script",
    "build_story_reel_draft",
    "story_params",
]

MINECRAFT_SLUG = "minecraft-reddit-split"
DEFAULT_MAX_WORDS = 130

# The reddit-story format always narrates over the first-party looping minecraft
# parkour loop. The compiler's availability fallback may downgrade an unuploaded
# bundled loop to a stock parkour clip; we pin the canonical id here so the draft
# and the folded params agree on the flagship background (it auto-upgrades to the
# first-party asset once uploaded).
_BACKGROUND_ID = "voxel-parkour"
_LAYOUT = "split"
_CAPTION_STYLE = "karaoke_yellow"
_DEFAULT_SUBJECT = "Reddit Story"


@dataclass
class StoryDraftResult:
    """The stateless product of ``thread_to_reel`` — never persisted here."""

    url: str
    thread: RedditThread
    script: str
    reel_draft: dict


def build_story_reel_draft(
    script: str,
    *,
    subject: str,
    aspect: str = "9:16",
    voice_id: str | None = None,
    template_slug: str = MINECRAFT_SLUG,
) -> dict:
    """Compile ``script`` into a submittable reel draft bound to the split preset.

    Delegates to the real template compiler (``instantiate_draft``) so the draft is
    validated against ``JobCreateRequest`` before any credit spend, then pins the
    minecraft-parkour background and folds in the aspect + optional narration voice.
    Raises :class:`~app.domains.templates.validation.TemplateError` on an invalid
    story (e.g. empty script).
    """
    compiled = instantiate_draft(template_slug, {"story": script, "subject": subject})
    draft = dict(compiled["reel_draft"])
    draft["background_id"] = _BACKGROUND_ID
    if aspect:
        draft["aspect"] = aspect
    if voice_id:
        draft["voice_name"] = f"elevenlabs:{voice_id}"
    return draft


def story_params(
    script: str,
    *,
    subject: str,
    aspect: str = "9:16",
    voice_id: str | None = None,
    platforms: tuple[str, ...] = (),
) -> ReelForgeParams:
    """Fold a reddit-story draft into the immutable render DTO (single authority).

    ``platforms`` defaults to ``()`` so the render chain skips ``stage_upload`` and
    the RUNNER schedules publishing separately with pacing.
    """
    voice_name = f"elevenlabs:{voice_id}" if voice_id else ""
    return ReelForgeParams(
        video_subject=(subject or _DEFAULT_SUBJECT),
        video_script=script,
        layout=_LAYOUT,
        caption_style=_CAPTION_STYLE,
        background_id=_BACKGROUND_ID,
        aspect=aspect,
        voice_name=voice_name,
        platforms=tuple(platforms),
    )
