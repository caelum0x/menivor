"""Key storage: encrypted at rest, never returned, disconnect removes it.

Also checks a finished reel can be scheduled once the key is stored, and that
a provider limit becomes a 402 instead of an uncaught error.
"""

from __future__ import annotations

import hashlib
import importlib
from contextlib import contextmanager

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.x_scheduler.errors import LimitReached
from app.domains.x_scheduler.models import SchedulerConnection
from app.domains.x_scheduler.service import connect, disconnect, list_connections, schedule_post
from app.models.const import TASK_STATE_COMPLETE
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.services import crypto_tokens
from app.utils import utils

router_mod = importlib.import_module("app.domains.x_scheduler.router")
SECRET = "buf_live_owner_key_9f3a"


class _FakeBuffer:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def list_x_channels(self):
        if self.api_key != SECRET:
            from app.domains.x_scheduler.http import ProviderHTTPError

            raise ProviderHTTPError(401, "Buffer rejected that API key.")
        return [{"id": "ch-x", "name": "Ada", "handle": "ada", "organization": "Acme",
                 "service": "x", "provider": "buffer"}]

    def create_post(self, **kwargs):
        assert kwargs["channel_id"] == "ch-x"
        assert kwargs["asset_url"] == "https://media.example/reel.mp4"
        assert kwargs["when"] == "now"
        return {"id": "post_9", "status": "publishing"}


class _LimitBuffer(_FakeBuffer):
    def create_post(self, **kwargs):
        raise LimitReached(
            "Buffer's free plan allows 10 scheduled posts per channel, and this "
            "channel has reached that limit. Nothing was posted."
        )


@pytest.fixture()
def factory(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", Fernet.generate_key().decode())
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _user(factory, email: str, raw: str) -> str:
    with factory() as session:
        user = User(email=email, api_key_hash=hashlib.sha256(raw.encode()).hexdigest())
        session.add(user)
        session.commit()
        return user.id


def test_connect_stores_ciphertext_and_list_hides_the_key(factory, monkeypatch):
    monkeypatch.setattr("app.domains.x_scheduler.service.BufferClient", _FakeBuffer)
    user_id = _user(factory, "ada@example.com", "ada-key")
    with factory() as session:
        view = connect(session, user_id, "buffer", SECRET)
        session.commit()
    assert view["connected"] is True
    assert view["key_hint"] == "••••9f3a"
    assert SECRET not in str(view)
    assert "encrypted_secret" not in view

    with factory() as session:
        row = session.scalar(select(SchedulerConnection).where(SchedulerConnection.user_id == user_id))
        assert row.encrypted_secret != SECRET
        assert crypto_tokens.decrypt(row.encrypted_secret) == SECRET
        listed = list_connections(session, user_id)
    blob = str(listed)
    assert SECRET not in blob
    assert "encrypted_secret" not in blob
    assert listed[0]["provider"] == "buffer" and listed[0]["connected"] is True
    assert listed[1]["provider"] == "typefully" and listed[1]["connected"] is False


def test_missing_encryption_key_does_not_store_plaintext(factory, monkeypatch):
    monkeypatch.setattr("app.domains.x_scheduler.service.BufferClient", _FakeBuffer)
    monkeypatch.delenv("SOCIAL_TOKEN_KEY", raising=False)
    monkeypatch.setattr(crypto_tokens, "_resolve_secret", lambda: "")
    user_id = _user(factory, "bea@example.com", "bea-key")
    with factory() as session:
        with pytest.raises(Exception) as caught:
            connect(session, user_id, "buffer", SECRET)
        session.rollback()
    assert "SOCIAL_TOKEN_KEY" in str(caught.value)
    with factory() as session:
        assert session.scalar(select(SchedulerConnection)) is None


def test_disconnect_removes_the_row_and_other_users_cannot_see_it(factory, monkeypatch):
    monkeypatch.setattr("app.domains.x_scheduler.service.BufferClient", _FakeBuffer)
    ada = _user(factory, "ada2@example.com", "ada-key")
    bea = _user(factory, "bea2@example.com", "bea-key")
    with factory() as session:
        connect(session, ada, "buffer", SECRET)
        session.commit()
    with factory() as session:
        assert list_connections(session, bea)[0]["connected"] is False
        disconnect(session, ada, "buffer")
        session.commit()
    with factory() as session:
        assert session.scalar(select(SchedulerConnection).where(SchedulerConnection.user_id == ada)) is None


def test_schedule_uses_the_stored_key_and_a_finished_reel(factory, monkeypatch):
    monkeypatch.setattr("app.domains.x_scheduler.service.BufferClient", _FakeBuffer)
    user_id = _user(factory, "ada3@example.com", "ada-key")
    with factory() as session:
        connect(session, user_id, "buffer", SECRET)
        job = Job(
            user_id=user_id,
            state=TASK_STATE_COMPLETE,
            result_key="https://media.example/reel.mp4",
        )
        session.add(job)
        session.commit()
        job_id = job.id
    with factory() as session:
        result = schedule_post(
            session, user_id, provider="buffer", target_id="ch-x", source="reel",
            source_id=job_id, caption="Ship it", when="now", scheduled_at=None,
        )
    assert result["external_id"] == "post_9"
    assert result["status"] == "publishing"
    assert SECRET not in str(result)


def test_limit_reached_is_returned_and_does_not_crash(factory, monkeypatch):
    monkeypatch.setattr("app.domains.x_scheduler.service.BufferClient", _LimitBuffer)
    user_id = _user(factory, "ada4@example.com", "ada-key")
    with factory() as session:
        connect(session, user_id, "buffer", SECRET)
        job = Job(user_id=user_id, state=TASK_STATE_COMPLETE, result_key="https://media.example/reel.mp4")
        session.add(job)
        session.commit()
        job_id = job.id
        with pytest.raises(LimitReached) as caught:
            schedule_post(
                session, user_id, provider="buffer", target_id="ch-x", source="reel",
                source_id=job_id, caption="Ship it", when="queue", scheduled_at=None,
            )
    assert caught.value.status_code == 402
    assert "10 scheduled posts" in caught.value.message


def test_http_save_never_returns_the_key(factory, monkeypatch):
    monkeypatch.setattr("app.domains.x_scheduler.service.BufferClient", _FakeBuffer)

    @contextmanager
    def _session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(router_mod, "get_session", _session)
    monkeypatch.setattr(router_mod, "_DB_IMPORT_ERROR", None)
    raw = "owner-api-key"
    _user(factory, "ada5@example.com", raw)
    app = FastAPI()
    app.include_router(router_mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    client = TestClient(app)
    saved = client.put(
        "/api/v1/scheduler/connections/buffer",
        headers={"x-api-key": raw},
        json={"api_key": SECRET},
    )
    assert saved.status_code == 200, saved.text
    assert SECRET not in saved.text
    body = saved.json()["data"]
    assert body["key_hint"] == "••••9f3a"
    assert body["connected"] is True

    listed = client.get("/api/v1/scheduler/connections", headers={"x-api-key": raw})
    assert SECRET not in listed.text
    gone = client.delete("/api/v1/scheduler/connections/buffer", headers={"x-api-key": raw})
    assert gone.status_code == 200
    assert gone.json()["data"]["connected"] is False


def test_signed_buffer_url_is_refused_for_a_queued_post():
    from app.domains.x_scheduler.media import MediaAsset, buffer_asset_url

    asset = MediaAsset(
        kind="video", filename="clip.mp4", content_type="video/mp4",
        url="https://media.example/clip.mp4?X-Amz-Signature=abc&X-Amz-Expires=60",
    )
    with pytest.raises(Exception) as caught:
        buffer_asset_url(asset, "queue")
    assert "temporary" in str(caught.value).lower() or "stable" in str(caught.value).lower()
    url, note = buffer_asset_url(asset, "now")
    assert url.startswith("https://media.example/")
    assert "temporary" in note
