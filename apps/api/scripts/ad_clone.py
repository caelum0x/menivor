"""Ad Clone from the command line ($0: local analysis, no paid calls).

  python scripts/ad_clone.py https://vt.tiktok.com/XXXX/ --out ../../../gtm/oxhan-very-turkish-time/episodes/clone-XXXX \
      [--variations 3] [--aspect 9:16] [--language original] [--llm]

Writes brief.json, plan-<a|b|c>.yaml (make_episode.py format), costs.json and mj-prompts.md.
yt-dlp must be importable (PYTHONPATH) and REELFORGE_CLIPPING_PLATFORM_INGEST_ENABLED=1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domains.adclone import service  # noqa: E402
from app.domains.adclone.rewrite import CloneOptions  # noqa: E402


def _yaml(data: dict) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--out", required=True)
    ap.add_argument("--variations", type=int, default=3)
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--language", default="original")
    ap.add_argument("--engine")
    ap.add_argument("--source-file", help="analyse this already-downloaded copy instead of downloading again")
    ap.add_argument("--llm", action="store_true", help="refine + write with the configured LLM (Relay credits)")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    llm = service.default_llm() if args.llm else None
    downloader = None
    if args.source_file:
        def downloader(_url: str, dest_stem: str) -> str:
            import shutil

            dest = dest_stem + os.path.splitext(args.source_file)[1]
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(args.source_file, dest)
            return dest
    brief = service.analyze_link(args.url, llm=llm, downloader=downloader)
    result = service.clone(brief, options=CloneOptions(variations=args.variations, aspect=args.aspect,
                                                       language=args.language), engine=args.engine, llm=llm)
    with open(os.path.join(args.out, "brief.json"), "w", encoding="utf-8") as fh:
        json.dump(result["brief"], fh, indent=2, ensure_ascii=False)
    costs, mj = [], []
    for v in result["variations"]:
        plan = v["plan"]
        name = f"plan-{plan['clone']['variation']}.yaml"
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as fh:
            fh.write(f"# Ad Clone of {result['brief']['source']['url']} (structure only; new lines, our cast)\n")
            fh.write(_yaml(plan))
        costs.append({"plan": name, "chosen": {k: v["engine"][k] for k in ("engine", "usd", "reason", "dry_run_only")},
                      "estimates": [{k: r[k] for k in ("engine", "label", "usd", "configured", "source")}
                                    for r in v["estimates"]]})
        mj.append(f"## {name}\n\n" + "\n\n".join(f"**{p['still']}** (save as `{p['save_as']}`)\n\n```\n{p['prompt_v7']}\n```"
                                                 for p in v["midjourney"]))
    with open(os.path.join(args.out, "costs.json"), "w", encoding="utf-8") as fh:
        json.dump({"voice": result["voice"], "plans": costs}, fh, indent=2)
    with open(os.path.join(args.out, "mj-prompts.md"), "w", encoding="utf-8") as fh:
        fh.write("# Midjourney prompts (paste into Midjourney; drop results in mj-inbox/)\n\n" + "\n\n".join(mj) + "\n")
    print(json.dumps({"hook": result["brief"]["hook"], "beats": len(result["brief"]["beats"]), "costs": costs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
