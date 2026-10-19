"""Apps shelf preview loops (Wave P PM2.2, MH8): plan the render jobs, record uploads.

Apps stay hidden until their preview loop is uploaded and recorded (no
placeholder tiles). This tool never renders and never uploads:

* ``--plan`` writes ``assets/presets/apps/preview-jobs.json``: one job per app,
  in order (free jobs first, then the paid ones the owner's promo budget covers),
  each naming its own inputs, the object key it will produce and its cost.
  Create-flow apps reuse a finished showcase loop of the same style (the same
  public object the landing already serves), so they cost nothing new and
  need no upload.
* ``--record <app_id> [--key K] [--dry-run]`` marks one uploaded loop live in
  ``previews.json`` after the deploy-time upload (``publish.py``-style, no deletes).
* ``--record-reuse [--dry-run]`` (Wave Q QM1.1) records every create-flow app
  live on its public showcase loop.
* ``--render-jobs [--free-only]`` prints the jobs that still need a render and
  an upload at deploy (the local tools are free; the image apps cost $0.48).

Run from the repo root: ``PYTHONPATH=apps/api python apps/api/tools/ops/apps_previews.py --plan``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
APPS = REPO / "apps" / "api" / "assets" / "presets" / "apps"
JOBS = APPS / "preview-jobs.json"
PREVIEWS = APPS / "previews.json"
SHOWCASE = REPO / "apps" / "api" / "tools" / "ops" / "showcase" / "sources.json"
SONG = "output000"
#: Our own inputs: the showcase posters and loops are our renders (sources.json records their licences).
REEL_FOR_STYLE = {"meme_hook": "sneaker-meme", "before_after": "kitchen-before-after", "": "serum-morning"}
PRODUCT_POSTER = "showcase/serum-morning-poster.jpg"
SECOND_POSTER = "showcase/latte-cafe-poster.jpg"
CLIP = "showcase/barber-meme.mp4"


def _apps() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(APPS.glob("*@v*.json"))]


def _job(app: dict) -> dict:
    out = f"presets/apps/{app['id']}.mp4"
    base = {"app_id": app["id"], "output_key": out, "poster_key": f"presets/apps/{app['id']}.jpg"}
    runner, tool = app["runner"], app.get("local", "")
    if runner == "plan":
        style = (app.get("plan") or {}).get("style", "")
        reel = REEL_FOR_STYLE.get(style, REEL_FOR_STYLE[""])
        # QM1.1: the public showcase loop (live on the media bucket), not the unpublished "-full" reel.
        return {**base, "kind": "reuse_showcase", "source_key": f"showcase/{reel}.mp4",
                "cost_usd": 0.0, "lane": "copy"}
    if runner == "image_edit":
        images = len((app.get("edit") or {}).get("angles") or []) or 1
        return {**base, "kind": "app_run_then_loop", "inputs": {"image_key": PRODUCT_POSTER,
                "text": "a sunlit marble bathroom shelf", "choice": "golden hour"},
                "images": images, "cost_usd": round(images * float(app["price"]["per_image_usd"]), 2),
                "lane": "paid (owner promo budget)"}
    inputs = {"transition": {"image_key": PRODUCT_POSTER, "image_key_2": SECOND_POSTER},
              "remove_bg": {"image_key": PRODUCT_POSTER},
              "beat_cut": {"video_key": CLIP, "music_id": SONG},
              "hook_score": {"video_key": CLIP, "text": "Nobody tells you this about fades"}}[tool]
    return {**base, "kind": "app_run_then_loop", "inputs": inputs, "cost_usd": 0.0, "lane": "mac or box 1 tier 3"}


def plan() -> dict:
    jobs = [_job(app) for app in _apps()]
    jobs.sort(key=lambda j: (j["cost_usd"] > 0, j["app_id"]))
    for order, job in enumerate(jobs, start=1):
        job["order"] = order
    return {"version": 1, "note": "Render jobs only; nothing here has been rendered or uploaded.",
            "total_cost_usd": round(sum(j["cost_usd"] for j in jobs), 2), "jobs": jobs}


def render_jobs(*, free_only: bool = False) -> list[dict]:
    """Jobs that still need a render and an upload at deploy (everything but the create-flow reuse)."""
    jobs = [j for j in plan()["jobs"] if j["kind"] != "reuse_showcase"]
    return [j for j in jobs if j["cost_usd"] == 0] if free_only else jobs


def record(app_id: str, key: str | None = None, *, dry_run: bool = False) -> dict:
    data = json.loads(PREVIEWS.read_text(encoding="utf-8"))
    ids = {a["id"] for a in _apps()}
    if app_id not in ids:
        raise SystemExit(f"unknown app {app_id}")
    live = dict(data.get("live") or {})
    live[app_id] = key or f"presets/apps/{app_id}.mp4"
    data = {**data, "live": dict(sorted(live.items()))}
    if not dry_run:
        PREVIEWS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def record_reuse(*, dry_run: bool = False) -> dict:
    """Record every create-flow app live on the public showcase loop it reuses."""
    data: dict = {}
    for job in plan()["jobs"]:
        if job["kind"] == "reuse_showcase":
            data = record(job["app_id"], job["source_key"], dry_run=dry_run)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--record")
    parser.add_argument("--key")
    parser.add_argument("--record-reuse", action="store_true")
    parser.add_argument("--render-jobs", action="store_true")
    parser.add_argument("--free-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.plan:
        JOBS.write_text(json.dumps(plan(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {JOBS.relative_to(REPO)}")
    elif args.record:
        record(args.record, args.key, dry_run=args.dry_run)
        print(f"{'would record' if args.dry_run else 'recorded'} {args.record}")
    elif args.record_reuse:
        live = record_reuse(dry_run=args.dry_run).get("live", {})
        print(f"{'would record' if args.dry_run else 'recorded'} {len(live)} live previews")
    elif args.render_jobs:
        print(json.dumps(render_jobs(free_only=args.free_only), indent=2))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
