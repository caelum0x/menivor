"""Which connected platforms can share post numbers, and what to do when not.

The scope a platform needs to read a post's numbers:

* TikTok - ``video.list`` (Display API; the creator's own videos only).
* YouTube - ``yt-analytics.readonly`` (views, watch time) or any read scope for
  the Data API counters (``youtube.readonly`` / ``youtube`` / ``youtube.force-ssl``).
* Instagram - ``instagram_business_manage_insights`` (Instagram Login) or
  ``instagram_manage_insights`` (Facebook Login).
* Facebook Pages - ``pages_read_engagement`` for likes/comments, ``read_insights``
  for video views.
* Threads - ``threads_manage_insights``.
* X - ``tweet.read`` (numbers only on a paid X API plan).
* Bluesky - public; no permission needed.

An empty grant string means "unknown" (older connections did not store it): the
read is attempted and a permission error then asks for a reconnect.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.social_inbox.capabilities import PLATFORM_LABELS, scope_tokens

NATIVE_PLATFORMS: frozenset[str] = frozenset({"tiktok", "youtube", "instagram"})

METRIC_SCOPES: dict[str, frozenset[str]] = {
    "tiktok": frozenset({"video.list"}),
    "youtube": frozenset({"yt-analytics.readonly", "youtube.readonly", "youtube", "youtube.force-ssl"}),
    "instagram": frozenset({"instagram_manage_insights", "instagram_business_manage_insights"}),
    "facebook": frozenset({"pages_read_engagement", "read_insights"}),
    "threads": frozenset({"threads_manage_insights"}),
    "x": frozenset({"tweet.read"}),
}

PUBLIC_PLATFORMS: frozenset[str] = frozenset({"bluesky"})

NOT_OFFERED: dict[str, str] = {
    "linkedin": "LinkedIn does not share post numbers with apps like Menivor yet.",
    "pinterest": "Pinterest numbers are not read yet.",
    "telegram": "Telegram does not share post numbers.",
    "discord": "Discord does not share post numbers.",
    "mastodon": "Mastodon numbers are not read yet.",
}

#: Platforms shown on the results page even before they are connected.
SUGGESTED: tuple[str, ...] = ("tiktok", "youtube", "instagram")


def can_connect(platform: str) -> bool:
    """Whether a connect button for ``platform`` can work on this server.

    Native platforms need the operator's OAuth client id; without it the
    authorize call answers 503, so the page must not offer that button. Other
    platforms connect from the Connections page, which handles its own setup.
    """
    if platform not in NATIVE_PLATFORMS:
        return True
    try:
        from app.services.oauth_connect import client_configured

        return client_configured(platform)
    except Exception:  # noqa: BLE001 - unknown means do not offer a dead button
        return False


def label(platform: str) -> str:
    return PLATFORM_LABELS.get(platform, platform.capitalize())


@dataclass(frozen=True)
class MetricsAccess:
    platform: str
    connected: bool
    reads_numbers: bool
    needs_reconnect: bool
    note: str = ""

    def to_record(self) -> dict:
        return {
            "platform": self.platform,
            "label": label(self.platform),
            "connected": self.connected,
            "reads_numbers": self.reads_numbers,
            "needs_reconnect": self.needs_reconnect,
            "reconnect_here": self.platform in NATIVE_PLATFORMS,
            "can_connect": can_connect(self.platform),
            "note": self.note,
        }


def metrics_access(platform: str, *, connected: bool, scopes: str = "") -> MetricsAccess:
    """Can Menivor read post numbers through this connection?"""
    plat = str(platform or "").strip().lower()
    name = label(plat)
    if plat in PUBLIC_PLATFORMS:
        return MetricsAccess(plat, connected, True, False)
    if plat in NOT_OFFERED:
        return MetricsAccess(plat, connected, False, False, NOT_OFFERED[plat])
    required = METRIC_SCOPES.get(plat)
    if required is None:
        return MetricsAccess(plat, connected, False, False, f"{name} numbers are not read yet.")
    if not connected:
        return MetricsAccess(plat, False, False, False, f"Connect {name} and Menivor reads your numbers for you.")
    granted = scope_tokens(scopes)
    if granted and not (granted & required):
        return MetricsAccess(
            plat, True, False, True,
            f"Reconnect {name} and allow access to your stats so Menivor can read your views.",
        )
    note = ""
    if plat == "facebook" and granted and "read_insights" not in granted:
        note = "Reconnect Facebook and allow insights to see views too."
    if plat == "x":
        note = "X shares numbers only on a paid X API plan."
    return MetricsAccess(plat, True, True, bool(note) and plat == "facebook", note)


__all__ = [
    "METRIC_SCOPES",
    "MetricsAccess",
    "NATIVE_PLATFORMS",
    "NOT_OFFERED",
    "PUBLIC_PLATFORMS",
    "SUGGESTED",
    "can_connect",
    "label",
    "metrics_access",
]
