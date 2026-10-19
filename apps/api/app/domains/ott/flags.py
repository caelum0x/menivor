"""OTT flags (PM2.0 steward): one master switch and one switch per surface, all off.

A surface is on only when ``OTT_ENABLED`` and its own flag are both on
(``1``, ``true``, ``yes`` or ``on``). Every OTT route calls :func:`require`, so
with the flags off the routes answer 404 exactly like an unknown path and the
public API surface is unchanged. Copy that names a surface is gated on the same
flag (claims rule: no claim before its flag is Live).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from fastapi import HTTPException

MASTER = "OTT_ENABLED"
#: surface id -> env flag. ``cms`` covers the catalog and one-click publish
#: (MV1), ``upload`` resumable uploads and transcode lanes (MV2), ``packaging``
#: the CMAF ladder and tier-1 encryption (MV3), ``storefront``/``embed``/``feeds``
#: the viewer surfaces (MV4) and ``access`` playback tokens and keys (MV5).
#: P3 (PM3.0 steward): ``viewers`` channel viewer accounts (MV6), ``plans`` OTT
#: plans and meters (MV7), ``commerce`` SVOD/TVOD/rentals with the creator as
#: merchant (MV13), ``ads`` house and sponsor ads (MV14), ``tv`` the TV app API
#: (MV8/MV9), ``live`` live streams (MV10), ``chat`` live chat (MV11), ``fast``
#: linear channels (MV15), ``analytics`` QoE beacons (MV12), ``ai`` the AI panel
#: (MV16) and ``discovery`` search and "ask this video" (MV19).
SURFACES: dict[str, str] = {
    "cms": "OTT_CMS_LIVE",
    "upload": "OTT_UPLOAD_LIVE",
    "packaging": "OTT_PACKAGING_LIVE",
    "storefront": "OTT_STOREFRONT_LIVE",
    "embed": "OTT_EMBED_LIVE",
    "feeds": "OTT_FEEDS_LIVE",
    "access": "OTT_ACCESS_LIVE",
    "viewers": "OTT_VIEWERS_LIVE",
    "plans": "OTT_PLANS_LIVE",
    "commerce": "OTT_COMMERCE_LIVE",
    "ads": "OTT_ADS_LIVE",
    "tv": "OTT_TV_LIVE",
    "live": "OTT_LIVE_LIVE",
    "chat": "OTT_CHAT_LIVE",
    "fast": "OTT_FAST_LIVE",
    "analytics": "OTT_ANALYTICS_LIVE",
    "ai": "OTT_AI_LIVE",
    "discovery": "OTT_DISCOVERY_LIVE",
}
_ON = frozenset({"1", "true", "yes", "on"})


def _on(value: str | None) -> bool:
    return (value or "").strip().lower() in _ON


def enabled(surface: str, env: Mapping[str, str] | None = None) -> bool:
    """Whether ``surface`` is live: the master flag and the surface flag are both on."""
    source = os.environ if env is None else env
    flag = SURFACES.get(surface)
    if flag is None:
        raise KeyError(f"unknown OTT surface {surface!r}")
    return _on(source.get(MASTER)) and _on(source.get(flag))


def snapshot(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    return {surface: enabled(surface, env) for surface in SURFACES}


def require(surface: str) -> Callable[[], None]:
    """A FastAPI dependency: 404 while ``surface`` is off (the route looks unknown)."""
    if surface not in SURFACES:
        raise KeyError(f"unknown OTT surface {surface!r}")

    def _dependency() -> None:
        if not enabled(surface):
            raise HTTPException(status_code=404, detail="Not Found")

    return _dependency


__all__ = ["MASTER", "SURFACES", "enabled", "require", "snapshot"]
