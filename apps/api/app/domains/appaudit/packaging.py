"""The 5-point App Store packaging checklist (icon, screenshots, title/subtitle,
promo text, freshness), scored from public listing data only.

Mirrors ``~/products/gtm/APP-STORE-PACKAGING-RULES-2026-10-11.md``. Every
check reports ``pass``/``warn``/``fail`` plus a one-line, honest reason: where
the public data cannot answer the real question (does the icon read at
60x60pt? do the screenshots tell a story?) the check says so plainly instead
of inventing a verdict.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Status = Literal["pass", "warn", "fail"]

_STATUS_POINTS: dict[Status, int] = {"pass": 20, "warn": 10, "fail": 0}
FRESH_DAYS = 90
STALE_DAYS = 180
ICON_THUMBNAIL_PX = 60


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    status: Status
    why: str
    heuristic: bool = False


def _score(checks: list[Check]) -> int:
    if not checks:
        return 0
    return round(sum(_STATUS_POINTS[c.status] for c in checks) / (len(checks) * 20) * 100)


# ---------------------------------------------------------------------------
# 1. Icon readability at thumbnail size (heuristic, from pixels if available)
# ---------------------------------------------------------------------------
def analyze_icon_bytes(data: bytes, size_px: int = ICON_THUMBNAIL_PX) -> Check:
    """Downscale the icon to ``size_px`` and score contrast/detail.

    This is a pixel heuristic, not a judgment of "good design": a flat,
    near-single-color icon at thumbnail size tends to disappear in a dense
    search results grid, so low variance is flagged as a warning. Never a
    ``fail`` on its own — image statistics cannot prove an icon will not
    read well, only that it is worth a human look.
    """
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            img.load()
            thumb = img.convert("L").resize((size_px, size_px))
            pixels = list(thumb.getdata())
    except Exception:  # noqa: BLE001 - any decode failure degrades to "unknown"
        return Check(
            "icon", "Icon readability at 60x60pt", "warn",
            "Could not analyze the icon image (heuristic unavailable) — look at it yourself at thumbnail size.",
            heuristic=True,
        )
    mean = sum(pixels) / len(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    stdev = variance ** 0.5
    if stdev < 18:
        return Check(
            "icon", "Icon readability at 60x60pt", "warn",
            f"Low contrast at {size_px}x{size_px}px (heuristic std dev {stdev:.0f}/128) — it may look flat or blend in next to other icons.",
            heuristic=True,
        )
    return Check(
        "icon", "Icon readability at 60x60pt", "pass",
        f"Enough contrast/detail at {size_px}x{size_px}px to likely read as more than a flat color (heuristic std dev {stdev:.0f}/128).",
        heuristic=True,
    )


def icon_check_unavailable(reason: str) -> Check:
    return Check("icon", "Icon readability at 60x60pt", "warn", reason, heuristic=True)


# ---------------------------------------------------------------------------
# 2. First 3 screenshots tell a value story
# ---------------------------------------------------------------------------
def screenshots_check(screenshot_count: int) -> Check:
    if screenshot_count <= 0:
        return Check("screenshots", "First 3 screenshots tell a value story", "fail",
                      "No screenshots were found on the listing.")
    if screenshot_count < 3:
        return Check("screenshots", "First 3 screenshots tell a value story", "fail",
                      f"Only {screenshot_count} screenshot(s) — Search results show the first 3, so fewer than 3 leaves the story untold.")
    return Check(
        "screenshots", "First 3 screenshots tell a value story", "warn",
        f"{screenshot_count} screenshots present (≥3). Whether they tell a clear story in sequence can't be read from image URLs alone — needs a human look.",
        heuristic=True,
    )


# ---------------------------------------------------------------------------
# 3. Title / subtitle states the outcome
# ---------------------------------------------------------------------------
_OUTCOME_WORDS = (
    "tracker", "counter", "planner", "coach", "generator", "maker", "builder", "editor", "scanner",
    "calculator", "assistant", "manager", "organizer", "journal", "trainer", "analyzer", "finder",
    "converter", "recorder", "reminder", "scheduler", "notes", "tracker", "logger",
)


def title_check(title: str) -> Check:
    title = (title or "").strip()
    if not title:
        return Check("title", "Title/subtitle states the outcome", "fail", "No title was found on the listing.")
    lower = title.lower()
    if any(word in lower for word in _OUTCOME_WORDS):
        return Check(
            "title", "Title/subtitle states the outcome", "pass",
            f'"{title}" names a concrete outcome word (e.g. tracker/counter/planner) rather than just a brand name.',
        )
    return Check(
        "title", "Title/subtitle states the outcome", "warn",
        f'"{title}" does not contain an obvious outcome word (heuristic keyword check) — a shopper may not know what it does from the title alone.',
        heuristic=True,
    )


# ---------------------------------------------------------------------------
# 4. Promo text / description leads with a concrete benefit
# ---------------------------------------------------------------------------
_GENERIC_OPENERS = (
    "welcome to", "the ultimate", "the best app", "the #1", "the number one", "introducing",
)
_BENEFIT_HINTS = (
    "track", "get", "scan", "save", "estimate", "generate", "plan", "learn", "build", "create",
    "find", "manage", "log", "record", "snap", "convert", "remind", "calculate", "organize",
)
_DIGIT = re.compile(r"\d")


def promo_text_check(description: str) -> Check:
    description = (description or "").strip()
    if not description:
        return Check("promo_text", "Promo text / description leads with a benefit", "fail",
                      "No description was found on the listing.")
    opening = re.split(r"(?<=[.!?])\s+|\n+", description, maxsplit=1)[0][:170]
    lower = opening.lower()
    if any(opener in lower for opener in _GENERIC_OPENERS):
        return Check(
            "promo_text", "Promo text / description leads with a benefit", "fail",
            f'Opens with a generic line ("{opening[:60]}…") instead of a concrete benefit.',
        )
    has_benefit = any(hint in lower for hint in _BENEFIT_HINTS) or bool(_DIGIT.search(opening))
    if has_benefit:
        return Check(
            "promo_text", "Promo text / description leads with a benefit", "pass",
            f'Opening line names a concrete action or number: "{opening[:120]}".',
        )
    return Check(
        "promo_text", "Promo text / description leads with a benefit", "warn",
        f'Opening line doesn\'t clearly name a concrete benefit (heuristic keyword check): "{opening[:120]}".',
        heuristic=True,
    )


# ---------------------------------------------------------------------------
# 5. Freshness: updated within the last 90 days
# ---------------------------------------------------------------------------
def freshness_check(current_version_release_date: str | None, *, now: datetime | None = None) -> Check:
    if not current_version_release_date:
        return Check(
            "freshness", "Updated in the last 90 days", "warn",
            "No last-update date in this data source — check the store listing page directly.",
        )
    try:
        updated = datetime.fromisoformat(current_version_release_date.replace("Z", "+00:00"))
    except ValueError:
        return Check("freshness", "Updated in the last 90 days", "warn",
                      "Could not parse the listing's update date.")
    now = now or datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age_days = (now - updated).days
    if age_days <= FRESH_DAYS:
        return Check("freshness", "Updated in the last 90 days", "pass",
                      f"Last updated {age_days} days ago.")
    if age_days <= STALE_DAYS:
        return Check("freshness", "Updated in the last 90 days", "warn",
                      f"Last updated {age_days} days ago (more than {FRESH_DAYS}).")
    return Check("freshness", "Updated in the last 90 days", "fail",
                 f"Last updated {age_days} days ago (more than {STALE_DAYS}).")


def score_packaging(checks: list[Check]) -> dict:
    return {
        "score": _score(checks),
        "checks": [
            {"id": c.id, "label": c.label, "status": c.status, "why": c.why, "heuristic": c.heuristic}
            for c in checks
        ],
    }


__all__ = [
    "Check",
    "FRESH_DAYS",
    "ICON_THUMBNAIL_PX",
    "STALE_DAYS",
    "Status",
    "analyze_icon_bytes",
    "freshness_check",
    "icon_check_unavailable",
    "promo_text_check",
    "score_packaging",
    "screenshots_check",
    "title_check",
]
