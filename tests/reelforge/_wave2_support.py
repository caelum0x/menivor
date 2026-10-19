"""Shared setup for the wave-2 tests: one in-memory DB patched into every service that opens sessions."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.actors import models as _actors  # noqa: F401  (registers tables)
from app.domains.competitors import models as _competitors  # noqa: F401
from app.domains.creative_review import models as _reviews  # noqa: F401
from app.domains.integrations import models as _integrations  # noqa: F401
from app.domains.launch_kit import models as _launch_kit  # noqa: F401
from app.domains.mcp_hosted import models as _mcp  # noqa: F401
from app.domains.studio_render import models as _renders  # noqa: F401
from app.domains.workflows import models as _workflows  # noqa: F401
from app.models.db import premium_credit as _premium  # noqa: F401
from app.models.exception import HttpException
from app.utils import utils
from tests.reelforge._brand_agent_support import make_deps, make_factory, make_user

SESSION_MODULES = (
    "app.domains.approvals.service",
    "app.domains.approvals.adapters",
    "app.domains.creative_review.adapter",
    "app.domains.creative_review.service",
    "app.domains.studio_render.service",
)


def patch_sessions(monkeypatch, db, extra: tuple[str, ...] = ()) -> None:
    import importlib

    for name in (*SESSION_MODULES, *extra):
        monkeypatch.setattr(importlib.import_module(name), "get_session", db.scope, raising=False)


def make_env(monkeypatch, extra: tuple[str, ...] = ()):
    db = make_factory()
    patch_sessions(monkeypatch, db, extra)
    uid = make_user(db, "owner@example.com")
    other = make_user(db, "other@example.com")
    return SimpleNamespace(db=db, uid=uid, other=other, deps=make_deps())


def client_for(*routers, monkeypatch=None, db=None) -> TestClient:
    app = FastAPI()
    for module in routers:
        if monkeypatch is not None and db is not None and hasattr(module, "get_session"):
            monkeypatch.setattr(module, "get_session", db.scope)
        app.include_router(module.router)
    app.add_exception_handler(HttpException, lambda request, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def grant_ai_video(db, user_id: str, amount: int) -> None:
    from app.services.billing import premium_credits as pc

    with db.scope() as s:
        pc.grant(s, user_id, pc.KIND_AI_VIDEO, amount, "test-grant")


def ai_video_balance(db, user_id: str) -> int:
    from app.services.billing import premium_credits as pc

    with db.scope() as s:
        return pc.balance(s, user_id, pc.KIND_AI_VIDEO)


def data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


H = {"x-api-key": "owner@example.com"}
OTHER = {"x-api-key": "other@example.com"}
