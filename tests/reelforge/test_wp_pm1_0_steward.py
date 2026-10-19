"""Wave P PM1.0 steward: router includes, beat module lines, one Alembic head.

The migration table in ``docs/planning/WAVE-P-MIGRATIONS.md`` is the chain of
record: every ``landed`` row must exist in ``migrations/versions`` with the
stated ``down_revision``, and the graph must have exactly one head.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

from fastapi.routing import APIRoute

REPO = Path(__file__).resolve().parents[2]
VERSIONS = REPO / "migrations" / "versions"
CHAIN_DOC = REPO / "docs" / "planning" / "WAVE-P-MIGRATIONS.md"

_REV = re.compile(r"^revision[^=]*=\s*['\"]([^'\"]+)['\"]", re.M)
_DOWN = re.compile(r"^down_revision[^=]*=\s*(.+)$", re.M)


def _graph() -> dict[str, tuple[str, list[str]]]:
    graph: dict[str, tuple[str, list[str]]] = {}
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = _REV.search(text)
        if not rev:
            continue
        down = _DOWN.search(text)
        downs = re.findall(r"['\"]([^'\"]+)['\"]", down.group(1)) if down else []
        graph[rev.group(1)] = (path.name, downs)
    return graph


def _chain_rows() -> list[dict[str, str]]:
    rows = []
    for line in CHAIN_DOC.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].startswith("PM"):
            rows.append(dict(zip(("package", "revision", "down", "file", "status"), cells)))
    return rows


def test_alembic_graph_has_one_head():
    graph = _graph()
    referenced = {d for _, downs in graph.values() for d in downs}
    heads = sorted(r for r in graph if r not in referenced)
    assert len(heads) == 1, heads


def test_landed_rows_match_the_versions_folder():
    graph = _graph()
    rows = _chain_rows()
    assert rows, "WAVE-P-MIGRATIONS.md has no package rows"
    for row in rows:
        if row["status"] != "landed":
            continue
        assert row["revision"] in graph, row
        name, downs = graph[row["revision"]]
        assert name == row["file"], (name, row)
        assert downs == [row["down"]], (downs, row)


def test_router_includes_wave_p_domains():
    from app.domains.characters.hub import router as hub
    from app.domains.gallery.router import router as gallery
    from app.domains.presets_hub.router import router as presets
    from app.router import build_full_router

    source = (REPO / "apps" / "api" / "app" / "router.py").read_text(encoding="utf-8")
    for name in ("presets_hub_router", "gallery_router", "characters_hub_router"):
        assert f"router.include_router({name})" in source, name
    mounted = {r.path for r in build_full_router().routes if isinstance(r, APIRoute)}
    for sub in (presets, gallery, hub):
        for route in sub.routes:
            if isinstance(route, APIRoute):
                assert route.path in mounted, route.path


def test_railyard_task_module_is_registered_as_optional():
    source = (REPO / "apps" / "api" / "app" / "workers" / "celery_app.py").read_text(encoding="utf-8")
    assert '"app.integrations.railyard.tasks"' in source


# Public Wave P routes a signed-out client may call under the production
# allowlist (each package adds its own); staff routes stay 404.
WAVE_P_PUBLIC_GETS = ("/api/v1/presets/shelf", "/api/v1/gallery", "/api/v1/gallery/wall")


def test_allowlist_serves_new_public_routes_and_hides_staff_routes(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core import api_surface as surf
    from app.domains.presets_hub import previews
    from app.router import build_full_router

    monkeypatch.setattr(previews, "load_manifest", lambda: {})
    from app.domains.gallery import service as gallery_service

    monkeypatch.setattr(gallery_service, "list_public", lambda session, **kw: [])
    monkeypatch.setattr(gallery_service, "wall", lambda session: [])
    import app.domains.gallery.router as gallery_router

    @contextmanager
    def _no_db():
        yield None

    monkeypatch.setattr(gallery_router, "get_session", _no_db)
    monkeypatch.setattr(gallery_router, "_require_db", lambda request_id: None)
    monkeypatch.setattr(surf, "_is_staff", lambda request: False)
    app = FastAPI()
    app.include_router(surf.apply_surface(build_full_router(), surf.ALLOWLIST))
    client = TestClient(app)
    for path in WAVE_P_PUBLIC_GETS:
        assert client.get(path).status_code == 200, path
    assert client.get("/api/v1/admin/funnel/readout").status_code == 404
    assert client.post("/api/v1/admin/gallery/x/wall", json={"approved": True}).status_code == 404
    allow = surf.load_allowlist()
    for route in ("POST /api/v1/presets/shelf/{preset_id}/plan", "POST /api/v1/presets/shelf/{preset_id}/runs",
                  "GET /api/v1/presets/runs/{job_id}", "POST /api/v1/gallery/{item_id}/recreate",
                  "POST /api/v1/my/characters/real-face", "POST /api/v1/my/characters/{character_id}/train"):
        assert route in allow, route
