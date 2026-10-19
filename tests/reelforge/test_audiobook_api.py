"""Audiobook export routes: opt-in gate, auth order, validation, MP3 response."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.audiobook import router as audiobook_router
from app.domains.routing.base import ProviderError
from app.domains.routing.providers.kokoro import SpeechResult
from app.models.exception import HttpException
from app.utils import utils


class FakeKokoro:
    calls: list[tuple[str, str, float]] = []
    fail: ProviderError | None = None

    def __init__(self, base_url, **_kw):
        self.base_url = base_url

    def synthesize(self, text, *, voice, speed, response_format):
        if FakeKokoro.fail:
            raise FakeKokoro.fail
        FakeKokoro.calls.append((text, voice, speed))
        return SpeechResult(audio=b"MP3", content_type="audio/mpeg", characters=len(text), voice=voice)

    def list_voices(self):
        return ["af_heart", "bf_emma"]


@pytest.fixture()
def client(monkeypatch):
    FakeKokoro.calls = []
    FakeKokoro.fail = None
    auth_calls: list[str] = []

    @contextmanager
    def fake_session():
        yield object()

    def fake_principal(*_a):
        auth_calls.append("x")
        return SimpleNamespace(id="u1")

    monkeypatch.setattr(audiobook_router, "get_session", fake_session)
    monkeypatch.setattr(audiobook_router, "require_database", lambda _rid: None)
    monkeypatch.setattr(audiobook_router, "resolve_principal", fake_principal)
    monkeypatch.setattr(audiobook_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_router, "KokoroClient", FakeKokoro)
    app = FastAPI()
    app.include_router(audiobook_router.router)
    app.add_exception_handler(
        HttpException,
        lambda _r, exc: JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        ),
    )
    return SimpleNamespace(http=TestClient(app), auth_calls=auth_calls)


def test_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("KOKORO_URL", raising=False)
    status = client.http.get("/api/v1/audiobook/status")
    assert status.status_code == 200
    assert status.json()["data"] == {"enabled": False, "voices": []}
    resp = client.http.post("/api/v1/audiobook/chapter", json={"text": "Hello."})
    assert resp.status_code == 503
    assert client.auth_calls == []  # the gate runs before auth


def test_chapter_returns_mp3(client, monkeypatch):
    monkeypatch.setenv("KOKORO_URL", "http://kokoro:8880")
    resp = client.http.post(
        "/api/v1/audiobook/chapter",
        json={"text": "Chapter one. It begins.", "voice": "bf_emma", "speed": 1.25},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == b"MP3"
    assert resp.headers["cache-control"] == "no-store"
    assert FakeKokoro.calls == [("Chapter one. It begins.", "bf_emma", 1.25)]
    assert client.auth_calls == ["x"]


def test_status_lists_voices_when_enabled(client, monkeypatch):
    monkeypatch.setenv("KOKORO_URL", "http://kokoro:8880")
    body = client.http.get("/api/v1/audiobook/status").json()["data"]
    assert body == {"enabled": True, "voices": ["af_heart", "bf_emma"]}


@pytest.mark.parametrize(
    "payload",
    [
        {"text": ""},
        {"text": "hi", "speed": 5},
        {"text": "hi", "voice": "../etc"},
        {"text": "hi", "extra": 1},
    ],
)
def test_validation(client, monkeypatch, payload):
    monkeypatch.setenv("KOKORO_URL", "http://kokoro:8880")
    assert client.http.post("/api/v1/audiobook/chapter", json=payload).status_code == 422


def test_oversized_part_is_413(client, monkeypatch):
    monkeypatch.setenv("KOKORO_URL", "http://kokoro:8880")
    resp = client.http.post("/api/v1/audiobook/chapter", json={"text": "Hello world. " * 2000})
    assert resp.status_code == 413


def test_sidecar_failure_maps_to_503(client, monkeypatch):
    monkeypatch.setenv("KOKORO_URL", "http://kokoro:8880")
    FakeKokoro.fail = ProviderError("down", provider_key="kokoro", retryable=True)
    resp = client.http.post("/api/v1/audiobook/chapter", json={"text": "Hello."})
    assert resp.status_code == 503
    assert "down" not in resp.text
