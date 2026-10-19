"""Diff the curated hate-terms list against the upstream LDNOOBW lists.

Usage::

    python apps/api/tools/moderation/refresh_hate_terms.py            # fetch upstream, print the diff
    python apps/api/tools/moderation/refresh_hate_terms.py --offline DIR  # use local copies of en/tr/de

It never edits the list. Upstream mixes slurs with general profanity, so a
person reviews each "new upstream term" and adds the slurs to
``assets/moderation/hate_terms.json`` (category ``upstream``), bumping
``version`` and ``sources[0].commit``. Licence of the upstream data: CC-BY-4.0.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIST_FILE = ROOT / "assets" / "moderation" / "hate_terms.json"
RAW = "https://raw.githubusercontent.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words/master/{lang}"


def fold(text: str) -> str:
    lowered = str(text or "").replace("İ", "i").replace("I", "i").replace("ı", "i").casefold()
    return "".join(c for c in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(c)).strip()


def upstream_terms(langs: list[str], offline: Path | None) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for lang in langs:
        if offline:
            text = (offline / lang).read_text(encoding="utf-8")
        else:
            with urllib.request.urlopen(RAW.format(lang=lang), timeout=20) as resp:  # noqa: S310 - fixed https URL
                text = resp.read().decode("utf-8")
        out[lang] = {fold(line) for line in text.splitlines() if line.strip()}
    return out


def diff(data: dict, upstream: dict[str, set[str]]) -> dict[str, list[str]]:
    kept = {fold(t) for group in data["categories"].values() for t in group.get("upstream", [])}
    excluded = {fold(t) for t in data.get("excluded_from_upstream", {})}
    every = set().union(*upstream.values()) if upstream else set()
    return {
        "gone_upstream": sorted(kept - every),
        "not_reviewed": sorted(every - kept - excluded),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--langs", default="en,tr,de")
    parser.add_argument("--offline", type=Path, default=None)
    args = parser.parse_args(argv)
    data = json.loads(LIST_FILE.read_text(encoding="utf-8"))
    result = diff(data, upstream_terms([x for x in args.langs.split(",") if x], args.offline))
    print(json.dumps({"version": data["version"], "gone_upstream": result["gone_upstream"],
                      "not_reviewed_count": len(result["not_reviewed"])}, indent=2))
    return 1 if result["gone_upstream"] else 0


if __name__ == "__main__":
    sys.exit(main())
