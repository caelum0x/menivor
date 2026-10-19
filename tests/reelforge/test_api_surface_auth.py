"""API surface: the allowlist follows what the clients call, and allowlisted is not anonymous.

* The audit tool reads template paths (``${encodeURIComponent(id)}``, nested templates,
  ``apiPath`` tagged templates, a leading ``${API_BASE}``) and normalises them to the
  route pattern, so every route a client screen calls is allowlisted.
* Being on the allowlist only makes a route reachable. Every allowlisted route either
  authenticates the caller (statically: the endpoint or its helpers resolve a principal,
  a viewer session, a signed hook or a bearer token) or is public by design and listed
  below with the reason. Dynamically, an anonymous request to any allowlisted route that
  is not public by design is never served (no 2xx/3xx).
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import textwrap
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

from app.core import api_surface as surf

TOOL = Path(surf.__file__).resolve().parents[2] / "tools" / "ops" / "api_surface_audit.py"

#: Public by design (normalised path prefix -> why anonymous access is intended).
PUBLIC_BY_DESIGN: dict[str, str] = {
    "/catalog/": "read-only catalogs (styles, music, models, presets, provider health)",
    "/templates": "template gallery, backgrounds and compile previews (no account data)",
    "/motion": "camera-move preset catalog and compile preview",
    "/styles": "one-click style catalog",
    "/presets/shelf": "public preset shelf",
    "/presets/drops": "released weekly preset drop",
    "/apps": "apps shelf listing",
    "/scenes": "talking-scene catalog and price quote (404 until PRESENTER_LIVE)",
    "/characters/narrators": "built-in narrator catalog",
    "/generation/speak/providers": "voice provider catalog",
    "/dub/languages": "dub language catalog",
    "/publishing/native/platforms": "native publishing platform list",
    "/captions/": "stateless caption tools (safe zones, loop check, beat fit, SEO)",
    "/trends/rank": "stateless ranking of the posted list",
    "/trends/recommended": "public trend recommendations",
    "/film/plan": "stateless shot-list preview (nothing stored, nothing charged)",
    "/billing/": "public plan prices; signed payment webhooks (unsigned events are dropped)",
    "/credit-packs": "public credit-pack prices (checkout itself requires an account)",
    "/creators/": "public creator profiles and leaderboard",
    "/gallery": "opt-in public gallery",
    "/ott/": "viewer-facing channel pages, feeds and players (404 until OTT flags; personal "
             "routes use the viewer session header)",
    "/ads/status": "which ad platforms are configured (no account data)",
    "/mcp": "hosted MCP transport: bearer connector token checked in the handler",
    "/metrics": "Prometheus scrape (observability plane)",
    "/media/models": "developer media gateway model list (prices and ids only)",
    "/launch/status": "launch posture for the marketing site",
    "/webhooks/": "signed platform webhooks (unsigned events are dropped)",
}
#: How an endpoint (or a helper it calls) authenticates the caller.
AUTH_MARKERS = re.compile(
    r"require_caller|resolve_principal|_resolve_user|resolve_user|verify_token|require_user|current_user|_caller\(|require_auth|"
    r"_principal|_user_id\(|signature|verify_|hmac|_guard\(|Call\(|_call\(|_run\(|tokens\.verify|require_staff|"
    r"is_staff|api_key|_with_viewer|viewers\.resolve|viewer_session|check_hook|_hook\(|webhooks\.verify|token")


def _tool():
    spec = importlib.util.spec_from_file_location("api_surface_audit_auth", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    return _tool()


@pytest.fixture(scope="module")
def full_router():
    from app.router import build_full_router

    return build_full_router()


def _allowlisted(full_router) -> list[tuple[str, APIRoute]]:
    allow = surf.load_allowlist()
    out = []
    for r in full_router.routes:
        if isinstance(r, APIRoute):
            out += [(m, r) for m in sorted(r.methods - {"HEAD", "OPTIONS"}) if f"{m} {r.path}" in allow]
    return out


def _public(tool, path: str) -> bool:
    norm = tool.normalise(path)
    return any(norm == p.rstrip("/") or norm.startswith(p if p.endswith("/") else p) for p in PUBLIC_BY_DESIGN)


# --------------------------------------------------------------------------- the parser
@pytest.mark.parametrize("snippet,expected", [
    ("apiRequest(`/review/${encodeURIComponent(itemId)}/decide`)", ["/review/{}/decide"]),
    ("fetch(`${API_BASE}/auth/device`)", ["/auth/device"]),
    ("get(`/jobs/${id}/share?x=${a ? `b${c}` : \"\"}`)", ["/jobs/{}/share"]),
    ("apiPath`/actors/${actorId}/face`", ["/actors/{}/face"]),
    ("q(`/competitors/ads${tier ? `?tier=${tier}` : \"\"}`)", ["/competitors/ads"]),
    ("x(`/me/workspaces/${enc(ws.id)}/members/${enc(u)}/role`)", ["/me/workspaces/{}/members/{}/role"]),
    ("y('/me/presets'); // don't call '/admin/secret'", ["/me/presets"]),
    ("/** POST `/wallet/checkout` starts a payment */", []),
])
def test_parser_understands_template_paths(tool, snippet, expected):
    assert [tool.normalise(p) for p in tool.path_literals(snippet)] == expected


def test_route_patterns_and_client_templates_normalise_alike(tool):
    assert tool.normalise("/api/v1/me/workspaces/{workspace_id}/scim/tokens/{token_id}") == \
        tool.normalise("/me/workspaces/${encodeURIComponent(id)}/scim/tokens/${encodeURIComponent(t)}")
    assert tool.normalise("/api/v1/catalog/models/{model_id:path}") == "/catalog/models/{}"


# --------------------------------------------------------------------------- reachability
def test_every_route_a_client_screen_calls_is_allowlisted(tool, full_router):
    literals = tool.client_literals()
    allow = surf.load_allowlist()
    missing = []
    for r in full_router.routes:
        if not isinstance(r, APIRoute) or surf.is_frozen(r.path) or surf.is_staff_only(r.path):
            continue
        if tool.normalise(r.path) in literals:
            missing += [f"{m} {r.path}" for m in sorted(r.methods - {"HEAD", "OPTIONS"})
                        if f"{m} {r.path}" not in allow]
    assert missing == [], "re-run apps/api/tools/ops/api_surface_audit.py"


def test_the_screens_blocked_before_this_fix_are_reachable():
    allow = surf.load_allowlist()
    for route in ("POST /api/v1/jobs/{job_id}/share", "POST /api/v1/jobs/{job_id}/retry",
                  "GET /api/v1/me/notifications", "GET /api/v1/workspaces/{workspace_id}/members",
                  "GET /api/v1/film/projects/{project_id}", "GET /api/v1/public/r/{token}",
                  "POST /api/v1/credit-packs/{pack_id}/checkout", "POST /api/v1/review/{item_id}/decide"):
        assert route in allow, route


# --------------------------------------------------------------------------- authentication
def _source(fn, depth: int = 2, seen: set | None = None) -> str:
    seen = set() if seen is None else seen
    if depth < 0 or fn in seen:
        return ""
    seen.add(fn)
    try:
        src = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(src)
    except (OSError, TypeError, SyntaxError):
        return ""
    names = getattr(fn, "__globals__", {})
    out = src
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            helper = names.get(node.func.id)
            if callable(helper) and str(getattr(helper, "__module__", "")).startswith("app."):
                out += _source(helper, depth - 1, seen)
    return out


def _dependency_names(dependant) -> str:
    names = []
    for dep in dependant.dependencies:
        names.append(getattr(dep.call, "__name__", ""))
        names.append(_dependency_names(dep))
    return " ".join(names)


def test_every_allowlisted_route_authenticates_or_is_public_by_design(tool, full_router):
    unauthenticated = sorted({
        f"{m} {r.path}" for m, r in _allowlisted(full_router)
        if not _public(tool, r.path)
        and not AUTH_MARKERS.search(_source(r.endpoint) + " " + _dependency_names(r.dependant))
    })
    assert unauthenticated == [], "add auth, or list the route in PUBLIC_BY_DESIGN with the reason"


def test_public_by_design_entries_are_all_in_use(tool, full_router):
    used = {p for p in PUBLIC_BY_DESIGN for _m, r in _allowlisted(full_router)
            if tool.normalise(r.path).startswith(p.rstrip("/"))}
    assert used == set(PUBLIC_BY_DESIGN)


def test_anonymous_requests_to_allowlisted_private_routes_are_refused(tool, full_router):
    from app.asgi import app as real_app

    api = FastAPI()
    api.exception_handlers.update(real_app.exception_handlers)
    api.include_router(surf.apply_surface(full_router, surf.ALLOWLIST))
    client = TestClient(api, raise_server_exceptions=False, follow_redirects=False)
    served, refused_401, total = [], 0, 0
    for method, route in _allowlisted(full_router):
        if _public(tool, route.path):
            continue
        total += 1
        path = re.sub(r"\{[^}]+\}", "x123", route.path)
        resp = client.request(method, path, json={} if method in ("POST", "PUT", "PATCH") else None)
        if resp.status_code < 400:
            served.append(f"{method} {route.path} -> {resp.status_code}")
        refused_401 += resp.status_code in (401, 403)
    assert served == []
    # Most refusals are the auth check itself; the rest fail input validation first (never served).
    assert refused_401 / total > 0.5
