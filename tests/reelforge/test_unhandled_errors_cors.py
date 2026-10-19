"""Unhandled 500s keep CORS headers (browsers must not see a network error)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from app.core.unhandled_errors import INTERNAL_ERROR_MESSAGE, unhandled_error_middleware

ORIGIN = "https://menivor.com"


def _app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(unhandled_error_middleware)

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    @app.get("/ok")
    def ok():
        return {"status": 200}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


def test_unhandled_error_is_json_500_with_cors() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    response = client.get("/boom", headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == ORIGIN
    assert response.json()["message"] == INTERNAL_ERROR_MESSAGE
    assert "kaboom" not in response.text


def test_normal_responses_pass_through() -> None:
    client = TestClient(_app())
    response = client.get("/ok", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == ORIGIN


def test_real_application_keeps_cors_on_500(monkeypatch) -> None:
    import importlib

    asgi = importlib.import_module("app.asgi")
    app = asgi.app

    def _boom():
        raise RuntimeError("kaboom")

    app.router.add_api_route("/__test_boom__", _boom, include_in_schema=False)
    # Ahead of the static "/" mount, which would otherwise shadow it.
    app.router.routes.insert(0, app.router.routes.pop())

    try:
        client = TestClient(app, raise_server_exceptions=False)
        origin = asgi.origins[0]
        response = client.get("/__test_boom__", headers={"Origin": origin})
        assert response.status_code == 500
        assert response.headers.get("access-control-allow-origin") == origin
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/__test_boom__"]
