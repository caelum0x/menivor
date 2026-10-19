"""Deployment health probes remain cheap and expose no dependency secrets."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import asgi
from app.services import health


def test_healthz_is_a_dependency_free_liveness_probe():
    client = TestClient(asgi.get_application())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_all_critical_dependencies(monkeypatch):
    monkeypatch.setattr(health, "check_runtime_storage", lambda: None)
    monkeypatch.setattr(health, "check_database", lambda: None)
    monkeypatch.setattr(health, "check_redis", lambda: None)
    monkeypatch.setattr(health, "check_r2", lambda: None)
    monkeypatch.setattr(health, "check_generation_worker", lambda: None)
    client = TestClient(asgi.get_application())

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "runtime": "ok",
            "database": "ok",
            "redis": "ok",
            "r2": "ok",
            "worker": "ok",
        },
    }


def test_readyz_fails_closed_when_a_critical_dependency_is_down(monkeypatch):
    monkeypatch.setattr(health, "check_runtime_storage", lambda: None)
    monkeypatch.setattr(health, "check_database", lambda: None)
    monkeypatch.setattr(health, "check_redis", lambda: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(health, "check_r2", lambda: None)
    monkeypatch.setattr(health, "check_generation_worker", lambda: None)
    client = TestClient(asgi.get_application())

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "runtime": "ok",
            "database": "ok",
            "redis": "down",
            "r2": "ok",
            "worker": "ok",
        },
    }


def test_readyz_requires_a_live_generation_worker(monkeypatch):
    monkeypatch.setattr(health, "check_runtime_storage", lambda: None)
    monkeypatch.setattr(health, "check_database", lambda: None)
    monkeypatch.setattr(health, "check_redis", lambda: None)
    monkeypatch.setattr(health, "check_r2", lambda: None)
    monkeypatch.setattr(
        health,
        "check_generation_worker",
        lambda: (_ for _ in ()).throw(RuntimeError("no worker")),
    )
    client = TestClient(asgi.get_application())

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["worker"] == "down"
