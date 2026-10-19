"""Resolve a pasted ad link (incl. short links like vt.tiktok.com/XXXX) to its canonical post URL.

Every hop must stay on a recognised social host (``clipping.platform_source``), so a
short link can never be used to make the server fetch an arbitrary/internal URL.
The network hop is an injectable ``head(url) -> (status, location)`` seam.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

from app.domains.clipping.platform_source import platform_source_ref, recognize_platform

MAX_HOPS = 5
TIMEOUT_S = 10
_TIKTOK_VIDEO = re.compile(r"/@[^/]+/video/(\d+)")
_SHORT_HOSTS = {"vt.tiktok.com", "vm.tiktok.com", "youtu.be"}

Head = Callable[[str], tuple[int, str]]


class LinkError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ResolvedLink:
    url: str
    platform: str
    video_id: str
    source_ref: str
    hops: int


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003 - stdlib signature
        return None


def default_head(url: str) -> tuple[int, str]:
    """One GET hop without following redirects; returns (status, Location)."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0 (Menivor ad-clone)"})
    try:
        with opener.open(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - host allowlisted by caller
            return resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "") if exc.headers else ""


def _clean(url: str) -> str:
    """Drop query + fragment (tracking params such as _t / _r) from a canonical post URL."""
    p = urlparse(url)
    return urlunparse((p.scheme or "https", p.netloc, p.path, "", "", ""))


def _video_id(url: str) -> str:
    m = _TIKTOK_VIDEO.search(urlparse(url).path)
    return m.group(1) if m else ""


def resolve(raw_url: str, *, head: Head | None = None) -> ResolvedLink:
    text = (raw_url or "").strip()
    if not text:
        raise LinkError(400, "paste the link of the ad you want to clone")
    if not text.lower().startswith(("http://", "https://")):
        text = "https://" + text
    platform = recognize_platform(text)
    if platform is None:
        raise LinkError(422, "use a TikTok, YouTube, Vimeo or X link")
    hop = head or default_head
    url, hops = text, 0
    while (urlparse(url).hostname or "").lower() in _SHORT_HOSTS:
        if hops >= MAX_HOPS:
            raise LinkError(502, "the short link redirects too many times")
        try:
            status, location = hop(url)
        except Exception as exc:  # noqa: BLE001 - network boundary
            raise LinkError(502, "could not open the short link") from exc
        if status not in (301, 302, 303, 307, 308) or not location:
            raise LinkError(422, "the short link did not lead to a video")
        nxt = urljoin(url, location)
        if recognize_platform(nxt) is None:
            raise LinkError(422, "the short link points outside the supported platforms")
        url, hops = nxt, hops + 1
    canonical = _clean(url) if hops else url
    return ResolvedLink(url=canonical, platform=recognize_platform(canonical) or platform,
                        video_id=_video_id(canonical), source_ref=platform_source_ref(canonical), hops=hops)
