#!/usr/bin/env python3
"""Post-deploy HTTP smoke: liveness, readiness, and launch-policy visibility."""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def get_json(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=10) as response:  # noqa: S310 - operator supplied endpoint
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, {}
    except (URLError, ValueError) as exc:
        raise RuntimeError(f"{url}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="API origin, e.g. https://api.reelforge.example")
    parser.add_argument("--expect-mode", choices=("internal_pilot", "public"), required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    checks = [("healthz", f"{base}/healthz"), ("readyz", f"{base}/readyz")]
    failed = False
    for name, url in checks:
        status, body = get_json(url)
        ok = status == 200 and body.get("status") in ({"ok", "ready"})
        print(f"{'PASS' if ok else 'FAIL'} {name}: HTTP {status}")
        failed = failed or not ok
    status, body = get_json(f"{base}/api/v1/launch/status")
    data = body.get("data", {}) if isinstance(body, dict) else {}
    ok = status == 200 and data.get("mode") == args.expect_mode
    print(f"{'PASS' if ok else 'FAIL'} launch status: HTTP {status}, mode={data.get('mode')!r}")
    return 1 if failed or not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
