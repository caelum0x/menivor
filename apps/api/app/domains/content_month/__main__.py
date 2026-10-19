"""Content Month CLI: make a month of posts for our own sites (dogfood), no database needed.

    python -m app.domains.content_month run https://scribase.com https://menivor.com --out /tmp/month
    python -m app.domains.content_month run bidstage.app --render 8 --size instagram --no-video

For each site: read it, write ``ideas.json`` (every idea with format, hook,
slides, caption, reel request), and render the first ``--render`` carousels to
``<site>/<n>-<format>/`` as PNG slides, ``carousel.pdf`` and ``carousel.mp4``.
The LLM route is the API's (Relay on the box); without one the rules write the copy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from loguru import logger

from app.domains.content_month import formats as fm
from app.domains.content_month import ideas as ideas_mod
from app.domains.content_month import raster, slides
from app.domains.content_month.brief import SiteBrief, from_analysis
from app.domains.content_month.reel import reel_job

LOGO_KEY = "uploads/cli-logo.png"
_SAFE = re.compile(r"[^a-z0-9.-]+")


def _logo(brief: SiteBrief) -> bytes:
    if not brief.logo_url.startswith("https://"):
        return b""
    try:
        from app.domains.adstudio.fetch import IMAGE_MAX_BYTES, safe_get

        return safe_get(brief.logo_url, max_bytes=IMAGE_MAX_BYTES, accept="image/*").body
    except Exception as exc:  # noqa: BLE001 - slides fall back to the brand name
        logger.info(f"logo skipped for {brief.domain}: {exc}")
        return b""


def _style(brief: SiteBrief, has_logo: bool) -> Any:
    from app.domains.design.service import style_from_brand

    return style_from_brand(brief.brand(), LOGO_KEY if has_logo else "")


def run_site(url: str, out_dir: str, *, count: int, render: int, size: str, video: bool, use_llm: bool) -> dict:
    from app.domains.brand_agent.site_analysis import analyze_site

    target = url if url.startswith(("http://", "https://")) else f"https://{url}"
    brief = from_analysis(analyze_site(target))
    items = ideas_mod.month_ideas(brief, count=count, use_llm=use_llm)
    site_dir = os.path.join(out_dir, _SAFE.sub("-", brief.domain.lower()) or "site")
    os.makedirs(site_dir, exist_ok=True)
    logo = _logo(brief)
    style = _style(brief, bool(logo))
    _, width, height = slides.SIZES[size]
    rendered: list[str] = []
    for position, idea in enumerate(items):
        if idea["kind"] == fm.KIND_REEL:
            idea["reel_job"] = reel_job(f"cli{position}", idea["hook"], idea["script"], brief.language, position)
        if idea["kind"] != fm.KIND_CAROUSEL or len(rendered) >= render:
            continue
        folder = os.path.join(site_dir, f"{position + 1:02d}-{idea['format']}")
        os.makedirs(folder, exist_ok=True)
        pngs = raster.render_pages(slides.deck(idea["slides"], style, size), width, height,
                                   load_image=lambda key: logo)
        for index, data in enumerate(pngs, start=1):
            with open(os.path.join(folder, f"slide-{index:02d}.png"), "wb") as fp:
                fp.write(data)
        with open(os.path.join(folder, "carousel.pdf"), "wb") as fp:
            fp.write(raster.to_pdf(pngs))
        if video:
            with open(os.path.join(folder, "carousel.mp4"), "wb") as fp:
                fp.write(raster.to_mp4(pngs, width, height))
        with open(os.path.join(folder, "caption.txt"), "w", encoding="utf-8") as fp:
            fp.write(idea["caption"] + "\n")
        idea["rendered_to"] = folder
        rendered.append(folder)
    with open(os.path.join(site_dir, "ideas.json"), "w", encoding="utf-8") as fp:
        json.dump({"site": brief.to_dict(), "ideas": items}, fp, ensure_ascii=False, indent=1)
    summary = {"site": brief.domain, "ideas": len(items), "llm": sum(1 for i in items if i["source"] == "llm"),
               "carousels_rendered": len(rendered), "dir": site_dir}
    logger.info(f"content month: {summary}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.domains.content_month")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="make a month of posts for one or more websites")
    run.add_argument("urls", nargs="+")
    run.add_argument("--out", default="/tmp/content-month")
    run.add_argument("--count", type=int, default=ideas_mod.DEFAULT_COUNT)
    run.add_argument("--render", type=int, default=6, help="carousels to render per site")
    run.add_argument("--size", choices=sorted(slides.SIZES), default=slides.DEFAULT_SIZE)
    run.add_argument("--no-video", action="store_true")
    run.add_argument("--no-llm", action="store_true")
    args = parser.parse_args(argv)
    results = []
    for url in args.urls:
        try:
            results.append(run_site(url, args.out, count=args.count, render=args.render, size=args.size,
                                    video=not args.no_video, use_llm=not args.no_llm))
        except Exception as exc:  # noqa: BLE001 - one bad site never stops the batch
            logger.error(f"content month: {url} failed: {exc}")
            results.append({"site": url, "error": str(exc)})
    sys.stdout.write(json.dumps(results, indent=1) + "\n")
    return 0 if all("error" not in r for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
