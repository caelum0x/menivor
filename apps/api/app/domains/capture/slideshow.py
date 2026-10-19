"""Store-listing slideshow: icon + screenshots + description -> promo video.

Planning is pure (:func:`plan_slides`); rendering reuses the Ad Studio FFmpeg
renderer (:func:`app.domains.adstudio.render.render_ad`), so each slide gets
the same blurred-backdrop framing, camera motion and caption cards. Every
caption is taken from the real listing (title, description sentences, rating
as published); nothing is invented.
"""

from __future__ import annotations

import re
from typing import Any

from app.domains.adstudio.cards import Card
from app.domains.adstudio.variants import MOTIONS, Segment

MAX_SLIDES = 8
INTRO_SECONDS = 3.0
SLIDE_SECONDS = 3.2
CTA_SECONDS = 3.0
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_BULLET = re.compile(r"^[\s\-•*●–]+")


def description_lines(description: str, limit: int = 6, max_chars: int = 110) -> list[str]:
    """Short, standalone caption lines from a store description."""
    lines: list[str] = []
    for raw in _SENTENCE.split(description or ""):
        text = _BULLET.sub("", raw).strip()
        if len(text) < 12 or text.isupper() and len(text) < 40:
            continue
        if len(text) > max_chars:
            cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:")
            text = f"{cut}..."
        if text.lower() in {line.lower() for line in lines}:
            continue
        lines.append(text)
        if len(lines) >= limit:
            break
    return lines


def store_label(store: str) -> str:
    return "On Google Play" if store == "play_store" else "On the App Store"


def plan_slides(listing: dict[str, Any], has_icon: bool, screenshot_count: int) -> list[Segment]:
    """Segments over ``[icon?] + screenshots`` (image indexes into that list)."""
    title = str(listing.get("title") or "").strip() or "This app"
    offset = 1 if has_icon else 0
    total_images = offset + screenshot_count
    if total_images == 0:
        return []
    segments: list[Segment] = [
        Segment(
            image_index=0,
            seconds=INTRO_SECONDS,
            motion="zoom_in",
            card=Card(text=title, style="hook", subtext=str(listing.get("developer") or "")[:80]),
        )
    ]
    lines = description_lines(str(listing.get("description") or ""), limit=max(1, min(MAX_SLIDES - 2, screenshot_count or 3)))
    shot_indexes = [offset + i for i in range(screenshot_count)] or [0]
    for i, line in enumerate(lines):
        segments.append(
            Segment(
                image_index=shot_indexes[i % len(shot_indexes)],
                seconds=SLIDE_SECONDS,
                motion=MOTIONS[(i + 1) % len(MOTIONS)],
                card=Card(text=line, style="body"),
            )
        )
    # Remaining screenshots without a matching sentence still get shown.
    for j in range(len(lines), min(screenshot_count, MAX_SLIDES - 2)):
        segments.append(Segment(image_index=shot_indexes[j], seconds=2.4, motion=MOTIONS[j % len(MOTIONS)]))
    rating = listing.get("rating")
    if isinstance(rating, (int, float)) and rating >= 4.0:
        count = listing.get("rating_count")
        sub = f"{int(count):,} ratings" if isinstance(count, int) and count > 0 else ""
        segments.append(
            Segment(
                image_index=shot_indexes[-1],
                seconds=2.6,
                motion="zoom_out",
                card=Card(text=f"Rated {float(rating):.1f} out of 5", style="price", subtext=sub),
            )
        )
    segments.append(
        Segment(
            image_index=0,
            seconds=CTA_SECONDS,
            motion="zoom_out",
            card=Card(text=f"Get {title}"[:80], style="cta", subtext=store_label(str(listing.get("store") or ""))),
        )
    )
    return segments


__all__ = ["description_lines", "plan_slides", "store_label"]
