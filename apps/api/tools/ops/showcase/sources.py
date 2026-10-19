"""Write ``sources.json`` (the licence and source record of every showcase reel) from ``plan.py``.

    python apps/api/tools/ops/showcase/sources.py [--date YYYY-MM-DD]

Every footage clip, loop and voice is listed with its licence, so the landing's
"stock footage" credit and the no-repeat rules can be checked from one file.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from collections.abc import Mapping, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sources.json")


def _pexels(vid: str) -> dict:
    return {"source": "Pexels", "id": vid, "url": f"https://www.pexels.com/video/{vid}/", "license": "Pexels License"}


def loop_record(reel: Mapping) -> dict | None:
    spec = str(reel.get("loop") or "")
    if not spec:
        return None
    if spec == "@footage":
        return {"source": "footage montage"}
    if spec.startswith("px:"):
        return _pexels(spec[3:])
    return {"source": "bundled original loop", "file": spec, "license": "first-party"}


def reel_record(reel: Mapping) -> dict:
    if reel.get("page"):
        footage = [{"source": "live page recording", "url": reel["page"], "license": "our own product"}]
    else:
        footage = [_pexels(str(vid)) for vid in reel.get("footage") or []]
    return {
        "key": reel["key"],
        "niche": reel["niche"],
        "style": reel.get("style") or "voiceover (classic)",
        "footage": footage,
        "loop": loop_record(reel),
        "voice": {"engine": "edge-tts (free)", "name": reel["voice"]},
        "script_words": len(str(reel.get("script") or "").split()),
        "spend_usd": 0.0,
    }


def build(reels: Sequence[Mapping], generated: str, lane: str) -> dict:
    return {
        "generated": generated,
        "render_lane": lane,
        "total_spend_usd": 0.0,
        "reels": [reel_record(reel) for reel in reels],
    }


def main() -> None:
    sys.path.insert(0, HERE)
    import plan

    parser = argparse.ArgumentParser(description="Write sources.json from plan.py")
    parser.add_argument("--date", default=_dt.date.today().isoformat())
    args = parser.parse_args()
    data = build(plan.REELS, args.date, plan.RENDER_LANE)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {OUT} ({len(data['reels'])} reels)")


if __name__ == "__main__":
    main()
