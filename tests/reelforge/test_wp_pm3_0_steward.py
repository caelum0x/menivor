"""Wave P PM3.0: the P3 steward set and MH9 growth loops.

1. Registry and migration lines for PM3.1-PM3.5 (router includes, optional
   task modules, OTT P3 surface flags all off, the P3 chain rows).
2. A weekly drop publishes at least 3 presets with preview loops, inside the
   promo budget; fewer than 3 publishes nothing; a second run is a no-op.
3. MCP ``presets.list`` and ``presets.recreate`` pass contract tests and are
   hidden and refused while ``MCP_PRESETS_LIVE`` (MG4) is off.
4. The dogfood Earn campaign stays off until 10 paying users (OD4) and inside
   the $100 monthly cap.
"""

from __future__ import annotations

import hashlib
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import app.domains.compliance.takedown  # noqa: F401  (registers takedown_reports)
import app.domains.gallery.models  # noqa: F401  (registers gallery_items)
import app.models.db.clipmarket  # noqa: F401
import app.models.db.creator_subscription  # noqa: F401
import app.models.db.trends  # noqa: F401
import app.services.loops.preset_drop  # noqa: F401  (registers preset_drops)
from app.models.db.base import Base

REPO = Path(__file__).resolve().parents[2]
API_APP = REPO / "apps" / "api" / "app"

P3_ROUTERS = (
    ("app.services.loops.preset_drop", "preset_drop_router"),
    ("app.domains.ott_viewers.router", "ott_viewers_router"),
    ("app.services.billing.ott_plans", "ott_plans_router"),
    ("app.domains.ott_commerce.router", "ott_commerce_router"),
    ("app.domains.ott_ads.router", "ott_ads_router"),
    ("app.domains.ott_live.router", "ott_live_router"),
    ("app.domains.ott_linear.router", "ott_linear_router"),
    ("app.domains.ott_analytics.router", "ott_analytics_router"),
    ("app.domains.ott_ai.router", "ott_ai_router"),
    ("app.domains.ott_discovery.router", "ott_discovery_router"),
)
P3_TASK_MODULES = (
    "app.services.loops.preset_drop_tasks",
    "app.services.billing.ott_usage_tasks",
    "app.domains.ott_commerce.tasks",
    "app.domains.ott_live.tasks",
    "app.domains.ott_analytics.tasks",
    "app.domains.ott_ai.tasks",
    "app.domains.ott_discovery.tasks",
)
P3_SURFACES = ("viewers", "plans", "commerce", "ads", "tv", "live", "chat", "fast", "analytics", "ai", "discovery")


# --------------------------------------------------------------------------- #
# 1. Registry lines
# --------------------------------------------------------------------------- #
def test_router_includes_p3_domains():
    from app.router import build_full_router

    source = (API_APP / "router.py").read_text(encoding="utf-8")
    mounted = {(r.path, tuple(sorted(r.methods))) for r in build_full_router().routes if isinstance(r, APIRoute)}
    for module, name in P3_ROUTERS:
        assert f"router.include_router({name})" in source, name
        for route in importlib.import_module(module).router.routes:
            if isinstance(route, APIRoute):
                assert (route.path, tuple(sorted(route.methods))) in mounted, route.path


def test_p3_task_modules_are_registered_as_optional():
    source = (API_APP / "workers" / "celery_app.py").read_text(encoding="utf-8")
    start = source.index("_OPTIONAL_TASK_MODULES")
    block = source[start:source.index("\n)", start)]
    for module in P3_TASK_MODULES:
        assert f'"{module}"' in block, module


def test_preset_drop_beat_runs_mondays():
    from app.services.loops import preset_drop_tasks

    entry = preset_drop_tasks.BEAT_SCHEDULE["menivor-preset-weekly-drop"]
    assert entry["task"] == preset_drop_tasks.DROP_TASK
    assert entry["schedule"].day_of_week == {1}


def test_p3_surfaces_are_off_by_default(monkeypatch):
    from app.domains.ott import flags

    for surface in P3_SURFACES:
        assert surface in flags.SURFACES
        monkeypatch.delenv(flags.SURFACES[surface], raising=False)
    monkeypatch.delenv(flags.MASTER, raising=False)
    assert not any(flags.enabled(s) for s in P3_SURFACES)
    assert flags.enabled("live", {"OTT_ENABLED": "1", "OTT_LIVE_LIVE": "1"})


def test_chain_doc_has_p3_rows_in_order():
    rows = []
    for line in (REPO / "docs" / "planning" / "WAVE-P-MIGRATIONS.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].startswith("PM3."):
            rows.append(cells)
    assert [r[0] for r in rows] == ["PM3.0", "PM3.1", "PM3.2", "PM3.3", "PM3.4", "PM3.5"]
    chained = [r for r in rows if r[1] != "none"]
    assert chained[0][2] == "c2e4a6b8d0f3"
    for previous, row in zip(chained, chained[1:]):
        assert row[2] == previous[1], (previous, row)


# --------------------------------------------------------------------------- #
# 2. Weekly drop
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db():
    from app.services.loops import preset_drop

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    preset_drop.reset_cache()
    yield factory
    preset_drop.reset_cache()


def _entry(pid: str, week: str | None, **extra) -> dict:
    entry = {"loop": f"presets/{pid}.mp4", "poster": f"presets/{pid}.jpg", "status": "published", "spend_usd": 0.0}
    if week:
        entry["drop"] = week
    entry.update(extra)
    return entry


WEEK = "2026-W41"


def _manifest(**over) -> dict:
    manifest = {
        "crash-zoom": _entry("crash-zoom", WEEK),
        "orbit": _entry("orbit", WEEK),
        "whip-pan": _entry("whip-pan", WEEK),
        "melt-away": _entry("melt-away", WEEK, funded_by="owner-promo-M2", spend_usd=4.5),
        "dreamy-push": _entry("dreamy-push", None),
    }
    manifest.update(over)
    return manifest


def test_drop_publishes_three_or_more_ready_presets(db):
    from app.services.loops import preset_drop

    with db() as s:
        result = preset_drop.publish_week(s, WEEK, manifest=_manifest())
        s.commit()
    assert result["published"] is True
    assert sorted(result["preset_ids"]) == ["crash-zoom", "melt-away", "orbit", "whip-pan"]
    assert result["spend_usd"] == 4.5
    with db() as s:
        again = preset_drop.publish_week(s, WEEK, manifest=_manifest())
    assert again["already"] is True


def test_drop_waits_with_fewer_than_three_ready(db):
    from app.services.loops import preset_drop

    manifest = _manifest(orbit=_entry("orbit", WEEK, loop=""),
                         **{"melt-away": _entry("melt-away", WEEK)},  # model preview not funded
                         )
    with db() as s:
        result = preset_drop.publish_week(s, WEEK, manifest=manifest)
    assert result["published"] is False
    assert "2 of 3" in result["reason"]
    assert result["waiting"] == {"orbit": "no preview loop yet",
                                 "melt-away": "model preview not funded from the promo budget"}


def test_drop_refuses_above_the_weekly_promo_cap(db, monkeypatch):
    from app.services.loops import preset_drop

    monkeypatch.setenv(preset_drop.BUDGET_ENV, "3")
    with db() as s:
        result = preset_drop.publish_week(s, WEEK, manifest=_manifest())
    assert result["published"] is False and "promo cap" in result["reason"]


def test_drop_presets_stay_hidden_until_released(db, monkeypatch):
    from app.domains.presets_hub import catalog, previews
    from app.services.loops import preset_drop

    preset = catalog.get("orbit")
    entry = _entry("orbit", WEEK)
    released: set[str] = set()
    monkeypatch.setattr(preset_drop, "_load_released", lambda: frozenset(released))
    assert previews.visible(preset, entry) is False
    released.add("orbit")
    preset_drop.reset_cache()
    assert previews.visible(preset, entry) is True
    # A shelf entry with no drop is unaffected.
    assert previews.visible(catalog.get("dreamy-push"), _entry("dreamy-push", None)) is True


def test_released_read_failure_hides_drop_presets(monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.services.loops import preset_drop

    def broken():
        raise OperationalError("select", {}, Exception("down"))

    preset_drop.reset_cache()
    assert preset_drop.released("orbit", loader=broken) is False
    preset_drop.reset_cache()


def test_latest_drop_route_serves_tiles(db, monkeypatch):
    import app.controllers.v1.jobs as jobs_mod
    from contextlib import contextmanager

    from app.domains.presets_hub import previews
    from app.services.loops import preset_drop

    manifest = _manifest()

    @contextmanager
    def session():
        s = db()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(preset_drop, "get_session", session)
    monkeypatch.setattr(jobs_mod, "_require_db", lambda _rid: None)
    monkeypatch.setattr(previews, "load_manifest", lambda: manifest)
    app = FastAPI()
    app.include_router(preset_drop.router)
    client = TestClient(app)
    first = client.get("/api/v1/presets/drops/latest")
    assert first.json().get("data") == {"week": None, "presets": []}, first.text
    with db() as s:
        preset_drop.publish_week(s, WEEK, manifest=manifest)
        s.commit()
    preset_drop.reset_cache()
    monkeypatch.setattr(preset_drop, "_load_released", lambda: frozenset({"crash-zoom", "orbit", "whip-pan",
                                                                          "melt-away"}))
    body = client.get("/api/v1/presets/drops/latest")
    assert body.headers["cache-control"].startswith("public")
    data = body.json()["data"]
    assert data["week"] == WEEK
    ids = [t["id"] for t in data["presets"]]
    assert sorted(ids) == ["crash-zoom", "melt-away", "orbit", "whip-pan"]
    assert all(t["preview"]["loop_url"].endswith(".mp4") for t in data["presets"])


def test_trends_brief_lists_recommended_formats(db):
    from app.models.db.trends import TrendObservation
    from app.services.loops import preset_drop

    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with db() as s:
        s.add_all([
            TrendObservation(trend_id="t1", kind="format", label="Split-screen reveal", opportunity_bps=7000,
                             recommend=True, observed_at=now - timedelta(days=2)),
            TrendObservation(trend_id="t2", kind="format", label="Old", opportunity_bps=9000, recommend=True,
                             observed_at=now - timedelta(days=40)),
            TrendObservation(trend_id="t3", kind="sound", label="Not picked", opportunity_bps=9500,
                             recommend=False, observed_at=now),
        ])
        s.commit()
        assert [b["label"] for b in preset_drop.brief(s, now=now)] == ["Split-screen reveal"]


def test_iso_week_format():
    from app.services.loops import preset_drop

    assert preset_drop.iso_week(datetime(2026, 10, 5, tzinfo=timezone.utc)) == "2026-W41"


# --------------------------------------------------------------------------- #
# 3. MCP presets tools (behind MG4)
# --------------------------------------------------------------------------- #
def test_mcp_presets_tools_hidden_and_refused_while_mg4_is_off(monkeypatch):
    from app.mcp import tools

    monkeypatch.delenv("MCP_PRESETS_LIVE", raising=False)
    names = {t["name"] for t in tools.tool_specs()}
    assert "presets.list" not in names and "presets.recreate" not in names
    with pytest.raises(tools.MCPToolError, match="unknown tool"):
        tools.dispatch(None, "u1", "presets.list", {})


def test_mcp_presets_list_contract(monkeypatch):
    from app.domains.presets_hub import previews
    from app.mcp import tools

    monkeypatch.setenv("MCP_PRESETS_LIVE", "1")
    monkeypatch.setattr(previews, "load_manifest", lambda: {"crash-zoom": _entry("crash-zoom", None),
                                                           "melt-away": _entry("melt-away", None,
                                                                               funded_by="owner-promo-M1")})
    specs = {t["name"]: t for t in tools.tool_specs()}
    assert specs["presets.list"]["input_schema"]["type"] == "object"
    assert specs["presets.recreate"]["input_schema"]["required"] == ["subject"]
    result = tools.dispatch(None, "u1", "presets.list", {})
    assert {t["id"] for t in result["presets"]} == {"crash-zoom", "melt-away"}
    for tile in result["presets"]:
        assert set(tile) >= {"id", "name", "blurb", "kind", "credit_kind", "preview", "create_url"}
        assert "prompt_template" not in tile and "camera_motion" not in tile
    only_filter = tools.dispatch(None, "u1", "presets.list", {"kind": "filter"})
    assert [t["id"] for t in only_filter["presets"]] == ["crash-zoom"]
    with pytest.raises(tools.MCPToolError):
        tools.dispatch(None, "u1", "presets.list", {"kind": "other"})


def test_mcp_presets_recreate_contract(monkeypatch):
    from app.domains.presets_hub import previews
    from app.mcp import tools

    monkeypatch.setenv("MCP_PRESETS_LIVE", "1")
    monkeypatch.setattr(previews, "load_manifest", lambda: {"crash-zoom": _entry("crash-zoom", None)})
    plan = tools.dispatch(None, "u1", "presets.recreate", {"preset_id": "crash-zoom", "subject": "espresso"})
    assert plan["route"] == "jobs" and plan["preset_id"] == "crash-zoom"
    assert plan["body"]["params"]["camera_motion"] == "crash_zoom_in"
    with pytest.raises(tools.MCPToolError, match="preset not found"):
        tools.dispatch(None, "u1", "presets.recreate", {"preset_id": "orbit", "subject": "x"})
    with pytest.raises(tools.MCPToolError, match="exactly one"):
        tools.dispatch(None, "u1", "presets.recreate", {"subject": "x"})


def test_mcp_presets_recreate_gallery_item(db, monkeypatch):
    from app.domains.gallery.models import GalleryItem
    from app.domains.presets_hub import previews
    from app.mcp import tools
    from app.models.db.models import Job, User

    monkeypatch.setenv("MCP_PRESETS_LIVE", "1")
    monkeypatch.setattr(previews, "load_manifest", lambda: {"crash-zoom": _entry("crash-zoom", None)})
    with db() as s:
        user = User(email="a@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest())
        s.add(user)
        s.flush()
        job = Job(user_id=user.id, state=1, params={})
        s.add(job)
        s.flush()
        item = GalleryItem(user_id=user.id, job_id=job.id, preset_id="shelf:crash-zoom", title="Espresso")
        s.add(item)
        s.commit()
        plan = tools.dispatch(s, user.id, "presets.recreate", {"item_id": item.id, "subject": "tea"})
    assert plan["item_id"] == item.id and plan["route"] == "jobs"
    with db() as s, pytest.raises(tools.MCPToolError, match="not found"):
        tools.dispatch(s, "u1", "presets.recreate", {"item_id": "missing", "subject": "tea"})


# --------------------------------------------------------------------------- #
# 4. Dogfood Earn campaign gate (OD4)
# --------------------------------------------------------------------------- #
def _paying(s, n: int) -> str:
    from app.models.db.creator_subscription import CreatorSubscription
    from app.models.db.models import User

    brand = None
    for i in range(n):
        user = User(email=f"p{i}@example.com", api_key_hash=hashlib.sha256(f"k{i}".encode()).hexdigest())
        s.add(user)
        s.flush()
        s.add(CreatorSubscription(user_id=user.id, plan_key="creator", provider="dodo", status="active"))
        brand = brand or user.id
    s.flush()
    return brand


def test_earn_campaign_stays_off_below_ten_paying_users(db):
    from app.services.loops import dogfood_earn

    with db() as s:
        brand = _paying(s, 9)
        gate = dogfood_earn.status(s, {"MENIVOR_DOGFOOD_EARN": "1"})
        assert gate["paying_users"] == 9 and gate["eligible"] is False
        with pytest.raises(dogfood_earn.EarnRefused, match="10 paying users"):
            dogfood_earn.start(s, brand_id=brand, budget_usd=50, cpm_usd=2.0, env={"MENIVOR_DOGFOOD_EARN": "1"})


def test_earn_campaign_needs_the_switch_and_keeps_the_monthly_cap(db, monkeypatch):
    from app.domains.clipmarket import service as clipmarket
    from app.services.loops import dogfood_earn

    created = []
    monkeypatch.setattr(clipmarket, "_escrow_budget", lambda session, row: created.append(row.budget_micros))
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with db() as s:
        brand = _paying(s, 10)
        with pytest.raises(dogfood_earn.EarnRefused, match="off"):
            dogfood_earn.start(s, brand_id=brand, budget_usd=50, cpm_usd=2.0, env={}, now=now)
        on = {"MENIVOR_DOGFOOD_EARN": "1"}
        row = dogfood_earn.start(s, brand_id=brand, budget_usd=60, cpm_usd=2.0, env=on, now=now)
        assert row.title == "Menivor dogfood 2026-10" and row.budget_micros == 60_000_000
        with pytest.raises(dogfood_earn.EarnRefused, match="monthly cap"):
            dogfood_earn.start(s, brand_id=brand, budget_usd=50, cpm_usd=2.0, env=on, now=now)
        dogfood_earn.start(s, brand_id=brand, budget_usd=40, cpm_usd=2.0, env=on, now=now)
    assert created == [60_000_000, 40_000_000]
