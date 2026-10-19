"""Clone briefs from ads found in official ad libraries (competitor tracker -> Ad Clone).

Two paths, both $0 and local:

* :func:`brief_from_copy` - the Meta Ad Library API returns the ad's copy but no
  video, so the brief is built from the copy's structure (one beat per sentence over
  a default length). It keeps the hook device and pacing, never the words: Ad Clone's
  IP guard still refuses plans that copy source lines, and the advertiser's name is
  an avoid term.
* :func:`brief_from_media` - when the API gave a video file on an official ad-library
  CDN host (TikTok Commercial Content API), the file is analysed exactly like a pasted
  link (shots, OCR, Whisper) and deleted afterwards.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from .analyze import Observations, ShotObs, SpeechObs, heuristic_brief
from .schemas import CloneBrief
from .service import AdCloneError

#: Official ad-library media hosts (TikTok and Meta CDNs). Anything else is refused.
CDN_SUFFIXES = (".tiktokcdn.com", ".tiktokcdn-us.com", ".tiktokcdn-eu.com", ".ibyteimg.com", ".fbcdn.net")
MAX_BYTES = 80 * 1024 * 1024
DEFAULT_SECONDS = 15.0
MAX_BEATS = 6
COPY_NOTE = "structure from the ad copy: the ad library gives no video for this ad"
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")

Downloader = Callable[[str, str], str]


def _sentences(*texts: str) -> list[str]:
    out: list[str] = []
    for text in texts:
        for part in _SENTENCE.split(str(text or "")):
            clean = " ".join(part.split())
            if len(clean) >= 3 and clean not in out:
                out.append(clean[:280])
    return out[:MAX_BEATS]


def brief_from_copy(*, url: str, platform: str, source_ref: str, advertiser: str, body: str, title: str = "",
                    language: str = "en", seconds: float = DEFAULT_SECONDS) -> CloneBrief:
    lines = _sentences(body, title)
    if not lines:
        raise AdCloneError(422, "This ad has no copy or video to learn from.")
    span = round(seconds / len(lines), 3)
    shots = tuple(ShotObs(start_s=round(i * span, 3), end_s=round((i + 1) * span, 3), face_ratio=0.2)
                  for i in range(len(lines)))
    speech = tuple(SpeechObs(start_s=s.start_s, end_s=s.end_s, text=line) for s, line in zip(shots, lines))
    obs = Observations(url=url[:500], platform=platform[:20], source_ref=source_ref[:120], duration_s=seconds,
                       width=1080, height=1920, shots=shots, speech=speech, language=language or "en",
                       avoid_terms=tuple(t for t in (advertiser.strip(),) if t), notes=(COPY_NOTE,),
                       ocr_available=False)
    return heuristic_brief(obs)


def allowed_media(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host.endswith(s) for s in CDN_SUFFIXES)


def default_downloader(url: str, dest: str) -> str:
    """Fetch an allowlisted CDN file with a size cap; no redirects off the allowlist."""
    req = urllib.request.Request(url, headers={"User-Agent": "Menivor competitor tracker"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:  # noqa: S310 - allowlisted
        if not allowed_media(resp.geturl()):
            raise AdCloneError(422, "the ad video moved off the ad library host")
        total = 0
        while chunk := resp.read(1 << 16):
            total += len(chunk)
            if total > MAX_BYTES:
                raise AdCloneError(413, "the ad video is too large to analyse")
            out.write(chunk)
    return dest


def brief_from_media(media_url: str, *, page_url: str, platform: str, source_ref: str, advertiser: str,
                     downloader: Downloader | None = None, observer: Callable[..., Any] | None = None,
                     language: str | None = None) -> CloneBrief:
    if not allowed_media(media_url):
        raise AdCloneError(422, "only videos from the official ad library can be analysed")
    from .ingest import observe

    root = tempfile.mkdtemp(prefix="adclone-tracked-")
    try:
        path = (downloader or default_downloader)(media_url, os.path.join(root, "source.mp4"))
        obs = (observer or observe)(path, os.path.join(root, "frames"), url=page_url[:500], platform=platform,
                                    source_ref=source_ref, extra_avoid=(advertiser,) if advertiser else (),
                                    language=language)
        return heuristic_brief(obs)
    finally:
        shutil.rmtree(root, ignore_errors=True)


__all__ = ["CDN_SUFFIXES", "allowed_media", "brief_from_copy", "brief_from_media"]
