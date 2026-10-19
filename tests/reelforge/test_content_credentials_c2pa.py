"""M7.1: a signed C2PA manifest on every final MP4.

* The manifest is found on the output by ``c2patool`` (when installed) and by
  the c2pa-python Reader; it marks the video as AI-generated
  (IPTC ``trainedAlgorithmicMedia``), names Menivor, and carries the content id.
* Signing keeps the MN5 metadata tags and does not re-encode the streams.
* ``tag_final`` signs before the stored copy is replaced; with the layer off,
  only the MN5 tag is written.
* A changed file fails validation. The self-issued signer is reported as not
  trusted, never as trusted.
* The public check endpoint answers for signed, unsigned, empty, wrong-type
  and oversized uploads.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.exception import HttpException
from app.services import provenance
from app.services.compose import provenance as cc
from app.utils import utils

pytest.importorskip("c2pa")

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)
needs_c2patool = pytest.mark.skipif(shutil.which("c2patool") is None, reason="c2patool not installed")


@pytest.fixture(autouse=True)
def _key_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(cc.ENV_KEY_DIR, str(tmp_path / "c2pa-keys"))
    for name in (cc.ENV_ENABLED, cc.ENV_CERT_CHAIN, cc.ENV_PRIVATE_KEY, cc.ENV_TSA_URL):
        monkeypatch.delenv(name, raising=False)


def _make_mp4(path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
        check=True,
    )


def _stream_md5(path: str) -> str:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0", "-c", "copy", "-f", "md5", "-"],
        capture_output=True, check=True,
    )
    return out.stdout.decode().strip()


@pytest.fixture()
def signed_mp4(tmp_path):
    video = str(tmp_path / "final.mp4")
    _make_mp4(video)
    provenance.tag(video, "job42")
    cc.sign_mp4(video, "job42")
    return video


@needs_ffmpeg
def test_signed_manifest_marks_ai_and_keeps_mn5_tags_without_reencode(tmp_path):
    video = str(tmp_path / "final.mp4")
    _make_mp4(video)
    provenance.tag(video, "job42")
    before = _stream_md5(video)

    summary = cc.sign_mp4(video, "job42")

    assert summary["present"] and summary["valid"]
    assert summary["ai_generated"] and summary["made_with_menivor"]
    assert summary["digital_source_types"] == [cc.DIGITAL_SOURCE_TYPE_URI]
    assert summary["content_id"] == "job42"
    assert summary["claim_generator"] == ["Menivor"]
    assert summary["trusted"] is False  # self-issued signer: stated, not hidden
    assert "signingCredential.untrusted" in summary["validation_codes"]
    assert cc.read_manifest(video) == summary
    assert provenance.read_tags(video)["ai_generated"] == "true"
    assert _stream_md5(video) == before


@needs_ffmpeg
@needs_c2patool
def test_c2patool_finds_the_manifest_on_the_output(signed_mp4):
    proc = subprocess.run(["c2patool", signed_mp4], capture_output=True, check=True)
    store = json.loads(proc.stdout)
    manifest = store["manifests"][store["active_manifest"]]
    labels = {a["label"]: a["data"] for a in manifest["assertions"]}
    actions = (labels.get("c2pa.actions.v2") or labels["c2pa.actions"])["actions"]
    assert actions[0]["action"] == "c2pa.created"
    assert actions[0]["digitalSourceType"] == cc.DIGITAL_SOURCE_TYPE_URI
    assert labels[cc.MENIVOR_ASSERTION]["content_id"] == "job42"


@needs_ffmpeg
def test_resigning_on_retry_is_safe(signed_mp4):
    again = cc.sign_mp4(signed_mp4, "job42")
    assert again["present"] and again["valid"] and again["content_id"] == "job42"


@needs_ffmpeg
def test_unsigned_file_has_no_manifest(tmp_path):
    video = str(tmp_path / "plain.mp4")
    _make_mp4(video)
    assert cc.read_manifest(video)["present"] is False
    assert cc.has_manifest(video) is False


@needs_ffmpeg
def test_changed_file_fails_validation(signed_mp4):
    with open(signed_mp4, "r+b") as fh:
        fh.seek(-64, 2)
        byte = fh.read(1)
        fh.seek(-64, 2)
        fh.write(bytes([byte[0] ^ 0xFF]))
    summary = cc.read_manifest(signed_mp4)
    assert summary["present"] is True
    assert summary["valid"] is False


def test_sign_refuses_a_missing_file(tmp_path):
    with pytest.raises(cc.ContentCredentialsError):
        cc.sign_mp4(str(tmp_path / "nope.mp4"), "j")


def test_self_issued_signer_is_created_once_and_private(tmp_path):
    first = cc.load_signing_material()
    second = cc.load_signing_material()
    assert first == second and first.source == "self_issued"
    bundle = tmp_path / "c2pa-keys" / cc.SELF_ISSUED_BUNDLE
    assert oct(bundle.stat().st_mode & 0o777) == "0o600"
    assert first.cert_chain_pem.count(b"BEGIN CERTIFICATE") == 2
    assert b"PRIVATE KEY" not in first.cert_chain_pem


@needs_ffmpeg
def test_configured_certificate_is_used(tmp_path, monkeypatch, signed_mp4):
    material = cc.load_signing_material()
    chain, key = tmp_path / "chain.pem", tmp_path / "key.pem"
    chain.write_bytes(material.cert_chain_pem)
    key.write_bytes(material.private_key_pem)
    monkeypatch.setenv(cc.ENV_CERT_CHAIN, str(chain))
    monkeypatch.setenv(cc.ENV_PRIVATE_KEY, str(key))
    assert cc.load_signing_material().source == "configured"
    assert cc.sign_mp4(signed_mp4, "job42")["valid"]


def test_half_configured_certificate_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(cc.ENV_CERT_CHAIN, str(tmp_path / "chain.pem"))
    with pytest.raises(cc.ContentCredentialsError):
        cc.load_signing_material()


def _fake_r2(monkeypatch, check):
    uploads: list[str] = []

    class _R2:
        def upload_file(self, path, key, content_type):  # noqa: ANN001
            check(path)
            uploads.append(key)

    monkeypatch.setattr("app.services.storage.r2.get_r2_client", lambda: _R2())
    return uploads


@needs_ffmpeg
def test_tag_final_signs_before_the_stored_copy_is_replaced(tmp_path, monkeypatch):
    video = str(tmp_path / "final.mp4")
    _make_mp4(video)

    def _check(path):
        assert provenance.is_tagged(path)
        assert cc.read_manifest(path)["content_id"] == "j1"

    uploads = _fake_r2(monkeypatch, _check)
    provenance.tag_final("j1", {"final_video": video, "final_key": "jobs/j1/final.mp4"})
    assert uploads == ["jobs/j1/final.mp4"]


@needs_ffmpeg
def test_layer_off_writes_only_the_mn5_tag(tmp_path, monkeypatch):
    monkeypatch.setenv(cc.ENV_ENABLED, "false")
    video = str(tmp_path / "final.mp4")
    _make_mp4(video)
    _fake_r2(monkeypatch, lambda path: None)
    provenance.tag_final("j1", {"final_video": video, "final_key": "k"})
    assert provenance.is_tagged(video)
    assert cc.has_manifest(video) is False


def test_signing_failure_fails_the_stage(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(provenance, "tag", lambda path, content_id: None)
    with pytest.raises(provenance.ProvenanceError):
        provenance.tag_final("j1", {"final_video": str(video), "final_key": "k"})


# --------------------------------------------------------------------------- #
# Public check endpoint
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch):
    from app.domains.compliance import content_credentials_router as ccr

    buckets: list[str] = []
    monkeypatch.setattr(ccr, "enforce_rate_limit", lambda request, bucket, limit, window_s: buckets.append(bucket))
    app = FastAPI()
    app.include_router(ccr.router)

    def _handler(request, exc: HttpException):
        return JSONResponse(status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message))

    app.add_exception_handler(HttpException, _handler)
    test_client = TestClient(app)
    test_client.buckets = buckets  # type: ignore[attr-defined]
    return test_client


URL = "/api/v1/legal/content-credentials"


@needs_ffmpeg
def test_check_endpoint_reports_a_signed_menivor_video(client, signed_mp4):
    with open(signed_mp4, "rb") as fh:
        resp = client.post(URL, files={"file": ("reel.mp4", fh, "video/mp4")})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["present"] and data["valid"] and data["ai_generated"] and data["made_with_menivor"]
    assert data["content_id"] == "job42"
    # The self-issued signer is not on a trust list, so the maker is not confirmed.
    assert data["trusted"] is False
    assert data["verdict"].startswith("Says it was signed by Menivor and marked as AI-generated.")
    assert "cannot be confirmed" in data["verdict"]
    assert client.buckets == ["legal:c2pa-check"]


def test_verdict_confirms_the_maker_only_for_a_trusted_signer():
    from app.domains.compliance.content_credentials_router import _verdict

    forged = {"present": True, "valid": True, "trusted": False, "made_with_menivor": True, "ai_generated": True}
    assert "cannot be confirmed" in _verdict(forged)
    assert not _verdict(forged).startswith("Signed by Menivor")
    trusted = {**forged, "trusted": True}
    assert _verdict(trusted) == "Signed by Menivor and marked as AI-generated. The signature is valid."


@needs_ffmpeg
def test_check_endpoint_reports_an_unsigned_video(client, tmp_path):
    video = str(tmp_path / "plain.mp4")
    _make_mp4(video)
    with open(video, "rb") as fh:
        resp = client.post(URL, files={"file": ("plain.mp4", fh, "video/mp4")})
    assert resp.status_code == 200
    assert resp.json()["data"]["present"] is False
    assert resp.json()["data"]["verdict"] == "No Content Credentials found in this file."


def test_check_endpoint_refuses_bad_uploads(client, monkeypatch):
    from app.domains.compliance import content_credentials_router as ccr

    assert client.post(URL, files={"file": ("a.mp4", b"", "video/mp4")}).status_code == 400
    assert client.post(URL, files={"file": ("a.png", b"png", "image/png")}).status_code == 400
    assert client.post(URL, files={"file": ("a.mp4", b"not a video", "video/mp4")}).status_code == 400
    monkeypatch.setattr(ccr, "MAX_UPLOAD_BYTES", 4)
    assert client.post(URL, files={"file": ("a.mp4", b"0123456789", "video/mp4")}).status_code == 413
