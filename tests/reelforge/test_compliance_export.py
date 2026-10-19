"""Tests for GDPR data export (Compliance, Epic 5).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered:

* :func:`export.assemble_export` yields a COMPLETE package containing ONLY the
  requesting user's rows — never another user's jobs / assets / ledger / PII;
* :func:`export.build_export` uploads under an OWNER-SCOPED key, returns a
  short-lived signed GET URL, and records an audit row;
* an unknown / blank user id raises ``ValueError``.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import AuditLog, User
from app.models.db.repositories import (
    AssetRepository,
    CreditRepository,
    InvoiceRepository,
    JobRepository,
    SubscriptionRepository,
    WorkspaceRepository,
)
from app.services.compliance import consent, export


@pytest.fixture()
def session_factory():
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


@contextmanager
def _session(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_user(session, email: str) -> str:
    user = User(email=email, credits=0)
    session.add(user)
    session.flush()
    return user.id


class _FakeStorage:
    """A fake R2 client capturing uploads and returning a deterministic URL."""

    def __init__(self) -> None:
        self.uploaded: dict[str, tuple[bytes, str]] = {}

    def upload_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.uploaded[key] = (data, content_type)
        return key

    def presign_get(self, key, expires=900, download_name=None) -> str:
        return f"https://r2.example.test/{key}?sig=abc123&exp={expires}"


# --------------------------------------------------------------------------- #
# assemble_export — strictly requester-scoped
# --------------------------------------------------------------------------- #
def test_assemble_export_contains_only_requester_rows(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        b = _make_user(s, "bob@example.com")

        # Alice's data.
        job_a = JobRepository(s).create(
            user_id=a, kind="avatar_reel", params={"prompt": "ALICE-SECRET"}
        )
        AssetRepository(s).create(user_id=a, kind="final", r2_key="alice/final.mp4")
        CreditRepository(s).grant(a, 100, "signup")
        ws_a = WorkspaceRepository(s).create_workspace("Alice WS", a)
        SubscriptionRepository(s).upsert(ws_a.id, plan_key="pro", status="active")
        InvoiceRepository(s).create(
            workspace_id=ws_a.id,
            status="paid",
            line_items=[{"description": "sub", "quantity": 1, "amount_cents": 500}],
        )
        consent.record_consent(s, a, "tos", True, version="2026-08")

        # Bob's data — must never appear in Alice's export.
        job_b = JobRepository(s).create(
            user_id=b, kind="avatar_reel", params={"prompt": "BOB-SECRET"}
        )
        AssetRepository(s).create(user_id=b, kind="final", r2_key="bob/final.mp4")
        CreditRepository(s).grant(b, 50, "signup")

        pkg = export.assemble_export(s, a)

        assert pkg["user_id"] == a
        assert pkg["profile"]["email"] == "alice@example.com"

        job_ids = {j["id"] for j in pkg["jobs"]}
        assert job_a.id in job_ids
        assert job_b.id not in job_ids

        asset_keys = {x["r2_key"] for x in pkg["assets"]}
        assert asset_keys == {"alice/final.mp4"}

        assert len(pkg["credit_ledger"]) == 1
        assert pkg["credit_ledger"][0]["balance_after"] == 100

        assert any(sub["plan_key"] == "pro" for sub in pkg["subscriptions"])
        assert any(inv["amount_cents"] == 500 for inv in pkg["invoices"])
        assert any(c["kind"] == "tos" and c["granted"] for c in pkg["consents"])
        assert any(m["workspace_id"] == ws_a.id for m in pkg["memberships"])

        # No trace of Bob anywhere in the serialized package.
        blob = json.dumps(pkg)
        assert "bob@example.com" not in blob
        assert "BOB-SECRET" not in blob


def test_assemble_export_rejects_unknown_user(session_factory):
    with _session(session_factory) as s:
        with pytest.raises(ValueError):
            export.assemble_export(s, "does-not-exist")
        with pytest.raises(ValueError):
            export.assemble_export(s, "   ")


# --------------------------------------------------------------------------- #
# build_export — owner-scoped upload + signed url + audit
# --------------------------------------------------------------------------- #
def test_build_export_returns_signed_url_and_audits(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        JobRepository(s).create(user_id=a, kind="avatar_reel", params={})

        storage = _FakeStorage()
        url = export.build_export(s, a, storage=storage)

        assert isinstance(url, str)
        assert url.startswith("https://")

        # Exactly one object uploaded, under an OWNER-SCOPED key.
        assert len(storage.uploaded) == 1
        key = next(iter(storage.uploaded))
        assert key.startswith(f"exports/{a}/")
        data, content_type = storage.uploaded[key]
        assert content_type == "application/json"
        # Uploaded bytes are the requester's package.
        parsed = json.loads(data.decode("utf-8"))
        assert parsed["user_id"] == a

        # Audit row recorded (export has no workspace scope -> query by action).
        rows = list(
            s.execute(
                select(AuditLog).where(
                    AuditLog.action == "compliance.data_exported"
                )
            ).scalars().all()
        )
        assert len(rows) == 1
        assert rows[0].target_id == a
        assert rows[0].actor_user_id == a


def test_build_export_scopes_key_per_user(session_factory):
    """Two users' exports land under distinct owner-scoped prefixes."""
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        b = _make_user(s, "bob@example.com")
        storage = _FakeStorage()

        export.build_export(s, a, storage=storage)
        export.build_export(s, b, storage=storage)

        keys = sorted(storage.uploaded)
        assert any(k.startswith(f"exports/{a}/") for k in keys)
        assert any(k.startswith(f"exports/{b}/") for k in keys)
        # No key for A ever lands under B's prefix or vice-versa.
        assert not any(k.startswith(f"exports/{a}/") and f"/{b}/" in k for k in keys)
