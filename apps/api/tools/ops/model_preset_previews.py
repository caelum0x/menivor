"""Model-preset preview loops (Wave Q QM1.1, H4): plan inside the owner's M1 budget, record uploads.

The 12 model presets (``assets/presets/*@v1.json`` with ``"kind": "model"``)
stay hidden until each has a real preview loop, paid from the owner's promo
budget M1 ($15-40, carried from Wave P). There is never placeholder art. This
tool never renders, never uploads and never spends:

* ``--plan [--budget 40]`` prices each preset's preview at the preset's own
  tier and length (the same :func:`routing.tiers.resolve` a creator's job
  uses), cheapest first, and marks the ones that fit the budget as chosen.
* The render is a normal preset run on the house account (the shelf's own
  create call, so the preview is exactly what a creator gets), then the loop
  and poster are uploaded to the media bucket at deploy.
* ``--record <preset_id> --spend 0.35 [--dry-run]`` writes the manifest entry
  as ``staged`` and ``funded_by = owner-promo-M1``, refusing anything that is
  not a model preset or would take recorded M1 spend over the budget.

Run from the repo root:
``PYTHONPATH=apps/api python apps/api/tools/ops/model_preset_previews.py --plan``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
MANIFEST = REPO / "apps" / "api" / "assets" / "presets" / "previews.json"
FUNDED_BY = "owner-promo-M1"
BUDGET_ENV = "MENIVOR_M1_BUDGET_USD"
DEFAULT_BUDGET_USD = 40.0
SOURCE = "our render from the preset's own prompt"


def budget(env: dict | None = None) -> float:
    raw = (env if env is not None else os.environ).get(BUDGET_ENV, "")
    try:
        return float(raw) if str(raw).strip() else DEFAULT_BUDGET_USD
    except ValueError:
        return DEFAULT_BUDGET_USD


def _model_presets() -> list:
    from app.domains.presets_hub import catalog

    return [p for p in catalog.all_presets() if p.kind == catalog.KIND_MODEL]


def _route(preset):
    from app.domains.routing import tiers

    return tiers.resolve(preset.preset_sku, preset.tier, seconds=int(preset.seconds or 5),
                         available=lambda provider: True)


def plan(*, budget_usd: float | None = None) -> dict:
    cap = DEFAULT_BUDGET_USD if budget_usd is None else float(budget_usd)
    jobs = []
    for preset in _model_presets():
        route = _route(preset)
        jobs.append({"preset_id": preset.id, "model_id": route.model_id, "seconds": route.seconds,
                     "cost_usd": round(route.provider_usd, 4), "loop_key": f"presets/{preset.id}.mp4",
                     "poster_key": f"presets/{preset.id}.jpg"})
    jobs.sort(key=lambda j: (j["cost_usd"], j["preset_id"]))
    spent = 0.0
    for job in jobs:
        job["chosen"] = spent + job["cost_usd"] <= cap + 1e-9
        job["funded_by"] = FUNDED_BY if job["chosen"] else ""
        if job["chosen"]:
            spent += job["cost_usd"]
    return {"budget_usd": cap, "chosen_cost_usd": round(spent, 4), "jobs": jobs,
            "note": "Plan only: nothing here has been rendered, uploaded or paid."}


def _spent(previews: dict) -> float:
    return sum(float(e.get("spend_usd") or 0) for e in previews.values() if e.get("funded_by") == FUNDED_BY)


def record(preset_id: str, *, spend_usd: float, dry_run: bool = False, on: str | None = None,
           budget_usd: float | None = None) -> dict:
    from app.domains.presets_hub import catalog

    preset = catalog.get(preset_id)
    if preset is None or preset.kind != catalog.KIND_MODEL:
        raise SystemExit(f"{preset_id} is not a model preset; only model presets are paid M1 renders")
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    previews = dict(data.get("previews") or {})
    others = {k: v for k, v in previews.items() if k != preset.id}
    cap = budget() if budget_usd is None else float(budget_usd)
    if _spent(others) + float(spend_usd) > cap + 1e-9:
        raise SystemExit(f"recording {spend_usd} would take M1 spend over the ${cap:.2f} budget")
    entry = {"loop": f"presets/{preset.id}.mp4", "poster": f"presets/{preset.id}.jpg", "status": "staged",
             "rendered_at": on or datetime.now(timezone.utc).date().isoformat(),
             "spend_usd": round(float(spend_usd), 4), "funded_by": FUNDED_BY, "source": SOURCE}
    if not dry_run:
        previews[preset.id] = entry
        MANIFEST.write_text(json.dumps({**data, "previews": dict(sorted(previews.items()))}, indent=1) + "\n",
                            encoding="utf-8")
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--budget", type=float, default=None)
    parser.add_argument("--record")
    parser.add_argument("--spend", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps(plan(budget_usd=args.budget if args.budget is not None else budget()), indent=2))
    elif args.record:
        entry = record(args.record, spend_usd=args.spend, dry_run=args.dry_run, budget_usd=args.budget)
        print(json.dumps(entry, indent=2))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
