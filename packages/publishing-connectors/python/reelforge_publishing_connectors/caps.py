"""Per-platform publish capability / limit table (mirror of ``src/caps.ts``).

Shared so the cap-aware composer (web/mobile) and the publish policy (api) reject
an over-limit post *before* the upload. Pure data + validation. Feeds
``publishing/policy.py``.
"""

from __future__ import annotations

PLATFORMS: tuple[str, ...] = ("tiktok", "instagram", "youtube", "x")

# Conservative, reviewed limits (confirm against live platform docs before prod).
CAPS: dict[str, dict] = {
    "tiktok": {"min_duration_s": 3, "max_duration_s": 600, "aspects": ["9:16"],
               "daily_cap": 15, "caption_max": 2200, "formats": ["mp4"]},
    "instagram": {"min_duration_s": 3, "max_duration_s": 90, "aspects": ["9:16", "1:1", "4:5"],
                  "daily_cap": 50, "caption_max": 2200, "formats": ["mp4", "mov"]},
    "youtube": {"min_duration_s": 1, "max_duration_s": 180, "aspects": ["9:16"],
                "daily_cap": 100, "caption_max": 100, "formats": ["mp4", "mov"]},
    "x": {"min_duration_s": 1, "max_duration_s": 140, "aspects": ["9:16", "16:9", "1:1"],
          "daily_cap": 1000, "caption_max": 280, "formats": ["mp4"]},
}


def caps_for(platform: str) -> dict | None:
    return CAPS.get(str(platform or "").strip().lower())


def validate_publish(platform: str, *, duration_s: float, aspect: str,
                     caption_len: int, fmt: str = "mp4") -> list[str]:
    """Reject an out-of-spec post before upload. Empty list = OK."""
    c = caps_for(platform)
    if c is None:
        return [f"unknown platform {platform!r}"]
    errors: list[str] = []
    if duration_s < c["min_duration_s"]:
        errors.append(f"{platform}: duration {duration_s}s below min {c['min_duration_s']}s")
    if duration_s > c["max_duration_s"]:
        errors.append(f"{platform}: duration {duration_s}s over max {c['max_duration_s']}s")
    if aspect not in c["aspects"]:
        errors.append(f"{platform}: aspect {aspect} not in {c['aspects']}")
    if caption_len > c["caption_max"]:
        errors.append(f"{platform}: caption {caption_len} chars over max {c['caption_max']}")
    if fmt.lower() not in c["formats"]:
        errors.append(f"{platform}: format {fmt} not in {c['formats']}")
    return errors


def remaining_daily(platform: str, posted_today: int) -> int:
    """How many more posts are allowed on ``platform`` today."""
    c = caps_for(platform)
    if c is None:
        return 0
    return max(0, int(c["daily_cap"]) - max(0, int(posted_today)))
