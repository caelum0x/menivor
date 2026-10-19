#!/usr/bin/env python3
"""Validate deployment configuration without printing secrets or calling providers.

This is a configuration gate, not a fake live-provider test.  It prevents the
common failure mode where a deployed credential quietly exposes checkout or
publishing before the launch switch and release approval are intentionally set.

The check logic itself lives in ``app.core.launch_preflight`` so the API
process can run the exact same checks at startup (fail-fast under a public
launch posture, warn-only in pilot/dev). This CLI stays the release-gate entry
point with unchanged flags, output, and exit codes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Runnable both as ``python3 apps/api/tools/ops/preflight.py`` (release gate,
# repo root) and from inside apps/api: put the API root on sys.path so the
# stdlib-only ``app.core.launch_preflight`` module resolves.
_API_ROOT = Path(__file__).resolve().parents[2]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.core.launch_preflight import (  # noqa: E402
    broll_provider,
    collect_preflight_errors,
    collect_preflight_warnings,
    launch_mode,
    public_tier,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true", help="require production dependencies")
    args = parser.parse_args()

    errors = collect_preflight_errors(production=args.production)
    if errors:
        print("ReelForge deployment preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    for note in collect_preflight_warnings():
        print(f"- warning: {note}")
    print(
        f"ReelForge deployment preflight passed "
        f"(mode={launch_mode()}, tier={public_tier()}, broll={broll_provider()})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
