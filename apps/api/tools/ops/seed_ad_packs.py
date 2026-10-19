#!/usr/bin/env python3
"""Seed Menivor with our own products' ad packs (dry run by default).

Reads ``gtm/menivor-ads/*.json`` (see ``ad_packs.py`` for the schema), checks
every pack, and prints the exact API request bodies. With ``--apply`` it calls
the Menivor HTTP API as the owner of ``--api-key``:

1. ``POST /api/v1/ad-studio/projects`` - one draft project per product, titled
   ``Menivor ad pack: <name>``, with the 5 reviewed angles. No variants are
   queued, so nothing renders and no credits are spent.
2. ``POST /api/v1/capture`` - one capture per pack source (website, store
   listing, or ``--native`` games on a simulator host). A capture only records
   a video; it becomes an approvals item (``capture_publish``) when the owner
   turns on "Suggest reel ads from finished captures", and approving that item
   renders captions-only reels with no publish targets.

Nothing is published, posted or charged by this script. It is idempotent:
projects are matched by title and captures by (kind, source), so a rerun only
creates what is missing (e.g. captures that were deferred by the 3-active
capture limit).

Usage
-----
  python apps/api/tools/ops/seed_ad_packs.py                       # validate + print plan
  python apps/api/tools/ops/seed_ad_packs.py --only caldesk --json # one pack, machine-readable
  MENIVOR_API_KEY=... python apps/api/tools/ops/seed_ad_packs.py --apply \\
      --api-base https://api.menivor.com [--native] [--skip-captures]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ad_packs  # noqa: E402  (sibling module; tools/ops is not a package)

DEFAULT_API_BASE = "https://api.menivor.com"
API_PREFIX = "/api/v1"
PAGE_SIZE = 100
MAX_PAGES = 50
TIMEOUT_S = 60
#: Default location: <products>/gtm/menivor-ads next to the videogen checkout.
DEFAULT_PACKS_DIR = Path(__file__).resolve().parents[4].parent / "gtm" / "menivor-ads"
_LIVE_CAPTURE_STATES = frozenset({"queued", "running", "succeeded"})


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


#: (method, path, json body or None) -> decoded ``data`` of the response envelope.
Transport = Callable[[str, str, "dict[str, Any] | None"], Any]


def http_transport(api_base: str, api_key: str) -> Transport:
    base = api_base.rstrip("/") + API_PREFIX

    def call(method: str, path: str, body: dict[str, Any] | None) -> Any:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base + path, data=payload, method=method)
        req.add_header("x-api-key", api_key)
        req.add_header("accept", "application/json")
        if payload is not None:
            req.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - operator-given API base
                raw = resp.read().decode("utf-8") or "{}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            try:
                detail = str(json.loads(detail).get("message") or detail)
            except (ValueError, AttributeError):
                pass
            raise ApiError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise ApiError(0, f"cannot reach {base}: {exc.reason}") from exc
        envelope = json.loads(raw)
        return envelope.get("data") if isinstance(envelope, dict) else envelope

    return call


def _paged(call: Transport, path: str, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(MAX_PAGES):
        data = call("GET", f"{path}?limit={PAGE_SIZE}&offset={page * PAGE_SIZE}", None) or {}
        batch = list(data.get(key) or [])
        rows += batch
        if not data.get("has_more") or not batch:
            break
    return rows


def _capture_key(row: dict[str, Any]) -> tuple[str, str]:
    kind = str(row.get("source_kind") or row.get("kind") or "")
    source = str(row.get("source_url") or row.get("url") or "")
    return kind, source if kind == "native_game" else ad_packs.normalize_url(source)


def apply_packs(packs: list[ad_packs.AdPack], call: Transport, *, native: bool = False,
                skip_captures: bool = False) -> list[dict[str, Any]]:
    """Create missing drafts; returns one action record per project/capture."""
    actions: list[dict[str, Any]] = []
    existing_projects = {str(p.get("title") or ""): p for p in _paged(call, "/ad-studio/projects", "projects")}
    existing_captures: dict[tuple[str, str], dict[str, Any]] = {}
    native_enabled = False
    if not skip_captures:
        for row in _paged(call, "/capture", "captures"):
            if str(row.get("status") or "") in _LIVE_CAPTURE_STATES:
                existing_captures.setdefault(_capture_key(row), row)
        if native:
            native_enabled = bool((call("GET", "/capture/native", None) or {}).get("enabled"))

    for pack in packs:
        title = pack.project_title
        if title in existing_projects:
            actions.append({"product": pack.product_id, "type": "project", "result": "exists",
                            "id": existing_projects[title].get("id"), "title": title})
        else:
            try:
                data = call("POST", "/ad-studio/projects", ad_packs.project_body(pack)) or {}
                existing_projects[title] = data
                actions.append({"product": pack.product_id, "type": "project", "result": "created",
                                "id": data.get("id"), "title": title})
            except ApiError as exc:
                actions.append({"product": pack.product_id, "type": "project", "result": "error",
                                "title": title, "error": str(exc)})
        if skip_captures:
            continue
        for body in (ad_packs.capture_body(c) for c in pack.data["captures"]):
            key = ad_packs.capture_match_key(body)
            record = {"product": pack.product_id, "type": "capture", "kind": key[0], "source": key[1]}
            if key[0] == "native_game" and not (native and native_enabled):
                reason = "pass --native" if not native else "native capture is not enabled on this server"
                actions.append(record | {"result": "skipped", "reason": reason})
                continue
            if key in existing_captures:
                actions.append(record | {"result": "exists", "id": existing_captures[key].get("id")})
                continue
            try:
                data = call("POST", "/capture", body) or {}
                existing_captures[key] = data
                actions.append(record | {"result": "created", "id": data.get("id")})
            except ApiError as exc:
                result = "deferred" if exc.status == 429 else "error"
                actions.append(record | {"result": result, "error": str(exc)})
    return actions


def _print_plan(packs: list[ad_packs.AdPack], as_json: bool) -> None:
    plans = [ad_packs.plan(p) for p in packs]
    if as_json:
        print(json.dumps({"dry_run": True, "packs": plans}, indent=2, ensure_ascii=False))
        return
    for pack, item in zip(packs, plans):
        print(f"[{pack.product_id}] project {pack.project_title!r} with {len(item['project']['angles'])} angles")
        for body in item["captures"]:
            print(f"  capture {ad_packs.capture_match_key(body)[0]}: {ad_packs.capture_match_key(body)[1]} "
                  f"formats={','.join(body['formats'])}")
        for ad in item["ads_after_capture"]:
            print(f"  ad {ad['concept']}: mode={ad['body']['mode']} aspect={ad['body']['aspects'][0]} "
                  f"for {ad['platform_hint']} (not auto-published)")
    print(f"dry run: {len(packs)} pack(s) valid; nothing was sent. Use --apply to create drafts.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--packs-dir", type=Path, default=Path(os.getenv("MENIVOR_AD_PACKS_DIR") or DEFAULT_PACKS_DIR))
    parser.add_argument("--only", action="append", default=[], help="product_id to include (repeatable)")
    parser.add_argument("--apply", action="store_true", help="create drafts through the API (default: dry run)")
    parser.add_argument("--api-base", default=os.getenv("MENIVOR_API_BASE") or DEFAULT_API_BASE)
    parser.add_argument("--api-key", default=os.getenv("MENIVOR_API_KEY") or "",
                        help="Menivor API key (x-api-key); prefer the MENIVOR_API_KEY env var")
    parser.add_argument("--native", action="store_true", help="also start native game captures (simulator host)")
    parser.add_argument("--skip-captures", action="store_true", help="only create Ad Studio projects")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        packs = ad_packs.load_dir(args.packs_dir)
    except ad_packs.PackError as exc:
        print(f"invalid ad pack: {exc}", file=sys.stderr)
        return 2
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {p.product_id for p in packs}
        if unknown:
            print(f"unknown product id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        packs = [p for p in packs if p.product_id in wanted]

    if not args.apply:
        _print_plan(packs, args.json)
        return 0
    if not args.api_key:
        print("--apply needs an API key (--api-key or MENIVOR_API_KEY)", file=sys.stderr)
        return 2
    try:
        actions = apply_packs(packs, http_transport(args.api_base, args.api_key),
                              native=args.native, skip_captures=args.skip_captures)
    except ApiError as exc:
        print(f"Menivor API error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"dry_run": False, "actions": actions}, indent=2, ensure_ascii=False))
    else:
        for action in actions:
            detail = action.get("id") or action.get("reason") or action.get("error") or ""
            label = action.get("title") or f"{action.get('kind')} {action.get('source')}"
            print(f"[{action['product']}] {action['type']} {action['result']}: {label} {detail}".rstrip())
    return 1 if any(a["result"] == "error" for a in actions) else 0


if __name__ == "__main__":
    raise SystemExit(main())
