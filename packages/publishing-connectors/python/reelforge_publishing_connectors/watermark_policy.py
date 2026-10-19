"""Foreign-watermark cross-post suppression rules (mirror of ``src/watermark-policy.ts``).

Platforms downrank / suppress clips carrying a *rival* platform's watermark
(e.g. a TikTok-watermarked clip reposted to Reels). This guards the cross-post
flow: reject or re-export before the reach penalty. Pure data.
"""

from __future__ import annotations

# target platform -> watermark sources it suppresses / penalizes.
_SUPPRESSED: dict[str, tuple[str, ...]] = {
    "instagram": ("tiktok", "musically", "capcut"),
    "youtube": ("tiktok", "musically"),
    "tiktok": ("instagram", "reels", "youtube", "shorts"),
    "x": (),
}


def is_watermark_allowed(target_platform: str, watermark_source: str) -> bool:
    """May a clip watermarked by ``watermark_source`` be posted to ``target_platform``?"""
    src = str(watermark_source or "").strip().lower()
    if not src:
        return True  # no foreign watermark
    suppressed = _SUPPRESSED.get(str(target_platform or "").strip().lower(), ())
    return src not in suppressed


def check_watermark(target_platform: str, watermark_source: str) -> dict:
    """``{allowed, reason}`` — reason is empty when allowed."""
    allowed = is_watermark_allowed(target_platform, watermark_source)
    reason = "" if allowed else (
        f"{watermark_source} watermark is suppressed on {target_platform}; "
        "re-export a clean version before cross-posting"
    )
    return {"allowed": allowed, "reason": reason}
