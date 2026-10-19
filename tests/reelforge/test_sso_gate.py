"""MN7a: SSO is hidden until real SSO ships.

With the flag off (the default) every SSO route answers 501 "contact sales",
including the public SAML endpoints, and nothing touches the database. With
``MENIVOR_SSO_ENABLED=1`` the routes are reachable again (the code is kept).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.sso as sso_mod
from app.models.exception import HttpException
from app.utils import utils

_ROUTES = [
    ("get", "/api/v1/sso/ws1/metadata"),
    ("get", "/api/v1/sso/ws1/login"),
    ("post", "/api/v1/sso/ws1/acs"),
    ("get", "/api/v1/me/workspaces/ws1/sso"),
    ("put", "/api/v1/me/workspaces/ws1/sso"),
    ("delete", "/api/v1/me/workspaces/ws1/sso"),
]


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(sso_mod.router)

    def _handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app)


@pytest.mark.parametrize(("method", "path"), _ROUTES)
def test_sso_routes_answer_501_contact_sales_by_default(client, monkeypatch, method, path):
    monkeypatch.delenv(sso_mod.SSO_FLAG_ENV, raising=False)
    monkeypatch.setattr(sso_mod, "_require_db", lambda _rid: pytest.fail("DB touched"))
    res = getattr(client, method)(path)
    assert res.status_code == 501
    message = res.json()["message"]
    assert "Contact sales" in message
    assert sso_mod.SSO_SALES_EMAIL in message


@pytest.mark.parametrize("value", ["0", "", "off"])
def test_flag_values_that_keep_sso_hidden(monkeypatch, value):
    monkeypatch.setenv(sso_mod.SSO_FLAG_ENV, value)
    assert sso_mod.sso_enabled() is False


def test_flag_on_reaches_the_kept_code(client, monkeypatch):
    monkeypatch.setenv(sso_mod.SSO_FLAG_ENV, "1")
    reached: list[str] = []

    def _stop(rid: str) -> None:
        reached.append(rid)
        raise HttpException(task_id=rid, status_code=503, message="stop")

    monkeypatch.setattr(sso_mod, "_require_db", _stop)
    monkeypatch.setattr(sso_mod, "_require_backend", lambda rid: _stop(rid))
    res = client.get("/api/v1/sso/ws1/metadata")
    assert res.status_code == 503
    assert reached
