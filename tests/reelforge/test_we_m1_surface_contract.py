"""Wave E M-1 (hand-off H1): quote, preset quote and keep are public in allowlist mode.

In production the surface is ``allowlist``. A signed-in user must get a price
before every render (MG3, MH1) and be able to keep a variant (M3.1); a
staff-only route must still answer 404 to that same user.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.jobs as jobs_mod
from app.core import api_surface as surf
from app.models.exception import HttpException
from app.utils import utils
from tests.reelforge.test_byov_api import _FakePipeline
from tests.reelforge.test_premium_credits import (  # noqa: F401 - fixtures
    _HEADERS,
    _user,
    db,
)

CONTRACT = (
    "POST /api/v1/jobs/quote",
    "POST /api/v1/jobs/quote/preset",
    "POST /api/v1/jobs/{job_id}/keep",
)


def test_committed_allowlist_names_the_contract_routes():
    allow = surf.load_allowlist()
    for route in CONTRACT:
        assert route in allow, route


def _allowlist_client(monkeypatch, extra_staff_route: bool = True) -> TestClient:
    monkeypatch.setattr(jobs_mod, "_import_pipeline", lambda rid: _FakePipeline())
    monkeypatch.setattr(jobs_mod, "_validate_enabled_feature_secrets", lambda params, rid: None)
    full = jobs_mod.router
    routed = surf.apply_surface(full, surf.ALLOWLIST, surf.load_allowlist())
    app = FastAPI()
    app.include_router(routed)

    def handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, handler)
    monkeypatch.setattr(surf, "_is_staff", lambda request: False)
    return TestClient(app), routed


def test_signed_in_user_gets_quotes_and_staff_route_is_404(db, monkeypatch):  # noqa: F811
    client, routed = _allowlist_client(monkeypatch)
    _user(db, credits=5)
    body = {"variants": 1, "params": {"video_subject": "cats", "layout": "captions_only"}}
    res = client.post("/api/v1/jobs/quote", json=body, headers=_HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["per_variant"]["standard"] == 1

    # Preset quote reaches its handler (200 priced, or 402 when the preset is
    # unpriced in this catalog) - never the 404 of a hidden route.
    res = client.post(
        "/api/v1/jobs/quote/preset",
        json={"preset_sku": "product_hero", "tier": "draft", "seconds": 5},
        headers=_HEADERS,
    )
    assert res.status_code in (200, 402), res.text

    # Keep on an unknown job is the handler's own 404 ("job not found"),
    # not the anonymous hidden-route 404.
    res = client.post("/api/v1/jobs/job_missing/keep", headers=_HEADERS)
    assert res.status_code == 404
    assert "job not found" in res.text

    # A route no client calls stays staff-only for the same signed-in user.
    staff = [
        r for r in routed.routes
        if isinstance(r, APIRoute)
        and any(getattr(d, "dependency", None) is surf.require_staff for d in r.dependencies)
    ]
    assert staff, "expected at least one staff-only route in the jobs router"
    hidden = staff[0]
    method = sorted(hidden.methods - {"HEAD", "OPTIONS"})[0]
    path = hidden.path.replace("{job_id}", "job_x").replace("{batch_id}", "b_x")
    path = path.replace("{", "").replace("}", "")
    res = client.request(method, path, headers=_HEADERS)
    assert res.status_code == 404
    assert res.json().get("detail") == "Not Found"


def test_contract_routes_are_not_staff_gated_in_allowlist_mode(monkeypatch):
    _client, routed = _allowlist_client(monkeypatch)
    public = {
        f"{m} {r.path}"
        for r in routed.routes
        if isinstance(r, APIRoute)
        and not any(getattr(d, "dependency", None) is surf.require_staff for d in r.dependencies)
        for m in (r.methods or ())
    }
    for route in CONTRACT:
        assert route in public, route
