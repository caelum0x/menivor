"""VAST 4.2 for one pre-roll (MV14). Our own ad decisions only; no wrappers, no third-party demand.

The media is a short-lived signed URL to the ad title's progressive MP4 (it is
fetched right before playback). Tracking events point at our tracker with a
per-event signature bound to one play with a 15-minute expiry, so counts cannot be
inflated by guessing or replaying URLs.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from app.domains.ott_commerce.models import OttAd

from .service import SKIP_AFTER_S, new_play, track_query

VERSION = "4.2"


def _hms(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}.000"


def empty() -> str:
    """A valid "no ad" answer."""
    return ET.tostring(ET.Element("VAST", version=VERSION), encoding="unicode", xml_declaration=True)


def build(ad: OttAd, *, media_url: str, api_base: str, play: tuple[str, int] | None = None) -> str:
    """One pre-roll. Every tracking URL is signed for this play only and expires in 15 min (P-M12)."""
    track = f"{api_base}/api/v1/ott/ads/track/{ad.id}"
    play_id, expires = play or new_play()

    def signed(event: str) -> str:
        return f"{track}/{event}?{track_query(ad.id, event, play_id, expires)}"

    root = ET.Element("VAST", version=VERSION)
    inline = ET.SubElement(ET.SubElement(root, "Ad", id=ad.id), "InLine")
    ET.SubElement(inline, "AdSystem").text = "Menivor"
    ET.SubElement(inline, "AdTitle").text = ad.name
    if ad.sponsor:
        ET.SubElement(inline, "Advertiser").text = ad.sponsor
    ET.SubElement(inline, "Impression", id="menivor").text = signed("impression")
    creative = ET.SubElement(ET.SubElement(inline, "Creatives"), "Creative", id=f"{ad.id}-1", sequence="1")
    linear = ET.SubElement(creative, "Linear", skipoffset=_hms(SKIP_AFTER_S)[:8])
    ET.SubElement(linear, "Duration").text = _hms(ad.duration_s)[:8]
    events = ET.SubElement(linear, "TrackingEvents")
    for event in ("start", "firstQuartile", "midpoint", "thirdQuartile", "complete", "skip"):
        ET.SubElement(events, "Tracking", event=event).text = signed(event)
    if ad.click_url:
        clicks = ET.SubElement(linear, "VideoClicks")
        ET.SubElement(clicks, "ClickThrough").text = ad.click_url
        ET.SubElement(clicks, "ClickTracking").text = signed("click")
    files = ET.SubElement(linear, "MediaFiles")
    ET.SubElement(files, "MediaFile", delivery="progressive", type="video/mp4", width="720", height="1280").text = \
        media_url
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


__all__ = ["VERSION", "build", "empty"]
