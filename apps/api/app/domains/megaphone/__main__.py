"""Megaphone CLI (run inside the menivor-api container on the box).

    python -m app.domains.megaphone run --bidstage-json - < week.json
    python -m app.domains.megaphone run --only menivor --dry-run
    python -m app.domains.megaphone upload /tmp/footage.mp4
    python -m app.domains.megaphone smoke

Env: ``MENIVOR_MEGAPHONE_API_KEY`` (internal comp account), optional
``MENIVOR_MEGAPHONE_API_BASE``, ``MENIVOR_MEGAPHONE_OXHAN_FOOTAGE`` (comma
separated ``uploads/`` keys), ``MENIVOR_MEGAPHONE_CLERK_USER`` (smoke).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

import requests
from loguru import logger

from app.domains.megaphone import briefs as bf
from app.domains.megaphone import manifest as mf
from app.domains.megaphone.pipeline import DEFAULT_API_BASE, USER_AGENT, ApiClient, MegaphoneError, Publisher, render_brief

BIDSTAGE_PER_WEEK = 2
MIN_CREDITS = 30
TOPUP_CREDITS = 60
_LOC = re.compile(r"<loc>https://bidstage\.app(/tenders/[a-z]{2}/cpv-\d{8})</loc>")


def _api() -> ApiClient:
    key = (os.environ.get("MENIVOR_MEGAPHONE_API_KEY") or "").strip()
    if not key:
        raise SystemExit("MENIVOR_MEGAPHONE_API_KEY is not set")
    return ApiClient(api_key=key, base=(os.environ.get("MENIVOR_MEGAPHONE_API_BASE") or DEFAULT_API_BASE).rstrip("/"))


def bidstage_paths() -> set[str]:
    resp = requests.get("https://bidstage.app/sitemap.xml", timeout=60, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return set(_LOC.findall(resp.text))


def ensure_credits(user_id: str, email: str) -> int:
    """Top up the internal comp account (never a customer: must be in MENIVOR_COMP_EMAILS)."""
    allowed = {e.strip().lower() for e in (os.environ.get("MENIVOR_COMP_EMAILS") or "").split(",") if e.strip()}
    if email.lower() not in allowed:
        raise MegaphoneError(f"{email} is not a comp account; refusing to top up")
    from app.models.db.base import get_session
    from app.models.db.repositories import CreditRepository

    with get_session() as session:
        repo = CreditRepository(session)
        balance = int(repo.balance(user_id))
        if balance < MIN_CREDITS:
            repo.grant(user_id, TOPUP_CREDITS, f"internal:megaphone_topup:{datetime.now(timezone.utc):%Y%m%d}")
            balance += TOPUP_CREDITS
    return balance


def build_briefs(day: Any, rows: list[dict[str, Any]], manifest: dict[str, Any], only: set[str]) -> list[bf.Brief]:
    out: list[bf.Brief] = []
    if "bidstage" in only and rows:
        recent = mf.recent_ids(manifest, "bidstage", limit=12)
        for cand in bf.bidstage_candidates(rows, bidstage_paths(), recent, day)[:BIDSTAGE_PER_WEEK]:
            out.append(bf.bidstage_brief(cand, day))
    if "mail" in only:
        out.append(bf.mail_brief(day))
    footage = [k.strip() for k in (os.environ.get("MENIVOR_MEGAPHONE_OXHAN_FOOTAGE") or "").split(",") if k.strip()]
    if "oxhan" in only and footage:
        out.append(bf.oxhan_brief(day, footage))
    if "menivor" in only:
        out.append(bf.menivor_brief(day))
    return out


def _email(summary: dict[str, Any]) -> None:
    try:
        from app.services import mailer
        from app.services.funnel.weekly import recipient

        lines = [f"Megaphone week {summary['week']}: {len(summary['published'])} published, {len(summary['failed'])} failed.", ""]
        lines += [f"- {p['id']}: {p['video_url']}" for p in summary["published"]]
        lines += [f"- FAILED {f['id']}: {f['error']}" for f in summary["failed"]]
        lines += ["", "Gallery: https://menivor.com/made-with-menivor"]
        mailer.send_email(to=recipient(), subject=f"Megaphone {summary['week']}: {len(summary['published'])} videos",
                          text="\n".join(lines), idempotency_key=f"megaphone-{summary['week']}-{summary['run_at']}",
                          tags=("megaphone",))
    except Exception as exc:  # noqa: BLE001 - the report never fails the run
        logger.warning(f"megaphone: summary email failed: {exc}")


def cmd_run(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    day = now.date()
    only = set(args.only.split(",")) if args.only else set(mf.PRODUCTS)
    rows: list[dict[str, Any]] = []
    if args.bidstage_json:
        raw = sys.stdin.read() if args.bidstage_json == "-" else open(args.bidstage_json, encoding="utf-8").read()
        rows = json.loads(raw.strip() or "[]") or []
    publisher = Publisher()
    manifest = publisher.load_manifest()
    briefs = build_briefs(day, rows, manifest, only)
    if args.dry_run:
        print(json.dumps([b.__dict__ for b in briefs], indent=1, default=list))
        return 0
    api = _api()
    me = api.me()
    logger.info(f"megaphone: credits before top-up {me.get('credits')}, now {ensure_credits(str(me['user_id']), str(me['email']))}")
    outro: dict[str, str] = {}
    published: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for brief in briefs:
        try:
            published.append(render_brief(api, publisher, brief, outro)["entry"])
            manifest = mf.upsert(manifest, published[-1:], datetime.now(timezone.utc))
            publisher.write_manifest(manifest)  # publish as we go: one failure keeps earlier videos
        except Exception as exc:  # noqa: BLE001 - one brief must not stop the week
            logger.error(f"megaphone: {brief.id} failed: {exc}")
            failed.append({"id": brief.id, "error": str(exc)[:300]})
    summary = {"week": bf.week_id(day), "run_at": mf.iso(now), "published": published, "failed": failed}
    _email(summary)
    print(json.dumps({**summary, "published": [p["id"] for p in published]}, indent=1))
    return 0 if published or not briefs else 1


def cmd_upload(args: argparse.Namespace) -> int:
    print(_api().upload(args.path, args.content_type))
    return 0


def _clerk_session_jwt(user_id: str) -> str:
    secret = os.environ["CLERK_SECRET_KEY"]
    issuer = os.environ["CLERK_ISSUER"].rstrip("/")
    headers = {"Authorization": f"Bearer {secret}", "User-Agent": USER_AGENT}
    ticket = requests.post("https://api.clerk.com/v1/sign_in_tokens", headers=headers, timeout=30,
                           json={"user_id": user_id, "expires_in_seconds": 300}).json()["token"]
    resp = requests.post(f"{issuer}/v1/client/sign_ins?_is_native=1", timeout=30,
                         data={"strategy": "ticket", "ticket": ticket},
                         headers={"Origin": "https://menivor.com", "User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.json()["client"]["sessions"][0]["last_active_token"]["jwt"]


def cmd_smoke(_args: argparse.Namespace) -> int:
    """Web sign-in (real Clerk session -> API) and API-key access for the internal account."""
    api = _api()
    checks: dict[str, Any] = {}
    me = api.me()
    checks["api_key_me"] = bool(me.get("user_id"))
    clerk_user = (os.environ.get("MENIVOR_MEGAPHONE_CLERK_USER") or "").strip()
    if clerk_user:
        jwt = _clerk_session_jwt(clerk_user)
        resp = requests.get(f"{api.base}/me", headers={"Authorization": f"Bearer {jwt}", "User-Agent": USER_AGENT}, timeout=30)
        checks["clerk_session_me"] = resp.status_code == 200 and resp.json()["data"]["user_id"] == me["user_id"]
    launch = requests.get(f"{api.base}/launch/status", timeout=30, headers={"User-Agent": USER_AGENT}).json()["data"]
    formats = {f["id"] for f in launch.get("available_formats") or []}
    checks["free_formats"] = {"faceless_free_voice", "dub_video_free_voice"} <= formats
    checks["signup_open"] = bool((launch.get("features") or {}).get("signup"))
    print(json.dumps(checks))
    return 0 if all(checks.values()) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="megaphone")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--bidstage-json", default="")
    run.add_argument("--only", default="")
    run.add_argument("--dry-run", action="store_true")
    up = sub.add_parser("upload")
    up.add_argument("path")
    up.add_argument("--content-type", default="video/mp4")
    sub.add_parser("smoke")
    args = parser.parse_args(argv)
    return {"run": cmd_run, "upload": cmd_upload, "smoke": cmd_smoke}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
