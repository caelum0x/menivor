"""Unified media gateway — OpenRouter-style /images + /videos over the real stack.

Real gateway + real wallet ledger + the real Kling/fal adapter; only the fal HTTP
session is faked (swapped socket). Verifies catalog routing, wallet reserve/settle/
refund, the video submit→poll→complete lifecycle, and sync image generation.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.wallet.repository import ENTRY_GRANT, WalletRepository
from app.domains.wallet.service import WalletService
from app.models.db import media_jobs, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.media_jobs import MediaJob
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

mod = importlib.import_module("app.domains.gateway.media_router")


class _Resp:
    def __init__(self, status_code=200, body=None, content=b""):
        self.status_code = status_code
        self._body = body or {}
        self.headers = {}
        self._content = content

    def json(self):
        return self._body

    def iter_content(self, chunk_size=1024):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeFal:
    """Fake fal.ai session — scripted queue responses."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def request(self, method, url, *, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url})
        return self._script.pop(0)

    def get(self, url, *, stream=False, timeout=None):
        return self._script.pop(0)


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )

    @contextmanager
    def _gs():
        s = Factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    with _gs() as s:
        s.add(User(id="u1", email="u@x.com"))
        s.flush()
        repo = WalletRepository(s)
        acct = repo.get_or_create_personal_account("u1")
        repo.append_entry(
            acct.id, entry_type=ENTRY_GRANT, reason="topup", available_delta=100_000_000
        )

    class _U:
        id = "u1"

    monkeypatch.setenv("FAL_KEY", "fal-test-key")
    monkeypatch.setattr(mod, "get_session", _gs)
    monkeypatch.setattr(mod, "_require_db", lambda rid: None)
    monkeypatch.setattr(mod, "_resolve_user", lambda req, s, rid: _U())
    monkeypatch.setattr(mod, "_IMPORT_ERROR", None)

    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        ),
    )
    return TestClient(app), _gs, monkeypatch


def test_models_catalog_lists_image_and_video(client):
    tc, _, _ = client
    resp = tc.get("/api/v1/media/models")
    data = resp.json()["data"]["models"]
    ids = {m["id"] for m in data}
    assert "kwaivgi/kling-v1.6" in ids and "bytedance-seed/seedream-4.5" in ids
    assert any(m["modality"] == "video" for m in data) and any(
        m["modality"] == "image" for m in data
    )


def test_catalog_is_broad_multi_provider(client):
    tc, _, _ = client
    data = tc.get("/api/v1/media/models").json()["data"]["models"]
    provs = {m["provider"] for m in data}
    mods = {m["modality"] for m in data}
    # A large, real, multi-provider catalog across all three modalities.
    assert len(data) >= 60
    assert mods == {"image", "video", "audio"}
    assert {
        "kling-fal",
        "fal-image",
        "replicate-image",
        "wan",
        "veo",
        "runway",
        "luma",
        "minimax",
        "suno",
        "imagen",
        "openai-image",
    } <= provs


def test_fal_direct_path_video_routes_end_to_end(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    # A fal-hosted model whose model_ref is a direct fal path (not a Kling alias).
    submit_fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "req-h",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_fal),
    )
    resp = tc.post(
        "/api/v1/media/videos",
        json={"model": "genmo/mochi-1", "prompt": "x", "duration": 5},
    )
    assert resp.status_code == 200, resp.text
    jid = resp.json()["data"]["id"]

    poll_fal = FakeFal(
        [
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"video": {"url": "https://cdn/hy.mp4"}}),
        ]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_fal)
    )
    got = tc.get(f"/api/v1/media/videos/{jid}")
    assert got.json()["data"]["status"] == "completed"
    assert got.json()["data"]["url"] == "https://cdn/hy.mp4"


def test_non_commercial_model_is_refused_before_any_charge(client):
    # MO1: HunyuanVideo is non-commercial; the gateway answers 403 before a hold.
    tc, gs, monkeypatch = client
    resp = tc.post(
        "/api/v1/media/videos",
        json={"model": "tencent/hunyuan-video", "prompt": "x", "duration": 5},
    )
    assert resp.status_code == 403, resp.text
    assert "non_commercial" in resp.text


def test_video_submit_poll_complete_meters_wallet(client):
    tc, gs, monkeypatch = client
    # Route the Kling adapter's http session to our fake fal for BOTH submit + poll.
    from app.domains.gateway import media_gateway

    submit_fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "req-1",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_fal),
    )

    resp = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "a red panda", "duration": 5},
    )
    assert resp.status_code == 200, resp.text
    jid = resp.json()["data"]["id"]
    assert resp.json()["data"]["status"] == "in_progress"

    # Wallet reserved 5s * $0.084 = 420_000 micros.
    with gs() as s:
        assert WalletService(s).balance_view("u1")["reserved_micros"] == 420_000

    poll_fal = FakeFal(
        [
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"video": {"url": "https://cdn.fal/out.mp4"}}),
        ]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_fal)
    )
    got = tc.get(f"/api/v1/media/videos/{jid}")
    assert got.status_code == 200
    assert got.json()["data"]["status"] == "completed"
    assert got.json()["data"]["url"] == "https://cdn.fal/out.mp4"
    # Settled: reservation released, actual charged.
    with gs() as s:
        bal = WalletService(s).balance_view("u1")
        assert (
            bal["reserved_micros"] == 0
            and bal["available_micros"] == 100_000_000 - 420_000
        )


def test_image_sync_returns_url_and_charges(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "img-1",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            ),
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"images": [{"url": "https://cdn.fal/panda.png"}]}),
        ]
    )
    monkeypatch.setattr(
        media_gateway, "create_image", _bind_session(media_gateway.create_image, fal)
    )
    resp = tc.post(
        "/api/v1/media/images",
        json={"model": "black-forest-labs/flux-schnell", "prompt": "a red panda"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["url"] == "https://cdn.fal/panda.png"
    assert resp.json()["data"]["cost_micros"] == 3_000
    image_id = resp.json()["data"]["id"]
    timeline = tc.get("/api/v1/media/generations?refresh_pending=false").json()["data"]
    assert timeline["generations"][0] == {
        **timeline["generations"][0],
        "id": image_id,
        "modality": "image",
        "status": "completed",
        "settlement_status": "settled",
        "effective_cost_micros": 3_000,
        "output_url": "https://cdn.fal/panda.png",
        "is_terminal": True,
    }


def test_provenance_export_is_owner_scoped_and_contains_signed_binding(client):
    tc, gs, _ = client
    with gs() as session:
        row = MediaJob(
            id="job_proof",
            correlation_id="gateway_job_proof",
            user_id="u1",
            model="runwayml/gen-4",
            modality="video",
            provider="runway",
            status="completed",
            output_url="https://cdn.example/proof.mp4",
            held_cost_micros=42,
            actual_cost_micros=42,
            identity_passport_id="psp_1",
            identity_version=3,
            identity_content_digest="ni:///sha-256;immutable",
            identity_provider="runway",
            identity_status="attested",
            identity_provenance_id="gen_ext_job_proof",
            settlement_rail="mint",
            settlement_outcome="captured",
            settlement_request_id="gateway_job_proof",
            settlement_payer_account="acct_owner",
            settlement_settled_at_ms=1234,
            settlement_verified_at_ms=1235,
            settlement_receipt={
                "seq": 7,
                "op": "hold.capture",
                "op_hash": "op",
                "amount_micros": 42,
                "hash": "hash",
                "sig": "sig",
            },
            settlement_attestation={
                "format": "mint-hold-settlement-attestation-v1",
                "payload_base64url": "eyJ2ZXJzaW9uIjoxfQ",
                "digest_sha256": "digest",
                "signer_key_id": "mint-key-1",
                "signature_hex": "signature",
            },
        )
        session.add(row)

    response = tc.get("/api/v1/media/generation/job_proof/provenance")
    assert response.status_code == 200
    proof = response.json()["data"]
    assert proof["schema"] == "menivor.media-provenance/v1"
    assert proof["generation_id"] == "job_proof"
    assert proof["correlation_id"] == "gateway_job_proof"
    assert proof["identity"]["content_digest"] == "ni:///sha-256;immutable"
    assert proof["identity"]["receipt"]["signature"] == "sig"
    assert proof["settlement_evidence"]["request_id"] == "gateway_job_proof"
    assert proof["settlement_evidence"]["principal"] == "acct_owner"
    assert proof["settlement_evidence"]["verified"] is True
    assert proof["settlement_evidence"]["verified_at_ms"] == 1235
    assert (
        proof["settlement_evidence"]["attestation"]["format"]
        == "mint-hold-settlement-attestation-v1"
    )
    assert proof["margin_source"]["source_settlement_receipt"]["receipt_hash"] == "hash"

    evidence = tc.get("/api/v1/media/generation/job_proof/evidence")
    assert evidence.status_code == 200
    evidence_body = evidence.json()["data"]
    assert evidence_body["schema"] == "railyard.settlement-evidence/v1"
    assert evidence_body["request_id"] == proof["correlation_id"]
    assert evidence_body["margin_source"]["cogs_micros"] == 42

    # A flat signed receipt or terminal database flag is not enough to claim
    # verified Mint settlement. Removing the pinned-key attestation makes the
    # public money state fail closed to held/no-evidence.
    with gs() as session:
        stored = session.get(MediaJob, "job_proof")
        stored.settlement_attestation = {}
    detail = tc.get("/api/v1/media/generation/job_proof").json()["data"]
    assert detail["settlement_status"] == "held"
    assert detail["settlement_evidence"] is None
    assert tc.get("/api/v1/media/generation/job_proof/evidence").status_code == 404

    assert tc.get("/api/v1/media/generation/missing/provenance").status_code == 404


def test_prism_video_adapter_keeps_menivor_as_wallet_and_job_owner(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    class FakePrism:
        def __init__(self):
            self.generated = []

        def generate(self, **body):
            self.generated.append(body)
            return {
                "id": "gen_prism_1",
                "correlation_id": body["correlation_id"],
                "status": "queued",
                "model": "kwaivgi/kling-v1.6",
                "provider": "kling-fal",
                "cost_micros": 400_000,
                "output_url": "",
            }

        def generation(self, generation_id, *, correlation_id=""):
            assert generation_id == "gen_prism_1"
            return {
                "id": generation_id,
                "correlation_id": correlation_id,
                "status": "completed",
                "model": "kwaivgi/kling-v1.6",
                "provider": "kling-fal",
                "cost_micros": 0,
                "output_url": "https://prism.example/out.mp4",
            }

    prism = FakePrism()
    monkeypatch.setattr(media_gateway, "prism_client_from_config", lambda: prism)

    created = tc.post(
        "/api/v1/media/videos",
        json={
            "model": "kwaivgi/kling-v1.6",
            "prompt": "a red panda",
            "duration": 5,
        },
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["id"]
    assert prism.generated[0]["max_cost_micros"] == 420_000
    assert prism.generated[0]["aspect_ratio"] == "9:16"
    with gs() as session:
        balance = WalletService(session).balance_view("u1")
        assert balance["reserved_micros"] == 420_000

    completed = tc.get(f"/api/v1/media/videos/{job_id}")
    assert completed.json()["data"]["status"] == "completed"
    assert completed.json()["data"]["url"] == "https://prism.example/out.mp4"
    assert completed.json()["data"]["cost_micros"] == 0
    with gs() as session:
        balance = WalletService(session).balance_view("u1")
        assert balance["reserved_micros"] == 0
        assert balance["available_micros"] == 100_000_000


def test_prism_missing_lookup_retains_hold_for_reconciliation(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway
    from app.domains.gateway.prism_client import PrismClientError

    class MissingPrism:
        def generate(self, **body):
            return {
                "id": "gen_missing_after_accept",
                "correlation_id": body["correlation_id"],
                "status": "queued",
                "model": "kwaivgi/kling-v1.6",
                "provider": "kling-fal",
                "cost_micros": 420_000,
            }

        def generation(self, generation_id, *, correlation_id=""):
            raise PrismClientError(404, "generation not found on this replica")

    monkeypatch.setattr(
        media_gateway, "prism_client_from_config", lambda: MissingPrism()
    )
    created = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "retain hold", "duration": 5},
    )
    job_id = created.json()["data"]["id"]
    polled = tc.get(f"/api/v1/media/videos/{job_id}")
    assert polled.status_code == 503
    with gs() as session:
        row = session.get(MediaJob, job_id)
        assert row.status == "in_progress"
        assert WalletService(session).balance_view("u1")["reserved_micros"] == 420_000


def test_prism_ambiguous_submit_persists_job_and_retains_hold(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway
    from app.domains.gateway.prism_client import PrismClientError

    class AmbiguousPrism:
        def generate(self, **_body):
            raise PrismClientError(
                502,
                "connection closed before response",
                acceptance="unknown",
            )

        def generation_by_correlation(self, _correlation_id):
            raise PrismClientError(404, "submission intent is still unresolved")

    monkeypatch.setattr(
        media_gateway, "prism_client_from_config", lambda: AmbiguousPrism()
    )
    response = tc.post(
        "/api/v1/media/videos",
        json={
            "model": "kwaivgi/kling-v1.6",
            "prompt": "persist ambiguous submission",
            "duration": 5,
        },
    )
    assert response.status_code == 502

    with gs() as session:
        row = (
            session.query(MediaJob)
            .filter(MediaJob.prompt == "persist ambiguous submission")
            .one()
        )
        assert row.status == "in_progress"
        assert row.provider == "prism:pending"
        assert row.provider_ref == ""
        assert "outcome ambiguous" in row.error
        assert WalletService(session).balance_view("u1")["reserved_micros"] == 420_000

    retry = tc.get(f"/api/v1/media/videos/{row.id}")
    assert retry.status_code == 503


def test_prism_ambiguous_submit_recovers_by_correlation_without_resubmit(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway
    from app.domains.gateway.prism_client import PrismClientError

    class RecoveringPrism:
        def __init__(self):
            self.submits = 0
            self.lookups = 0

        def generate(self, **_body):
            self.submits += 1
            raise PrismClientError(
                502,
                "response lost after provider acceptance",
                acceptance="unknown",
            )

        def generation_by_correlation(self, correlation_id):
            self.lookups += 1
            return {
                "id": "gen_recovered_by_correlation",
                "correlation_id": correlation_id,
                "status": "completed",
                "model": "kwaivgi/kling-v1.6",
                "provider": "kling-fal",
                "cost_micros": 0,
                "output_url": "https://prism.example/recovered.mp4",
            }

    prism = RecoveringPrism()
    monkeypatch.setattr(media_gateway, "prism_client_from_config", lambda: prism)
    response = tc.post(
        "/api/v1/media/videos",
        json={
            "model": "kwaivgi/kling-v1.6",
            "prompt": "recover lost submit response",
            "duration": 5,
        },
    )
    assert response.status_code == 502
    with gs() as session:
        job_id = (
            session.query(MediaJob)
            .filter(MediaJob.prompt == "recover lost submit response")
            .one()
            .id
        )

    recovered = tc.get(f"/api/v1/media/videos/{job_id}")
    assert recovered.status_code == 200
    assert recovered.json()["data"]["status"] == "completed"
    assert recovered.json()["data"]["cost_micros"] == 0
    assert prism.submits == 1
    assert prism.lookups == 1
    with gs() as session:
        row = session.get(MediaJob, job_id)
        assert row.provider_ref == "gen_recovered_by_correlation"
        assert row.output_url == "https://prism.example/recovered.mp4"
        assert WalletService(session).balance_view("u1")["reserved_micros"] == 0


def test_prism_terminal_failure_releases_hold(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    class FailedPrism:
        def generate(self, **body):
            return {
                "id": "gen_failed",
                "correlation_id": body["correlation_id"],
                "status": "queued",
                "model": "kwaivgi/kling-v1.6",
                "provider": "kling-fal",
                "cost_micros": 420_000,
            }

        def generation(self, generation_id, *, correlation_id=""):
            return {
                "id": generation_id,
                "correlation_id": correlation_id,
                "status": "failed",
                "error": "provider rejected the source image",
            }

    monkeypatch.setattr(
        media_gateway, "prism_client_from_config", lambda: FailedPrism()
    )
    created = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "fail safely", "duration": 5},
    )
    job_id = created.json()["data"]["id"]
    failed = tc.get(f"/api/v1/media/videos/{job_id}")
    assert failed.status_code == 200
    failed_view = failed.json()["data"]
    assert failed_view["status"] == "failed"
    assert failed_view["is_terminal"] is True
    assert failed_view["settlement_status"] == "released"
    assert failed_view["effective_cost_micros"] == 0
    assert failed_view["cost_micros"] == 0
    assert failed_view["error"] == "provider rejected the source image"
    assert failed_view["execution"] == {
        "kind": "prism",
        "provider_request_id": "gen_failed",
        "resumable": False,
    }
    with gs() as session:
        row = session.get(MediaJob, job_id)
        assert row.error == "provider rejected the source image"
        balance = WalletService(session).balance_view("u1")
        assert balance["reserved_micros"] == 0
        assert balance["available_micros"] == 100_000_000


def test_prism_image_adapter_preserves_explicit_zero_cost(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    class FakePrism:
        def generate(self, **body):
            assert body["max_cost_micros"] == 3_000
            return {
                "id": "gen_image",
                "correlation_id": body["correlation_id"],
                "status": "completed",
                "model": "black-forest-labs/flux-schnell",
                "provider": "fal-image",
                "cost_micros": 0,
                "output_url": "https://prism.example/out.png",
            }

    monkeypatch.setattr(media_gateway, "prism_client_from_config", lambda: FakePrism())
    response = tc.post(
        "/api/v1/media/images",
        json={
            "model": "black-forest-labs/flux-schnell",
            "prompt": "a red panda",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["model"] == "black-forest-labs/flux-schnell"
    assert data["modality"] == "image"
    assert data["status"] == "completed"
    assert data["url"] == "https://prism.example/out.png"
    assert data["cost_micros"] == 0
    assert data["id"]
    with gs() as session:
        balance = WalletService(session).balance_view("u1")
        assert balance["reserved_micros"] == 0
        assert balance["available_micros"] == 100_000_000


def test_openai_image_provider_routes_and_charges(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
    from app.domains.gateway import media_gateway

    fal = FakeFal([_Resp(200, {"data": [{"url": "https://oai/panda.png"}]})])
    monkeypatch.setattr(
        media_gateway, "create_image", _bind_session(media_gateway.create_image, fal)
    )
    resp = tc.post(
        "/api/v1/media/images",
        json={"model": "openai/gpt-image-1", "prompt": "a red panda"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["url"] == "https://oai/panda.png"
    assert resp.json()["data"]["cost_micros"] == 40_000
    # Wallet settled the 40_000 charge, nothing left reserved.
    with gs() as s:
        bal = WalletService(s).balance_view("u1")
        assert (
            bal["reserved_micros"] == 0
            and bal["available_micros"] == 100_000_000 - 40_000
        )


def test_gateway_emits_success_only_billing_metrics(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    jobs: list = []
    debits: list = []
    orig_create = media_gateway.create_video  # capture unwrapped before monkeypatching
    orig_poll = media_gateway.poll_video
    monkeypatch.setattr(
        media_gateway,
        "_metric_job",
        lambda modality, provider, status: jobs.append((modality, provider, status)),
    )
    monkeypatch.setattr(
        media_gateway, "_metric_debit", lambda micros: debits.append(micros)
    )

    # A completed video emits (video, provider, completed) + one gateway debit.
    submit_fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "rq",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway, "create_video", _bind_session(orig_create, submit_fal)
    )
    jid = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "x", "duration": 5},
    ).json()["data"]["id"]

    poll_fal = FakeFal(
        [
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"video": {"url": "https://cdn/o.mp4"}}),
        ]
    )
    monkeypatch.setattr(media_gateway, "poll_video", _bind_session(orig_poll, poll_fal))
    tc.get(f"/api/v1/media/videos/{jid}")

    assert ("video", "kling-fal", "completed") in jobs
    assert debits == [420_000]  # exactly one debit, equal to the settled charge

    # A polling/auth transport error is not proof that accepted work failed.
    debits.clear()
    submit2 = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "rq2",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway, "create_video", _bind_session(orig_create, submit2)
    )
    jid2 = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "x", "duration": 5},
    ).json()["data"]["id"]
    # A 401 while polling retains the accepted job and reservation for recovery.
    poll2 = FakeFal([_Resp(401, {"detail": "bad key"})])
    monkeypatch.setattr(media_gateway, "poll_video", _bind_session(orig_poll, poll2))
    retry = tc.get(f"/api/v1/media/videos/{jid2}")

    assert retry.status_code == 502
    assert ("video", "kling-fal", "failed") not in jobs
    assert debits == []  # uncertain accepted work is not charged or released yet
    with gs() as session:
        row = session.get(MediaJob, jid2)
        assert row.status == "in_progress"
        assert WalletService(session).balance_view("u1")["reserved_micros"] == 420_000


def test_replicate_image_provider_routes(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8-key")
    from app.domains.gateway import media_gateway

    fal = FakeFal(
        [_Resp(201, {"status": "succeeded", "output": ["https://r8/panda.png"]})]
    )
    monkeypatch.setattr(
        media_gateway, "create_image", _bind_session(media_gateway.create_image, fal)
    )
    resp = tc.post(
        "/api/v1/media/images",
        json={
            "model": "black-forest-labs/flux-schnell-replicate",
            "prompt": "a red panda",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["url"] == "https://r8/panda.png"
    assert resp.json()["data"]["cost_micros"] == 3_000


def test_imagen_image_provider_routes(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("GEMINI_API_KEY", "gk-key")
    from app.domains.gateway import media_gateway

    fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "predictions": [
                        {"bytesBase64Encoded": "ZZZZ", "mimeType": "image/png"}
                    ]
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway, "create_image", _bind_session(media_gateway.create_image, fal)
    )
    resp = tc.post(
        "/api/v1/media/images",
        json={"model": "google/imagen-4-fast", "prompt": "a red panda"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["url"] == "data:image/png;base64,ZZZZ"
    assert resp.json()["data"]["cost_micros"] == 20_000


def test_unknown_model_404(client):
    tc, _, _ = client
    assert (
        tc.post(
            "/api/v1/media/videos", json={"model": "nope/x", "prompt": "y"}
        ).status_code
        == 404
    )


def test_missing_provider_credentials_503_refunds(client):
    tc, gs, monkeypatch = client
    # Wan is wired to Replicate but REPLICATE_API_TOKEN is unset -> 503 + no net charge.
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    resp = tc.post(
        "/api/v1/media/videos",
        json={"model": "wan/wan-2.2", "prompt": "x", "duration": 4},
    )
    assert resp.status_code == 503
    with gs() as s:
        assert WalletService(s).balance_view("u1")["reserved_micros"] == 0


def test_credits_and_usage_and_generation(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    # Submit + complete a video so there's usage to report.
    submit_fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "rq",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_fal),
    )
    jid = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "x", "duration": 5},
    ).json()["data"]["id"]

    poll_fal = FakeFal(
        [
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"video": {"url": "https://cdn/out.mp4"}}),
        ]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_fal)
    )
    tc.get(f"/api/v1/media/videos/{jid}")

    # Credits: balance reflects the settled 420_000 charge + lifetime spend.
    credits = tc.get("/api/v1/media/credits").json()["data"]
    assert credits["available_micros"] == 100_000_000 - 420_000
    assert credits["total_gateway_spend_micros"] == 420_000

    # Usage by model.
    usage = tc.get("/api/v1/media/usage").json()["data"]["usage"]
    assert usage[0]["model"] == "kwaivgi/kling-v1.6"
    assert (
        usage[0]["jobs"] == 1
        and usage[0]["spend_micros"] == 420_000
        and usage[0]["seconds"] == 5
    )

    # Per-generation detail.
    gen = tc.get(f"/api/v1/media/generation/{jid}").json()["data"]
    assert (
        gen["id"] == jid
        and gen["status"] == "completed"
        and gen["actual_cost_micros"] == 420_000
    )
    assert gen["correlation_id"] == f"gateway_{jid}"
    assert gen["settlement_status"] == "settled"

    # The durable list is the same canonical DTO and survives a new request.
    page = tc.get(
        "/api/v1/media/generations?refresh_pending=false&modality=video"
    ).json()["data"]
    assert page["generations"][0] == gen
    assert page["has_more"] is False


def test_generation_timeline_reconciles_pending_jobs(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    submit_fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "recover-1",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_fal),
    )
    job_id = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "recover", "duration": 5},
    ).json()["data"]["id"]

    poll_fal = FakeFal(
        [
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"video": {"url": "https://cdn/recovered.mp4"}}),
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "poll_video",
        _bind_session(media_gateway.poll_video, poll_fal),
    )

    page = tc.get("/api/v1/media/generations").json()["data"]
    recovered = next(row for row in page["generations"] if row["id"] == job_id)
    assert recovered["status"] == "completed"
    assert recovered["output_url"] == "https://cdn/recovered.mp4"
    assert recovered["settlement_status"] == "settled"
    with gs() as session:
        balance = WalletService(session).balance_view("u1")
        assert balance["reserved_micros"] == 0
        assert balance["available_micros"] == 100_000_000 - 420_000


def test_generation_detail_resumes_pending_job_and_returns_the_canonical_view(client):
    tc, _, monkeypatch = client
    from app.domains.gateway import media_gateway

    submit_fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "resume-detail-1",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_fal),
    )
    submitted = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "resume", "duration": 5},
    ).json()["data"]
    assert submitted["execution"] == {
        "kind": "direct",
        "provider_request_id": "resume-detail-1",
        "resumable": True,
    }

    poll_fal = FakeFal(
        [
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"video": {"url": "https://cdn/resumed-detail.mp4"}}),
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "poll_video",
        _bind_session(media_gateway.poll_video, poll_fal),
    )
    resumed = tc.get(f"/api/v1/media/generation/{submitted['id']}").json()["data"]

    assert resumed["status"] == "completed"
    assert resumed["output_url"] == "https://cdn/resumed-detail.mp4"
    assert resumed["url"] == resumed["output_url"]
    assert resumed["effective_cost_micros"] == resumed["cost_micros"] == 420_000
    assert resumed["execution"] == {
        "kind": "direct",
        "provider_request_id": "resume-detail-1",
        "resumable": False,
    }
    assert resumed["provider_request_id"] == "resume-detail-1"
    assert resumed["settlement_status"] == "settled"


def test_background_reconciliation_recovers_without_an_open_client(client):
    tc, gs, monkeypatch = client
    from app.domains.gateway import media_gateway

    submit_fal = FakeFal(
        [
            _Resp(
                200,
                {
                    "request_id": "background-1",
                    "status_url": "https://q/s",
                    "response_url": "https://q/r",
                },
            )
        ]
    )
    original_create = media_gateway.create_video
    original_poll = media_gateway.poll_video
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(original_create, submit_fal),
    )
    job_id = tc.post(
        "/api/v1/media/videos",
        json={"model": "kwaivgi/kling-v1.6", "prompt": "recover", "duration": 5},
    ).json()["data"]["id"]

    poll_fal = FakeFal(
        [
            _Resp(200, {"status": "COMPLETED"}),
            _Resp(200, {"video": {"url": "https://cdn/background.mp4"}}),
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "poll_video",
        _bind_session(original_poll, poll_fal),
    )
    summary = media_gateway.run_pending_reconciliation(limit=10, session_factory=gs)

    assert summary == {
        "scanned": 1,
        "advanced": 1,
        "completed": 1,
        "failed": 0,
        "errored": 0,
    }
    with gs() as session:
        row = session.get(media_jobs.MediaJob, job_id)
        assert row is not None
        assert row.status == "completed"
        assert row.output_url == "https://cdn/background.mp4"


def test_generation_timeline_validates_filters(client):
    tc, _, _ = client
    assert tc.get("/api/v1/media/generations?status=nope").status_code == 422
    assert tc.get("/api/v1/media/generations?modality=text").status_code == 422


def test_generation_unknown_404(client):
    tc, _, _ = client
    assert tc.get("/api/v1/media/generation/nope").status_code == 404


def test_runway_provider_routes_to_real_adapter(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("RUNWAY_API_SECRET", "rw-key")
    from app.domains.gateway import media_gateway

    submit_rw = FakeFal([_Resp(200, {"id": "rw-task-1"})])
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_rw),
    )
    # Runway is image-to-video -> supply an image_url.
    resp = tc.post(
        "/api/v1/media/videos",
        json={
            "model": "runwayml/gen-4",
            "prompt": "dolly in",
            "duration": 5,
            "image_url": "https://img/first.png",
        },
    )
    assert resp.status_code == 200, resp.text
    jid = resp.json()["data"]["id"]

    poll_rw = FakeFal(
        [_Resp(200, {"status": "SUCCEEDED", "output": ["https://cdn.runway/o.mp4"]})]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_rw)
    )
    got = tc.get(f"/api/v1/media/videos/{jid}")
    assert got.json()["data"]["status"] == "completed"
    assert got.json()["data"]["url"] == "https://cdn.runway/o.mp4"


def test_veo_provider_routes_to_real_adapter(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("GEMINI_API_KEY", "gk-key")
    from app.domains.gateway import media_gateway

    # Veo submit returns a long-running operation name as the provider_ref.
    submit_veo = FakeFal([_Resp(200, {"name": "models/veo-3.1/operations/op-1"})])
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_veo),
    )
    resp = tc.post(
        "/api/v1/media/videos",
        json={"model": "google/veo-3.1-lite", "prompt": "a red panda", "duration": 8},
    )
    assert resp.status_code == 200, resp.text
    jid = resp.json()["data"]["id"]

    poll_veo = FakeFal(
        [
            _Resp(
                200,
                {
                    "done": True,
                    "response": {
                        "generateVideoResponse": {
                            "generatedSamples": [
                                {"video": {"uri": "https://cdn.g/veo.mp4"}}
                            ]
                        }
                    },
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_veo)
    )
    got = tc.get(f"/api/v1/media/videos/{jid}")
    assert got.json()["data"]["status"] == "completed"
    assert got.json()["data"]["url"] == "https://cdn.g/veo.mp4"


def test_luma_provider_routes_to_real_adapter(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("LUMAAI_API_KEY", "lm-key")
    from app.domains.gateway import media_gateway

    submit_luma = FakeFal([_Resp(200, {"id": "luma-gen-1", "state": "queued"})])
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_luma),
    )
    resp = tc.post(
        "/api/v1/media/videos",
        json={
            "model": "lumalabs/dream-machine",
            "prompt": "a red panda",
            "duration": 5,
        },
    )
    assert resp.status_code == 200, resp.text
    jid = resp.json()["data"]["id"]

    poll_luma = FakeFal(
        [
            _Resp(
                200,
                {"state": "completed", "assets": {"video": "https://cdn.luma/o.mp4"}},
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_luma)
    )
    got = tc.get(f"/api/v1/media/videos/{jid}")
    assert got.json()["data"]["status"] == "completed"
    assert got.json()["data"]["url"] == "https://cdn.luma/o.mp4"


def test_minimax_provider_routes_with_two_step_retrieve(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("MINIMAX_API_KEY", "mm-key")
    from app.domains.gateway import media_gateway

    submit_mm = FakeFal(
        [_Resp(200, {"task_id": "mm-1", "base_resp": {"status_code": 0}})]
    )
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_mm),
    )
    resp = tc.post(
        "/api/v1/media/videos",
        json={"model": "minimax/hailuo-02", "prompt": "a red panda", "duration": 6},
    )
    assert resp.status_code == 200, resp.text
    jid = resp.json()["data"]["id"]

    # poll -> Success (file_id) then the file-retrieve step resolves the url.
    poll_mm = FakeFal(
        [
            _Resp(
                200,
                {
                    "status": "Success",
                    "file_id": "f-1",
                    "base_resp": {"status_code": 0},
                },
            ),
            _Resp(
                200,
                {
                    "file": {"download_url": "https://cdn.mm/o.mp4"},
                    "base_resp": {"status_code": 0},
                },
            ),
        ]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_mm)
    )
    got = tc.get(f"/api/v1/media/videos/{jid}")
    assert got.json()["data"]["status"] == "completed"
    assert got.json()["data"]["url"] == "https://cdn.mm/o.mp4"


def test_wan_provider_routes_to_replicate(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8-key")
    from app.domains.gateway import media_gateway

    submit_wan = FakeFal(
        [
            _Resp(
                201,
                {
                    "id": "pred-1",
                    "status": "starting",
                    "urls": {"get": "https://api.replicate.com/v1/predictions/pred-1"},
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway,
        "create_video",
        _bind_session(media_gateway.create_video, submit_wan),
    )
    resp = tc.post(
        "/api/v1/media/videos",
        json={"model": "wan/wan-2.2", "prompt": "a red panda", "duration": 5},
    )
    assert resp.status_code == 200, resp.text
    jid = resp.json()["data"]["id"]

    poll_wan = FakeFal(
        [_Resp(200, {"status": "succeeded", "output": "https://cdn.r8/o.mp4"})]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_wan)
    )
    got = tc.get(f"/api/v1/media/videos/{jid}")
    assert got.json()["data"]["status"] == "completed"
    assert got.json()["data"]["url"] == "https://cdn.r8/o.mp4"


def test_audio_provider_routes_to_suno(client):
    tc, gs, monkeypatch = client
    monkeypatch.setenv("SUNO_API_KEY", "sn-key")
    from app.domains.gateway import media_gateway

    submit_suno = FakeFal([_Resp(200, {"code": 200, "data": {"taskId": "sn-1"}})])
    monkeypatch.setattr(
        media_gateway,
        "create_audio",
        _bind_session(media_gateway.create_audio, submit_suno),
    )
    resp = tc.post(
        "/api/v1/media/audio",
        json={"model": "suno/v4", "prompt": "lofi beat", "instrumental": True},
    )
    assert resp.status_code == 200, resp.text
    jid = resp.json()["data"]["id"]
    assert resp.json()["data"]["status"] == "in_progress"

    # Wallet reserved the flat clip price (80_000).
    with gs() as s:
        assert WalletService(s).balance_view("u1")["reserved_micros"] == 80_000

    poll_suno = FakeFal(
        [
            _Resp(
                200,
                {
                    "code": 200,
                    "data": {
                        "status": "SUCCESS",
                        "response": {
                            "sunoData": [{"audioUrl": "https://cdn.suno/o.mp3"}]
                        },
                    },
                },
            )
        ]
    )
    monkeypatch.setattr(
        media_gateway, "poll_video", _bind_session(media_gateway.poll_video, poll_suno)
    )
    got = tc.get(f"/api/v1/media/audio/{jid}")
    assert got.json()["data"]["status"] == "completed"
    assert got.json()["data"]["url"] == "https://cdn.suno/o.mp3"
    with gs() as s:
        bal = WalletService(s).balance_view("u1")
        assert (
            bal["reserved_micros"] == 0
            and bal["available_micros"] == 100_000_000 - 80_000
        )


def test_audio_model_in_catalog(client):
    tc, _, _ = client
    data = tc.get("/api/v1/media/models?modality=audio").json()["data"]["models"]
    ids = {m["id"] for m in data}
    assert "suno/v4" in ids and all(m["modality"] == "audio" for m in data)


def _bind_session(fn, fake):
    """Wrap a gateway fn to inject the fake fal http session."""

    def _wrapped(session, **kwargs):
        kwargs["session_http"] = fake
        return fn(session, **kwargs)

    return _wrapped
