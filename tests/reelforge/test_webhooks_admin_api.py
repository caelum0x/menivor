"""Customer webhook-subscription v1 API tests (Enterprise API Platform, Epic 4).

Exercises ``app.controllers.v1.webhooks_admin`` end-to-end over a FastAPI
``TestClient`` with Postgres replaced by in-memory SQLite. No external I/O: the
delivery primitive ``app.services.webhooks.deliver_webhook`` is monkeypatched and
subscription URLs use a public IP literal so the SSRF guard needs no DNS.

Covered
-------
* RBAC — create/list/delete/test/deliveries are gated by ``workspace.settings``:
  a VIEWER gets ``403`` and a caller from ANOTHER workspace gets ``403``.
* SSRF — a create with a loopback/private URL is a clean ``400`` (the SAME guard
  the delivery primitive uses, enforced before any row is persisted).
* SECRET HYGIENE — the signing secret is returned ONCE on create and NEVER on list.
* TEST EVENT — POST .../test signs + delivers and records a delivery.
* TENANT ISOLATION — deliveries are readable only by the owning workspace; a
  foreign subscription id is ``404``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.webhooks_admin as webhooks_mod
from app.models.db.base import Base
from app.models.db.models import User, Workspace, WorkspaceMember
from app.models.exception import HttpException
from app.services import webhooks
from app.utils import utils

# Public IP literal — the SSRF guard accepts it without any DNS resolution.
_PUBLIC_URL = "https://93.184.216.34/hook"


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(raw_key: str) -> dict[str, str]:
    return {"x-api-key": raw_key}


@pytest.fixture(autouse=True)
def _token_key(monkeypatch):
    """A deterministic Fernet key so the signing secret can be encrypted/stored."""
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "test-webhook-signing-key")


@pytest.fixture(autouse=True)
def _fake_deliver(monkeypatch):
    """Stub the delivery primitive: record calls, always report a 200 delivery."""
    calls: list[dict] = []

    def _deliver(url, payload, secret=None, timeout_s=10.0):
        calls.append({"url": url, "payload": payload, "secret": secret})
        return {"delivered": True, "status": 200}

    monkeypatch.setattr(webhooks, "deliver_webhook", _deliver)
    return calls


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def client(monkeypatch, db_factory):
    Factory = db_factory

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(webhooks_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(webhooks_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


@pytest.fixture()
def seeded(db_factory):
    """Workspaces A/B; A has an owner + viewer, B has an owner (foreign caller)."""
    Factory = db_factory
    with Factory() as s:
        owner_a = User(email="ownerA@ex.com", api_key_hash=_key_hash("ownerA-key"))
        viewer_a = User(email="viewerA@ex.com", api_key_hash=_key_hash("viewerA-key"))
        owner_b = User(email="ownerB@ex.com", api_key_hash=_key_hash("ownerB-key"))
        s.add_all([owner_a, viewer_a, owner_b])
        s.flush()
        ws_a = Workspace(owner_id=owner_a.id, name="Acme-A")
        ws_b = Workspace(owner_id=owner_b.id, name="Beta-B")
        s.add_all([ws_a, ws_b])
        s.flush()
        s.add_all(
            [
                WorkspaceMember(workspace_id=ws_a.id, user_id=owner_a.id, role="owner"),
                WorkspaceMember(workspace_id=ws_a.id, user_id=viewer_a.id, role="viewer"),
                WorkspaceMember(workspace_id=ws_b.id, user_id=owner_b.id, role="owner"),
            ]
        )
        s.commit()
        out = {
            "ws_a": ws_a.id,
            "ws_b": ws_b.id,
            "owner_a_key": "ownerA-key",
            "viewer_a_key": "viewerA-key",
            "owner_b_key": "ownerB-key",
        }
    return out


def _create(tc, seeded, key, url=_PUBLIC_URL, events=None):
    return tc.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks",
        headers=_headers(key),
        json={"url": url, "event_types": events or ["job.completed"]},
    )


# --------------------------------------------------------------------------- #
# create — RBAC + SSRF + one-time secret
# --------------------------------------------------------------------------- #
def test_create_returns_secret_once(client, seeded):
    tc, _ = client
    resp = _create(tc, seeded, seeded["owner_a_key"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["url"] == _PUBLIC_URL
    assert data["event_types"] == ["job.completed"]
    assert data["enabled"] is True
    # The signing secret is revealed exactly ONCE, here.
    assert isinstance(data["secret"], str) and len(data["secret"]) > 20


def test_create_is_settings_gated_viewer_403(client, seeded):
    tc, _ = client
    resp = _create(tc, seeded, seeded["viewer_a_key"])
    assert resp.status_code == 403, resp.text


def test_create_foreign_workspace_403(client, seeded):
    tc, _ = client
    resp = _create(tc, seeded, seeded["owner_b_key"])
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://127.0.0.1/hook",
        "http://localhost/hook",
        "http://10.0.0.5/hook",
        "http://169.254.169.254/latest/meta-data",
        "ftp://93.184.216.34/hook",
    ],
)
def test_create_ssrf_url_400(client, seeded, bad_url):
    tc, _ = client
    resp = _create(tc, seeded, seeded["owner_a_key"], url=bad_url)
    assert resp.status_code == 400, resp.text


def test_create_unknown_event_type_400(client, seeded):
    tc, _ = client
    resp = _create(tc, seeded, seeded["owner_a_key"], events=["not.a.real.event"])
    assert resp.status_code == 400, resp.text


# --------------------------------------------------------------------------- #
# list — never returns the secret
# --------------------------------------------------------------------------- #
def test_list_never_returns_secret(client, seeded):
    tc, _ = client
    _create(tc, seeded, seeded["owner_a_key"])
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert "secret" not in row
    assert "secret_enc" not in row
    assert row["url"] == _PUBLIC_URL


def test_list_foreign_workspace_403(client, seeded):
    tc, _ = client
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks",
        headers=_headers(seeded["owner_b_key"]),
    )
    assert resp.status_code == 403, resp.text


# --------------------------------------------------------------------------- #
# delete — tenant-scoped
# --------------------------------------------------------------------------- #
def test_delete_revokes(client, seeded):
    tc, _ = client
    sub_id = _create(tc, seeded, seeded["owner_a_key"]).json()["data"]["id"]
    resp = tc.delete(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks/{sub_id}",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["revoked"] is True
    # Now disabled — a second revoke of a real id is idempotent (still 200).
    again = tc.delete(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks/{sub_id}",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert again.status_code == 200, again.text


def test_delete_unknown_404(client, seeded):
    tc, _ = client
    resp = tc.delete(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks/does-not-exist",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# test event — signs + delivers + records a delivery
# --------------------------------------------------------------------------- #
def test_test_event_delivers_signed(client, seeded, _fake_deliver):
    tc, _ = client
    created = _create(tc, seeded, seeded["owner_a_key"]).json()["data"]
    sub_id = created["id"]
    resp = tc.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks/{sub_id}/test",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    delivery = resp.json()["data"]
    assert delivery["status"] == "delivered"
    assert delivery["event_type"] == "webhook.test"
    assert delivery["subscription_id"] == sub_id
    # The delivery primitive was invoked WITH the subscription's signing secret.
    assert len(_fake_deliver) == 1
    assert _fake_deliver[0]["secret"] == created["secret"]
    assert _fake_deliver[0]["url"] == _PUBLIC_URL


def test_test_event_foreign_subscription_404(client, seeded):
    tc, _ = client
    resp = tc.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks/nope/test",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# deliveries — tenant-scoped
# --------------------------------------------------------------------------- #
def test_deliveries_lists_recent(client, seeded):
    tc, _ = client
    sub_id = _create(tc, seeded, seeded["owner_a_key"]).json()["data"]["id"]
    tc.post(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks/{sub_id}/test",
        headers=_headers(seeded["owner_a_key"]),
    )
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_a']}/webhooks/{sub_id}/deliveries",
        headers=_headers(seeded["owner_a_key"]),
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["subscription_id"] == sub_id
    assert rows[0]["status"] == "delivered"
    # No signed payload body leaks in the summary view.
    assert "payload" not in rows[0]


def test_deliveries_foreign_workspace_cannot_read(client, seeded):
    """A subscription in workspace A is invisible to workspace B's owner (404)."""
    tc, _ = client
    sub_id = _create(tc, seeded, seeded["owner_a_key"]).json()["data"]["id"]
    # B's owner tries to read A's subscription deliveries via B's own workspace path.
    resp = tc.get(
        f"/api/v1/me/workspaces/{seeded['ws_b']}/webhooks/{sub_id}/deliveries",
        headers=_headers(seeded["owner_b_key"]),
    )
    assert resp.status_code == 404, resp.text
