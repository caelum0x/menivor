"""Download Pexels clips by video id for the landing showcase (ops tool).

Pexels License: free for commercial use, no attribution required. Picks a
<=1080p rendition when Pexels publishes one, trims to N seconds, strips audio,
and writes ``$SHOWCASE_WORK/stock/px-<id>.mp4``.

    python apps/api/tools/ops/showcase/fetch_pexels.py 8131891 7607767 ...
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) menivor-landing-samples"}
OUT = os.path.join(os.environ.get("SHOWCASE_WORK", "/tmp/menivor-showcase"), "stock")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


def original_url(vid: str) -> str:
    """The original file URL (Pexels' download link redirects to it)."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(f"https://www.pexels.com/download/video/{vid}/", headers=UA, method="HEAD")
    try:
        opener.open(req, timeout=30)
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("location", "")
        if location:
            return location
    raise RuntimeError(f"no download redirect for {vid}")


def _exists(url: str) -> bool:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA, method="HEAD"), timeout=30) as resp:
            return int(resp.headers.get("content-length", 0)) > 0
    except Exception:  # noqa: BLE001 - a missing rendition is expected
        return False


def pick(vid: str) -> str:
    """A 1080p (else 720p) rendition of the clip, else the original."""
    original = original_url(vid)
    match = re.search(r"-(?:uhd|hd|sd)_(\d+)_(\d+)_(\d+)fps\.mp4", original)
    if not match:
        return original
    width, height, fps = map(int, match.groups())
    sizes = [(1080, 1920), (720, 1280)] if height > width else [(1920, 1080), (1280, 720)]
    for w, h in sizes:
        for tier in ("hd", "uhd"):
            url = f"https://videos.pexels.com/video-files/{vid}/{vid}-{tier}_{w}_{h}_{fps}fps.mp4"
            if _exists(url):
                return url
    return original


def fetch(vid: str, seconds: int = 9) -> tuple[str, str]:
    dest = os.path.join(OUT, f"px-{vid}.mp4")
    if os.path.exists(dest):
        return dest, "cached"
    url = pick(vid)
    raw = dest + ".raw.mp4"
    subprocess.run(["curl", "-sL", "-A", UA["User-Agent"], "-o", raw, url], check=True, timeout=600)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", "0.3", "-t", str(seconds), "-i", raw, "-an",
         "-vf", "scale='if(gt(iw,ih),-2,1080)':'if(gt(iw,ih),1080,-2)',fps=30",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", dest],
        check=True, timeout=600,
    )
    os.remove(raw)
    return dest, url


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    log: dict[str, dict[str, str]] = {}
    for vid in sys.argv[1:]:
        try:
            path, source = fetch(vid)
        except Exception as exc:  # noqa: BLE001 - keep fetching the others
            print(vid, "FAIL", exc, flush=True)
            continue
        log[vid] = {"file": path, "source": source}
        print(vid, "ok", source, flush=True)
    with open(os.path.join(OUT, f"fetch-log-{os.getpid()}.json"), "w", encoding="utf-8") as handle:
        json.dump(log, handle, indent=1)


if __name__ == "__main__":
    main()
