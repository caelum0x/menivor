"""Menivor ↔ Identity Lock provenance boundary (no network/credentials)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.domains.gateway import media_gateway
from app.domains.gateway.identity_lock_client import IdentityLockClient
from app.domains.wallet.mint_client import MintClient
from app.models.db.media_jobs import MediaJob


def _identity_transport(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.method == "GET" and path == "/v1/passports":
        assert request.url.params["owner"] == "acct_owner"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "psp_1", "owner": "acct_owner", "kind": "character", "status": "locked", "version": 3},
                    {"id": "draft_1", "owner": "acct_owner", "kind": "style", "status": "draft", "version": 1},
                ]
            },
        )
    if request.method == "GET" and path == "/v1/passports/psp_1":
        return httpx.Response(200, json={"data": {"id": "psp_1", "owner": "acct_owner"}})
    if request.method == "POST" and path == "/v1/passports/psp_1/resolve":
        body = json.loads(request.content)
        assert body == {"provider": "runway", "modality": "video", "version": 3}
        return httpx.Response(
            200,
            json={
                "data": {
                    "passport_id": "psp_1",
                    "version": 3,
                    "provider": "runway",
                    "modality": "video",
                    "reference_images": ["https://owned/ref.png"],
                    "style_prompt": "cinematic denim jacket",
                }
            },
        )
    if request.method == "GET" and path == "/v1/passports/psp_1/versions/3":
        return httpx.Response(
            200,
            json={
                "data": {
                    "passport_id": "psp_1",
                    "version": 3,
                    "status": "locked",
                    "content_digest": "ni:///sha-256;immutable",
                }
            },
        )
    if request.method == "POST" and path == "/v1/passports/psp_1/attest":
        body = json.loads(request.content)
        assert body["payment_evidence"]["payer_account"] == "acct_owner"
        assert body["payment_evidence"]["receipt"]["operation"] == "hold.capture"
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "gen_ext_job1",
                    "passport_content_digest": "ni:///sha-256;immutable",
                }
            },
        )
    return httpx.Response(404, json={"error": {"message": "not found"}})


def test_identity_client_resolves_owner_locked_digest_and_attests():
    client = IdentityLockClient(
        "https://identity.test",
        "secret",
        transport=httpx.MockTransport(_identity_transport),
    )
    binding = client.prepare(
        passport_id="psp_1",
        provider="runway",
        modality="video",
        payer_account="acct_owner",
        version=3,
    )
    assert binding.content_digest == "ni:///sha-256;immutable"
    assert binding.conditioning["reference_images"] == ["https://owned/ref.png"]
    record = client.attest(
        binding,
        output_ref="https://cdn/out.mp4",
        asset_hash=None,
        request_id="job1",
        payer_account="acct_owner",
        receipt={
            "seq": 7,
            "op": "hold.capture",
            "op_hash": "op",
            "amount_micros": 42,
            "hash": "hash",
            "sig": "sig",
        },
        settled_at_ms=1234,
    )
    assert record["id"] == "gen_ext_job1"


def test_identity_client_lists_only_exact_locked_owned_heads():
    client = IdentityLockClient(
        "https://identity.test",
        "secret",
        transport=httpx.MockTransport(_identity_transport),
    )
    options = client.list_locked(owner="acct_owner")
    assert len(options) == 1
    assert options[0].passport_id == "psp_1"
    assert options[0].version == 3
    assert options[0].content_digest == "ni:///sha-256;immutable"


def test_mint_client_requires_and_decodes_signed_capture_receipt():
    receipt = {
        "seq": 8,
        "op": "hold.capture",
        "op_hash": "op",
        "amount_micros": 55,
        "balance_after_micros": 100,
        "prev_hash": "prev",
        "hash": "hash",
        "sig": "sig",
    }
    encoded = base64.urlsafe_b64encode(json.dumps(receipt).encode()).decode().rstrip("=")

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/holds/hold_1/capture"
        return httpx.Response(
            200,
            json={"success": True, "data": {"hold_id": "hold_1"}},
            headers={"AITP-Receipt": encoded},
        )

    client = MintClient(
        "https://mint.test",
        "key",
        "acct_treasury",
        transport=httpx.MockTransport(transport),
    )
    _, decoded = client.capture_hold_with_receipt(
        "hold_1", 55, "acct_treasury", "idem", "digest"
    )
    assert decoded == receipt


def test_identity_attestation_reuses_verified_capture_without_recapturing(monkeypatch):
    receipt = {
        "seq": 9,
        "op": "hold.capture",
        "op_hash": "op",
        "amount_micros": 84_000,
        "hash": "hash",
        "sig": "sig",
    }

    class Session:
        commits = 0

        def commit(self):
            self.commits += 1

    class Identity:
        attestations = 0

        def attest(self, binding, **kwargs):
            self.attestations += 1
            assert binding.content_digest == "ni:///sha-256;immutable"
            assert kwargs["receipt"] == receipt
            return {
                "id": "gen_ext_job1",
                "passport_content_digest": "ni:///sha-256;immutable",
            }

    identity = Identity()
    monkeypatch.setattr(
        "app.domains.gateway.identity_lock_client.identity_lock_client_from_config",
        lambda: identity,
    )
    row = MediaJob(
        id="job1",
        user_id="u1",
        model="runwayml/gen-4",
        modality="video",
        provider="runway",
        output_url="https://cdn/out.mp4",
        held_cost_micros=84_000,
        actual_cost_micros=0,
        identity_passport_id="psp_1",
        identity_version=3,
        identity_content_digest="ni:///sha-256;immutable",
        identity_provider="runway",
        identity_status="resolved",
        mint_hold_id="hold_1",
        settlement_request_id="job1",
        settlement_payer_account="acct_owner",
        settlement_rail="mint",
        settlement_outcome="captured",
        settlement_receipt=receipt,
        settlement_attestation={"format": "mint-hold-settlement-attestation-v1"},
        settlement_settled_at_ms=1234,
        settlement_verified_at_ms=1234,
    )
    session = Session()

    media_gateway._settle_and_attest_identity(session, row, 84_000)
    assert session.commits == 1
    assert identity.attestations == 1
    assert row.identity_status == "attested"
    assert row.identity_provenance_id == "gen_ext_job1"

    # Recovery/retry reuses persisted proof and only replays identity work.
    media_gateway._settle_and_attest_identity(session, row, 84_000)
    assert session.commits == 1
    assert identity.attestations == 2


def test_video_conditioning_requires_reference_and_is_deterministic():
    prompt, image = media_gateway._condition_video(
        "walk through rain",
        "",
        {
            "reference_images": ["https://owned/ref.png"],
            "style_prompt": "cinematic",
            "text_directives": ["same denim jacket"],
            "negative_prompt": "identity drift",
        },
    )
    assert image == "https://owned/ref.png"
    assert prompt == (
        "walk through rain. cinematic. same denim jacket. Avoid: identity drift"
    )
    with pytest.raises(media_gateway.GatewayError):
        media_gateway._condition_video("walk", "", {"style_prompt": "cinematic"})
