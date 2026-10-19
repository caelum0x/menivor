"""Wave P PM2.0 steward: P2 router includes, optional task modules, OTT flags, one head.

The migration chain of record is ``docs/planning/WAVE-P-MIGRATIONS.md``; the
PM1.0 steward test checks every ``landed`` row and the single Alembic head for
the whole file, so P2 rows are covered as soon as they land.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
API_APP = REPO / "apps" / "api" / "app"

P2_ROUTERS = (
    ("app.domains.film.story8", "story8_router"),
    ("app.services.enhance.router", "enhance_router"),
    ("app.domains.apps_shelf.router", "apps_shelf_router"),
    ("app.domains.ott.router", "ott_router"),
    ("app.services.ott_transcode.router", "ott_transcode_router"),
    ("app.domains.ott.feeds", "ott_feeds_router"),
    ("app.domains.ott_access.router", "ott_access_router"),
)
P2_TASK_MODULES = (
    "app.domains.film.story8_tasks",
    "app.services.enhance.tasks",
    "app.domains.apps_shelf.tasks",
    "app.domains.ott.tasks",
    "app.workers.tasks_ott",
)


def test_router_includes_p2_domains():
    import importlib

    from app.router import build_full_router

    source = (API_APP / "router.py").read_text(encoding="utf-8")
    mounted = {(r.path, tuple(sorted(r.methods))) for r in build_full_router().routes if isinstance(r, APIRoute)}
    for module, name in P2_ROUTERS:
        assert f"router.include_router({name})" in source, name
        sub = importlib.import_module(module).router
        for route in sub.routes:
            if isinstance(route, APIRoute):
                assert (route.path, tuple(sorted(route.methods))) in mounted, route.path


def test_p2_task_modules_are_registered_as_optional():
    source = (API_APP / "workers" / "celery_app.py").read_text(encoding="utf-8")
    start = source.index("_OPTIONAL_TASK_MODULES")
    block = source[start:source.index("\n)", start)]
    for module in P2_TASK_MODULES:
        assert f'"{module}"' in block, module


def test_chain_doc_has_p2_rows_in_order():
    rows = []
    for line in (REPO / "docs" / "planning" / "WAVE-P-MIGRATIONS.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].startswith("PM2."):
            rows.append(cells)
    packages = [r[0] for r in rows]
    assert packages == ["PM2.0", "PM2.1", "PM2.2", "PM2.3", "PM2.4", "PM2.5"], packages
    chained = [r for r in rows if r[1] != "none"]
    assert chained[0][2] == "a4c6e8f0b2d3"
    for previous, row in zip(chained, chained[1:]):
        if row[4] in {"landed", "reserved"} and previous[4] in {"landed", "reserved"}:
            assert row[2] == previous[1], (previous, row)


# --------------------------------------------------------------------------- #
# OTT flags: a master switch plus one per surface, all off by default.
# --------------------------------------------------------------------------- #
def test_every_ott_surface_is_off_by_default(monkeypatch):
    from app.domains.ott import flags

    for name in (flags.MASTER, *flags.SURFACES.values()):
        monkeypatch.delenv(name, raising=False)
    assert flags.snapshot() == {surface: False for surface in flags.SURFACES}


def test_surface_needs_master_and_own_flag():
    from app.domains.ott import flags

    assert not flags.enabled("cms", {"OTT_CMS_LIVE": "1"})
    assert not flags.enabled("cms", {"OTT_ENABLED": "1"})
    assert flags.enabled("cms", {"OTT_ENABLED": "true", "OTT_CMS_LIVE": "on"})
    assert not flags.enabled("storefront", {"OTT_ENABLED": "1", "OTT_CMS_LIVE": "1"})
    with pytest.raises(KeyError):
        flags.enabled("drm", {})


def test_require_dependency_answers_404_until_live(monkeypatch):
    from app.domains.ott import flags

    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(flags.require("feeds"))])
    def probe():
        return {"ok": True}

    client = TestClient(app)
    monkeypatch.delenv("OTT_ENABLED", raising=False)
    assert client.get("/probe").status_code == 404
    monkeypatch.setenv("OTT_ENABLED", "1")
    monkeypatch.setenv("OTT_FEEDS_LIVE", "1")
    assert client.get("/probe").status_code == 200


def test_creator_profile_links_the_channel_behind_the_flag():
    page = (REPO / "apps" / "web" / "app" / "creators" / "[handle]" / "page.tsx").read_text(encoding="utf-8")
    assert "<ChannelLink handle={profile.handle} />" in page
    flags_ts = (REPO / "apps" / "web" / "src" / "features" / "ott-player" / "flags.ts").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_OTT_ENABLED" in flags_ts and "NEXT_PUBLIC_OTT_STOREFRONT_LIVE" in flags_ts


def test_denylist_is_the_wave_p_version():
    import json

    vendored = json.loads((REPO / "policy" / "copy-denylist.json").read_text(encoding="utf-8"))
    assert vendored["version"] == "2026-09-29.3"
