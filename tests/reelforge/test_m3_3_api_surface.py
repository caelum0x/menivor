"""M3.3: production API allowlist, staff-only rest, frozen money routes, free watermark."""

from __future__ import annotations

import json

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core import api_surface as surf

# Public paths the clients reference today (generated audit). The WP3.3 target
# is 60; it needs client-side cuts first (see docs/api/ROUTE-AUDIT.md). This cap
# stops the public surface from growing past today's audit. Wave E M-1 (H1)
# adds the three product-contract paths: quote, preset quote and keep; M-6
# adds the partner launch-video path the /launch-video page calls.
# Wave P PM1.2 (MH2) adds the five preset shelf paths the /presets-gallery
# page calls (shelf, tile, plan, runs, run timing). PM1.3 (MH3) adds the six
# gallery paths the /gallery page calls (feed, wall, item, recreate, remixes,
# remix status); the wall approval stays staff-only. PM1.4 (MH4) adds the ten
# My characters and brands paths the presets page calls (list, original,
# consent phrase, real face, training quote and start, identity scores, brand
# kits, product shots, and the narrator roster the page reads). PM2.1 (MH5,
# MH7) adds the seven paths the /story and /enhance pages call (story plan,
# start and progress; image upscale, video quote, video start, progress).
# PM2.2 (MH8, MH6) adds the nine paths the /apps page calls (shelf, quote, plan,
# run, run status; scenes list, quote, run, run status - the scene paths answer
# 404 until PRESENTER_LIVE is on). PM2.3 (MV1) adds the six channel-studio
# paths /studio-ott calls (studio, publish-all, channel, title edit, publish,
# unpublish); they answer 404 until OTT_ENABLED and OTT_CMS_LIVE are on.
# PM2.4 (MV2, MV3) adds the upload paths the studio calls (start, parts,
# complete, package) and the six node paths the transcode nodes call with a
# node token (heartbeat, claim, progress, upload URLs, complete, fail); all
# 404 until their OTT flags are on. PM2.5 (MV4, MV5) adds the thirteen viewer
# paths: storefront, title, embed, custom-domain lookup and play (web pages),
# plus the stream, key, feed, feed-item and oEmbed paths players, feed readers
# and podcast apps follow; every one 404s until its OTT surface flag is on.
# PM3.0 (MH9) adds the weekly drop read the presets page calls (GET
# /presets/drops/latest; empty until a drop is released). PM3.1 (MV6, MV7)
# adds the five channel-viewer paths the storefront and player call (session,
# me, sign-out, continue, progress) and the two studio plan paths (plan,
# overage); all 404 until OTT_VIEWERS_LIVE or OTT_PLANS_LIVE. PM3.2 (MV13,
# MV14) adds thirteen: studio sales (commerce, connect, offers, stop), the
# public offers list, viewer checkout and purchases, studio ads (list and
# create, rules, stop), the VAST read, plus the Mint webhook and the signed
# VAST tracker as named server callers; all 404 until OTT_COMMERCE_LIVE or
# OTT_ADS_LIVE. PM3.3 (MV9) adds the three TV sign-in paths the TV app and
# the phone page call (code, approve, poll); 404 until OTT_TV_LIVE. PM3.4
# (MV10, MV11, MV15) adds eighteen: studio live (list and create, key, chat
# moderation read, rules, hide, ban), viewer live (live now, watch, latency,
# chat read and post), studio linear, now-and-next, plus the MediaMTX hooks,
# the FAST engine item feed and the XMLTV guide as named server callers; all
# 404 until OTT_LIVE_LIVE, OTT_CHAT_LIVE or OTT_FAST_LIVE. PM3.5 (MV12, MV16,
# MV19) adds eight: studio analytics, team (list and add, remove), the AI
# panel (run and read), public chapters, search and ask-this-video, plus the
# player beacon route as a named caller; all 404 until OTT_ANALYTICS_LIVE,
# OTT_AI_LIVE or OTT_DISCOVERY_LIVE. Wave Q QM1.3-QM1.5 add eight: studio
# coupons (list and create, stop) and sales per title, related titles on the
# watch page, and the channel viewer's list (read, add and remove), stars
# (read, rate, take back) and alert opt-in (in and out); all 404 until
# OTT_COMMERCE_LIVE, OTT_DISCOVERY_LIVE or OTT_VIEWERS_LIVE. Autopost
# (multi-account publishing) adds fourteen: providers, accounts (list, pace,
# disconnect, TikTok creator info), connect (authorize, callback), batches
# (list, preview, create, read, cancel), the queue (list, cancel, retry), plus
# the signed TikTok status webhook as a named server caller. The "Very ___
# Time" template adds two: plan (price and guard-rail, nothing charged) and
# start (the story8 job; progress reuses GET /film/story8/{job_id}). Very ___
# Time v2 adds one: voice takes (rate-limited, guard-railed before any voice call).
# Settings > Integrations adds nineteen: the overview, ad-platform connect (sign-in,
# key, callback, disconnect), Brand-space assignment, report refresh, the Ads agent
# (ask, propose, proposals, approve, reject), Slack (install, approvers,
# disconnect) and product sources (Shopify, Medusa, CSV, re-sync). The three Slack-signed
# callbacks are named server callers hidden from the schema.
# Ad Clone adds six: products, brief, plan, render (dry run), render approve
# (credits held, Idempotency-Key, 403 until ADCLONE_PAID_RENDER) and render
# progress; all 403 until ADCLONE_ENABLED.
# The Brand Agent adds nineteen /agent paths: overview, sessions (list, create,
# read, messages, chips, stream), Brain (read, edit, seen), actions (list,
# approve, reject), routines (list/create, change/delete), inspirations, skills,
# folders, library and connectors; every spend or publish waits for approve.
# Wave 2 (2026-10-06) adds twenty-seven: review queue (list, decide), competitor
# tracker (brands, ads, refresh, clone, alerts dismiss), ad fatigue (report,
# variations), AI actors (list/create, preset use, face, face use, voice design,
# voice lock, shot plan), studio renders (list, submit), translate (options,
# plan), workflows (list/create, read/save/delete, run, schedule) and the MCP
# connector settings (connector, tokens, revoke). The hosted /mcp transport is a
# named server caller hidden from the schema. Every spend waits for an approval.
# The 2026-10-06 audit fix reads template paths (``${encodeURIComponent(id)}``)
# that the old pattern skipped: 143 more paths that existing screens already
# call (job share/retry/exports, workspaces, notifications, film, design,
# marketplace, characters, billing ...). Each still requires its own auth
# (tests/reelforge/test_api_surface_auth.py).
# 2026-10-08: +5 capture paths (detect, native, retry, cancel, ads) that the
# web Capture screen already called but built from a shared prefix the audit
# could not read, so they answered 404 in production.
# 2026-10-09: +7 Content Month paths (website -> month of posts -> swipe -> render, video retry).
# 2026-10-14: +1 public, unauthenticated App Store/Play audit path (Menivor Growth phase 1
# lead magnet; same paste-link box the landing hero already uses, see app/domains/appaudit).
# 2026-10-15: +6 Phase 3 "Connect your store" paths (app/domains/store_connect: connect/
# disconnect App Store Connect + Play, list connections, apps+version+rating for each).
# 2026-10-15: +3 Menivor Growth phase 2 keyword-tracker paths (app/domains/keyword_tracker:
# list/add, delete, manual refresh — the daily App Store rank tracker).
# 2026-10-15: +10 Menivor Growth SEO paths (app/domains/seo: connect/disconnect OpenSEO,
# overview, run/read a site audit, keyword research read+write, rank-tracker keywords
# add/remove/refresh) and +1 ads campaign-draft path (POST .../campaigns/draft, always PAUSED).
# 2026-10-15: +8 Launch Kit paths (app/domains/launch_kit: platforms list/status, pain-point
# search/drafts/draft-status, backlinks, checklist read/mark-step) now that the new web
# /launch-kit page gives them a real first-party caller.
PUBLIC_PATH_CAP = 612


@pytest.fixture(scope="module")
def full_router():
    from app.router import build_full_router

    return build_full_router()


def _schema_paths(router: APIRouter) -> set[str]:
    app = FastAPI()
    app.include_router(router)
    return set(app.openapi()["paths"])


def test_default_mode_follows_launch_mode(monkeypatch):
    import app.core.launch.policy as lp

    monkeypatch.delenv(surf.SURFACE_ENV, raising=False)
    monkeypatch.setattr(lp, "launch_mode", lambda: "internal_pilot")
    assert surf.surface_mode() == surf.FULL
    monkeypatch.setattr(lp, "launch_mode", lambda: "public")
    assert surf.surface_mode() == surf.ALLOWLIST
    monkeypatch.setenv(surf.SURFACE_ENV, "full")
    assert surf.surface_mode() == surf.FULL


def test_full_mode_returns_the_router_unchanged(full_router):
    assert surf.apply_surface(full_router, surf.FULL) is full_router


def test_allowlist_mode_public_openapi(full_router):
    routed = surf.apply_surface(full_router, surf.ALLOWLIST)
    paths = _schema_paths(routed)
    assert len(paths) <= PUBLIC_PATH_CAP
    assert len(paths) < len(_schema_paths(full_router))
    for bad in ("/api/v1/wallet/transfers", "/api/v1/admin/impersonate",
                "/api/v1/billing/webhook/stripe", "/api/v1/billing/webhook/paddle",
                "/api/v1/billing/webhook/polar", "/api/v1/billing/webhook/iyzico"):
        assert bad not in paths
    # Core client flows stay public.
    for good in ("/api/v1/jobs", "/api/v1/me", "/api/v1/billing/plans", "/api/v1/pilot/capabilities"):
        assert good in paths, good


def test_frozen_routes_are_not_mounted_and_admin_is_staff_only(full_router):
    routed = surf.apply_surface(full_router, surf.ALLOWLIST)
    mounted = {r.path: r for r in routed.routes if isinstance(r, APIRoute)}
    assert "/api/v1/wallet/transfers" not in mounted
    assert "/api/v1/wallet/transfer-challenges" not in mounted
    assert "/api/v1/billing/webhook/polar" not in mounted
    imp = mounted["/api/v1/admin/impersonate"]
    assert imp.include_in_schema is False
    assert any(getattr(d, "dependency", None) is surf.require_staff for d in imp.dependencies)
    # Nothing else disappears: every non-frozen route is still mounted.
    full_paths = {r.path for r in full_router.routes if isinstance(r, APIRoute)}
    assert {p for p in full_paths if not surf.is_frozen(p)} <= set(mounted)


def test_allowlist_has_no_stale_entries(full_router):
    mounted = {
        f"{m} {r.path}" for r in full_router.routes if isinstance(r, APIRoute) for m in r.methods or ()
    }
    stale = sorted(surf.load_allowlist() - mounted)
    assert stale == [], "re-run apps/api/tools/ops/api_surface_audit.py"


def test_hidden_route_is_404_for_users_and_served_for_staff(monkeypatch):
    toy = APIRouter()

    @toy.get("/api/v1/open")
    def open_route():
        return {"ok": "open"}

    @toy.get("/api/v1/tool")
    def tool_route():
        return {"ok": "tool"}

    @toy.post("/api/v1/wallet/transfers")
    def send():
        return {"sent": True}

    app = FastAPI()
    app.include_router(surf.apply_surface(toy, surf.ALLOWLIST, frozenset({"GET /api/v1/open"})))
    client = TestClient(app)
    monkeypatch.setattr(surf, "_is_staff", lambda request: False)
    assert client.get("/api/v1/open").json() == {"ok": "open"}
    assert client.get("/api/v1/tool").status_code == 404
    assert client.post("/api/v1/wallet/transfers").status_code in (404, 405)
    monkeypatch.setattr(surf, "_is_staff", lambda request: True)
    assert client.get("/api/v1/tool").json() == {"ok": "tool"}
    assert client.post("/api/v1/wallet/transfers").status_code in (404, 405)  # frozen for everyone
    assert set(app.openapi()["paths"]) == {"/api/v1/open"}


def test_audit_regenerates_the_committed_allowlist():
    import importlib.util
    from pathlib import Path

    tool = Path(surf.__file__).resolve().parents[2] / "tools" / "ops" / "api_surface_audit.py"
    spec = importlib.util.spec_from_file_location("api_surface_audit", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    routes = mod.mounted_routes()
    live = [(m, p) for m, p in routes if not surf.is_frozen(p) and not surf.is_staff_only(p)]
    kept, _hidden = mod.audit(live)
    fresh = sorted({f"{r['method']} {r['path']}" for r in kept})
    committed = json.loads(surf.ALLOWLIST_FILE.read_text(encoding="utf-8"))["routes"]
    assert fresh == committed, "client calls changed: re-run apps/api/tools/ops/api_surface_audit.py"


def test_normalise_matches_client_templates():
    import importlib.util
    from pathlib import Path

    tool = Path(surf.__file__).resolve().parents[2] / "tools" / "ops" / "api_surface_audit.py"
    spec = importlib.util.spec_from_file_location("api_surface_audit_n", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.normalise("/jobs/${encodeURIComponent(id)}/exports?x=1") == "/jobs/{}/exports"
    assert mod.normalise("/api/v1/jobs/{job_id}/exports") == "/jobs/{}/exports"


# --------------------------------------------------------------------------- #
# Wallet P2P freeze (flag only)
# --------------------------------------------------------------------------- #
def test_p2p_flag_matrix(monkeypatch):
    import app.core.launch.policy as lp
    from app.domains.wallet.policy import p2p_transfers_enabled

    assert p2p_transfers_enabled({"MENIVOR_WALLET_P2P_TRANSFERS": "off"}) is False
    assert p2p_transfers_enabled({"MENIVOR_WALLET_P2P_TRANSFERS": "on"}) is True
    monkeypatch.setattr(lp, "launch_mode", lambda: "public")
    assert p2p_transfers_enabled({}) is False
    monkeypatch.setattr(lp, "launch_mode", lambda: "internal_pilot")
    assert p2p_transfers_enabled({}) is True


def test_transfer_refused_before_any_money_moves_when_frozen(monkeypatch):
    from app.domains.wallet import service as ws

    monkeypatch.setenv("MENIVOR_WALLET_P2P_TRANSFERS", "off")
    svc = ws.WalletService.__new__(ws.WalletService)  # no session: the gate must fire first
    with pytest.raises(ws.WalletError) as exc:
        svc.transfer("u1", recipient_handle="bob", amount_micros=1_000_000, idempotency_key="k" * 16)
    assert exc.value.status_code == 403
    with pytest.raises(ws.WalletError):
        svc.create_transfer_challenge(
            "u1", source_account_id="a", recipient_handle="bob", amount_micros=1, idempotency_key="k" * 16,
        )


# --------------------------------------------------------------------------- #
# "Made with Menivor" on free exports
# --------------------------------------------------------------------------- #
def test_free_watermark_text_flag():
    from app.services.share import FREE_WATERMARK_TEXT, free_watermark_text

    assert FREE_WATERMARK_TEXT == "Made with Menivor"
    assert free_watermark_text({}) == "Made with Menivor"
    assert free_watermark_text({"MENIVOR_FREE_WATERMARK": "off"}) == ""


def _fake_ffmpeg(monkeypatch, tmp_path, *, drawtext: bool):
    from app.services import preview

    src = tmp_path / "in.mp4"
    src.write_bytes(b"x" * 64)
    calls = []

    def run(cmd):
        calls.append(cmd)
        with open(cmd[-1], "wb") as fh:
            fh.write(b"mp4")

    monkeypatch.setattr(preview, "_run_ffmpeg", run)
    monkeypatch.setattr(preview, "_validate_source", lambda p: None)
    monkeypatch.setattr(preview, "_has_drawtext", lambda: drawtext)
    return preview, str(src), calls


def test_preview_burns_the_watermark_when_drawtext_exists(monkeypatch, tmp_path):
    preview, src, calls = _fake_ffmpeg(monkeypatch, tmp_path, drawtext=True)
    monkeypatch.delenv("MENIVOR_FREE_WATERMARK", raising=False)
    out = str(tmp_path / "p.mp4")
    preview.generate_preview_clip(src, out, duration_s=3)
    assert len(calls) == 1 and "copy" not in calls[0]  # re-encode only
    vf = calls[0][calls[0].index("-vf") + 1]
    assert vf.startswith("drawtext=textfile=")
    assert open(f"{out}.watermark.txt", encoding="utf-8").read() == "Made with Menivor"


def test_preview_without_drawtext_or_flag_keeps_the_fast_copy(monkeypatch, tmp_path):
    preview, src, calls = _fake_ffmpeg(monkeypatch, tmp_path, drawtext=False)
    preview.generate_preview_clip(src, str(tmp_path / "a.mp4"), duration_s=3)
    assert "copy" in calls[0] and "-vf" not in calls[0]
    preview, src, calls = _fake_ffmpeg(monkeypatch, tmp_path, drawtext=True)
    preview.generate_preview_clip(src, str(tmp_path / "b.mp4"), duration_s=3, watermark_text="")
    assert "-vf" not in calls[0]
