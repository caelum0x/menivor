"""Can this creator publish-and-test Ad Studio ads right now? (read-only)

"Publish and test" hands finished ads to the existing native scheduled-publish
path, so every gate that path enforces is surfaced here *before* the click,
each with a plain reason the page can show:

* **launch flag** — ``publishing_enabled()`` is closed during the internal
  pilot (and whenever an operator closes it). Closed publishing still allows a
  *manual* test: the creator posts the ads and logs the numbers, and the same
  48h loop ranks them.
* **Pro entitlement** — the due-runner re-checks it at post time; checked here
  so a creator is not surprised later. Only evaluated when publishing is open.
* **connections** — which of TikTok / Instagram / YouTube have an OAuth
  connection (existence only; no token refresh or network call on a read).
* **quota** — each platform's daily cap and minimum gap from the scheduling
  policy, so the page can say how many days a batch of N ads will take.

Nothing here writes or posts.
"""

from __future__ import annotations

import math
from typing import Any

from loguru import logger

from app.domains.publishing.scheduling_policy import platform_config

# Loop platform vocabulary (``tiktok|instagram|youtube``) -> display label.
PLATFORM_LABELS: dict[str, str] = {"tiktok": "TikTok", "instagram": "Instagram Reels", "youtube": "YouTube Shorts"}
TEST_PLATFORMS: tuple[str, ...] = tuple(PLATFORM_LABELS)


def launch_state() -> dict[str, Any]:
    """Launch mode + whether direct publishing is open (fails closed)."""
    try:
        from app.core.launch.policy import launch_mode, publishing_enabled

        mode = launch_mode()
        enabled = bool(publishing_enabled())
    except Exception as exc:  # noqa: BLE001 - a broken flag reads as closed
        logger.warning(f"adstudio publish gate: launch policy unavailable: {exc}")
        mode, enabled = "internal_pilot", False
    if enabled:
        reason = ""
    elif mode != "public":
        reason = (
            "Direct publishing is off during the private beta. You can still run a manual test: "
            "post the ads yourself, log each ad's numbers here, and the loop ranks them."
        )
    else:
        reason = (
            "Direct publishing is switched off right now. You can still run a manual test and "
            "log each ad's numbers yourself."
        )
    return {"enabled": enabled, "mode": mode, "pilot": mode != "public", "reason": reason}


def pro_state(user_id: str) -> dict[str, Any]:
    """``active`` | ``required`` | ``unavailable`` for paid access (any source)."""
    try:
        from app.services import user_entitlements as ue
    except Exception:  # noqa: BLE001 - billing layer missing
        return {"status": "unavailable", "reason": "Plan verification is unavailable right now."}
    try:
        ue.require_paid_access(str(user_id))
    except ue.PaidAccessDenied:
        return {"status": "required", "reason": "Scheduled publishing needs a paid plan or credit pack."}
    except Exception as exc:  # noqa: BLE001 - verification failure fails closed
        logger.warning(f"adstudio publish gate: entitlement check unavailable: {type(exc).__name__}")
        return {"status": "unavailable", "reason": "Plan verification is unavailable right now. Try again shortly."}
    return {"status": "active", "reason": ""}


def connected_platforms(session: Any, user_id: str) -> dict[str, bool]:
    """Which test platforms have a stored OAuth connection (no refresh)."""
    out = {p: False for p in TEST_PLATFORMS}
    try:
        from app.services import oauth_connect

        for platform in TEST_PLATFORMS:
            out[platform] = oauth_connect.get_account(session, user_id, platform) is not None
    except Exception as exc:  # noqa: BLE001 - connections layer missing reads as none
        logger.warning(f"adstudio publish gate: connections unavailable: {exc}")
    return out


def platform_quota(platform: str, ad_count: int) -> dict[str, Any]:
    """Daily cap / min gap for a platform and the days ``ad_count`` posts need."""
    policy_name = "youtube" if platform == "youtube" else platform
    cfg = platform_config(policy_name)
    cap = max(1, int(cfg["daily_cap"]))
    return {
        "daily_cap": cap,
        "min_gap_hours": float(cfg["min_gap_h"]),
        "days_needed": max(1, math.ceil(max(0, int(ad_count)) / cap)) if ad_count else 0,
    }


def readiness(session: Any, user_id: str, *, ad_count: int, check_pro: bool = True) -> dict[str, Any]:
    """Everything the page needs to enable, disable or explain the button."""
    launch = launch_state()
    connected = connected_platforms(session, user_id)
    pro = pro_state(user_id) if (launch["enabled"] and check_pro) else {"status": "skipped", "reason": ""}
    platforms = [
        {
            "platform": platform,
            "label": PLATFORM_LABELS[platform],
            "connected": connected[platform],
            **platform_quota(platform, ad_count),
        }
        for platform in TEST_PLATFORMS
    ]
    any_connected = any(connected.values())
    can_auto = bool(launch["enabled"] and pro["status"] == "active" and any_connected)
    if not launch["enabled"]:
        blocker = launch["reason"]
    elif pro["status"] != "active":
        blocker = pro["reason"]
    elif not any_connected:
        blocker = "Connect TikTok, Instagram or YouTube first to publish directly."
    else:
        blocker = ""
    return {
        "publishing": launch,
        "pro": pro,
        "platforms": platforms,
        "can_publish": can_auto,
        "can_track_manually": True,
        "blocker": blocker,
    }


__all__ = [
    "PLATFORM_LABELS",
    "TEST_PLATFORMS",
    "connected_platforms",
    "launch_state",
    "platform_quota",
    "pro_state",
    "readiness",
]
