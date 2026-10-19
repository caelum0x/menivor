"""M0.5: /docs and /openapi.json are staff-only by default; the API is "Menivor"."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

import app.core.auth.principal as principal
import app.models.db.base as db_base
from app.asgi import get_application
from app.core import api_docs
from app.models.exception import HttpException


@contextmanager
def _no_db():
    yield object()


def _client(monkeypatch, mode: str | None) -> TestClient:
    if mode is None:
        monkeypatch.delenv("MENIVOR_API_DOCS", raising=False)
    else:
        monkeypatch.setenv("MENIVOR_API_DOCS", mode)
    return TestClient(get_application(), raise_server_exceptions=False)


def _as_user(monkeypatch, *, staff: bool) -> None:
    monkeypatch.setattr(db_base, "get_session", _no_db)
    monkeypatch.setattr(
        principal, "resolve_principal", lambda *_a: SimpleNamespace(id="u1", is_staff=staff)
    )


def test_default_and_unknown_modes_are_staff(monkeypatch):
    monkeypatch.delenv("MENIVOR_API_DOCS", raising=False)
    assert api_docs.docs_mode() == api_docs.STAFF
    monkeypatch.setenv("MENIVOR_API_DOCS", "yes-please")
    assert api_docs.docs_mode() == api_docs.STAFF


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc"])
def test_anonymous_gets_404_by_default(monkeypatch, path):
    def reject(_request, _session, request_id):
        raise HttpException(task_id=request_id, status_code=401, message="missing")

    monkeypatch.setattr(db_base, "get_session", _no_db)
    monkeypatch.setattr(principal, "resolve_principal", reject)
    res = _client(monkeypatch, None).get(path)
    assert res.status_code == 404
    assert "paths" not in res.text


def test_ordinary_user_gets_404(monkeypatch):
    _as_user(monkeypatch, staff=False)
    client = _client(monkeypatch, "staff")
    assert client.get("/docs", headers={"x-api-key": "rk_user"}).status_code == 404
    assert client.get("/openapi.json", headers={"x-api-key": "rk_user"}).status_code == 404


def test_staff_reads_schema_and_docs(monkeypatch):
    _as_user(monkeypatch, staff=True)
    client = _client(monkeypatch, "staff")
    schema = client.get("/openapi.json", headers={"x-api-key": "rk_staff"})
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "Menivor"
    page = client.get("/docs", headers={"x-api-key": "rk_staff"})
    assert page.status_code == 200
    assert "SwaggerUIBundle" in page.text and "</script" not in page.text.split("spec:")[1].split("dom_id")[0]


def test_public_mode_serves_docs_for_local_development(monkeypatch):
    client = _client(monkeypatch, "public")
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_off_mode_has_no_docs_even_for_staff(monkeypatch):
    _as_user(monkeypatch, staff=True)
    client = _client(monkeypatch, "off")
    assert client.get("/openapi.json", headers={"x-api-key": "rk_staff"}).status_code == 404


def test_api_title_is_menivor():
    app = get_application()
    assert app.title == "Menivor"
    assert "MoneyPrinterTurbo" not in (app.description or "")
