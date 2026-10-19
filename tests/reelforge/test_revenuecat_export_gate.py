"""HTTP wiring for the server-authoritative RevenueCat editor gate."""

from __future__ import annotations

from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.exception import HttpException
from app.utils import utils

editor_router = import_module("app.domains.editor.router")


@pytest.fixture()
def client(monkeypatch):
    @contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(editor_router, "get_session", fake_session)
    monkeypatch.setattr(
        editor_router,
        "resolve_principal",
        lambda _request, _session, _request_id: SimpleNamespace(id="user-1"),
    )
    monkeypatch.setattr(editor_router, "read_idempotency_key", lambda *_args: None)

    app = FastAPI()
    app.include_router(editor_router.router)

    def handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, handler)
    return TestClient(app)


def test_timeline_export_denies_without_active_pro(client, monkeypatch):
    called = False

    def deny(_user_id, request_id, *, action):
        assert action == "export"
        raise HttpException(
            task_id=request_id,
            status_code=402,
            message=f"{request_id}: an active Pro entitlement is required",
        )

    def should_not_create(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}, True

    monkeypatch.setattr(editor_router, "require_pro_action", deny)
    monkeypatch.setattr(
        editor_router, "create_timeline_export_job", should_not_create
    )

    response = client.post(
        "/api/v1/jobs/job-1/timeline-exports",
        json={
            "segments": [{"source_in": 0, "source_out": 5}],
            "overlays": [],
        },
    )
    assert response.status_code == 402, response.text
    assert called is False


def test_timeline_export_allows_active_pro(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        editor_router,
        "require_pro_action",
        lambda user_id, request_id, *, action: seen.update(
            user_id=user_id, request_id=request_id, action=action
        ),
    )
    monkeypatch.setattr(
        editor_router,
        "create_timeline_export_job",
        lambda *_args, **_kwargs: (
            {"job_id": "export-1", "state": "pending"},
            True,
        ),
    )

    response = client.post(
        "/api/v1/jobs/job-1/timeline-exports",
        json={
            "segments": [{"source_in": 0, "source_out": 5}],
            "overlays": [],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["job_id"] == "export-1"
    assert seen["user_id"] == "user-1"
    assert seen["action"] == "export"
    assert seen["request_id"]
