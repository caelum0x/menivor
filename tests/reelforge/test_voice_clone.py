"""Unit tests for the ElevenLabs Instant Voice Clone client.

These tests never touch the network: ``requests`` on the module under test is
monkeypatched with a fake that records the outgoing multipart request and returns
scripted responses. Coverage:

  * clone_voice — multipart fields (name, description, files), xi-api-key header,
    success shape, transient retry, and error mapping (401/422/429).
  * delete_voice — success, idempotent 404, auth error.
  * get_shared_or_user_voice — success payload.
  * config-free API-key resolution via the environment variable.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from app.services.tts import voice_clone


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Optional[dict[str, Any]] = None,
        text: str = "",
        reason: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.reason = reason

    def json(self) -> Any:
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


class _FakeRequestException(Exception):
    pass


class _FakeRequests:
    """Minimal stand-in for the ``requests`` module used by voice_clone."""

    RequestException = _FakeRequestException

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[Any] = []

    def _next(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("no scripted response left")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._next("POST", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self._next("DELETE", url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._next("GET", url, **kwargs)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def fake_requests(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(voice_clone, "requests", fake)
    # Deterministic key resolution independent of any real config/env.
    monkeypatch.setattr(voice_clone, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(voice_clone, "_base_url", lambda: "https://api.elevenlabs.io")
    return fake


@pytest.fixture()
def sample_file(tmp_path):
    path = tmp_path / "voice_sample.mp3"
    path.write_bytes(b"ID3fakeaudio-bytes")
    return str(path)


# --------------------------------------------------------------------------- #
# clone_voice — success + multipart shape
# --------------------------------------------------------------------------- #
def test_clone_voice_success_shape_and_multipart(fake_requests, sample_file):
    fake_requests.responses = [
        _FakeResponse(200, {"voice_id": "prov_abc123", "requires_verification": False})
    ]

    result = voice_clone.clone_voice(
        "My Brand Voice", [sample_file], description="creator narration"
    )

    assert result == {"voice_id": "prov_abc123", "name": "My Brand Voice"}

    assert len(fake_requests.calls) == 1
    call = fake_requests.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.elevenlabs.io/v1/voices/add"

    # xi-api-key header present, no hardcoded secret.
    assert call["headers"]["xi-api-key"] == "test-key"

    # Form fields: name + description.
    assert call["data"]["name"] == "My Brand Voice"
    assert call["data"]["description"] == "creator narration"

    # files[] uses the "files" field and carries the sample basename.
    files = call["files"]
    assert isinstance(files, list) and len(files) == 1
    field_name, (filename, _handle) = files[0]
    assert field_name == "files"
    assert filename == "voice_sample.mp3"


def test_clone_voice_multiple_samples_share_files_field(fake_requests, tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"s{i}.wav"
        p.write_bytes(b"riff-data")
        paths.append(str(p))
    fake_requests.responses = [_FakeResponse(200, {"voice_id": "vid"})]

    voice_clone.clone_voice("Multi", paths)

    files = fake_requests.calls[0]["files"]
    assert [f[0] for f in files] == ["files", "files", "files"]


def test_clone_voice_optional_labels_json_encoded(fake_requests, sample_file):
    fake_requests.responses = [_FakeResponse(200, {"voice_id": "vid"})]

    voice_clone.clone_voice(
        "Labeled", [sample_file], labels={"lang": "en", "owner": "creator1"}
    )

    data = fake_requests.calls[0]["data"]
    assert '"lang": "en"' in data["labels"]
    assert '"owner": "creator1"' in data["labels"]


# --------------------------------------------------------------------------- #
# clone_voice — retries
# --------------------------------------------------------------------------- #
def test_clone_voice_retries_on_transient_5xx_then_succeeds(fake_requests, sample_file):
    fake_requests.responses = [
        _FakeResponse(503, text="upstream down"),
        _FakeResponse(200, {"voice_id": "vid_after_retry"}),
    ]

    result = voice_clone.clone_voice("Retry Voice", [sample_file])

    assert result["voice_id"] == "vid_after_retry"
    assert len(fake_requests.calls) == 2


def test_clone_voice_retries_on_network_error_then_succeeds(fake_requests, sample_file):
    fake_requests.responses = [
        _FakeRequestException("connection reset"),
        _FakeResponse(200, {"voice_id": "vid_net"}),
    ]

    result = voice_clone.clone_voice("Net Voice", [sample_file])

    assert result["voice_id"] == "vid_net"
    assert len(fake_requests.calls) == 2


def test_clone_voice_exhausts_retries_raises(fake_requests, sample_file):
    fake_requests.responses = [
        _FakeResponse(500, text="boom"),
        _FakeResponse(500, text="boom"),
        _FakeResponse(500, text="boom"),
    ]

    with pytest.raises(voice_clone.VoiceCloneError):
        voice_clone.clone_voice("Doomed", [sample_file])
    assert len(fake_requests.calls) == voice_clone.MAX_ATTEMPTS


# --------------------------------------------------------------------------- #
# clone_voice — error mapping (non-retryable)
# --------------------------------------------------------------------------- #
def test_clone_voice_maps_401_to_auth_error(fake_requests, sample_file):
    fake_requests.responses = [_FakeResponse(401, text="bad key")]
    with pytest.raises(voice_clone.VoiceCloneAuthError):
        voice_clone.clone_voice("Auth", [sample_file])
    assert len(fake_requests.calls) == 1  # not retried


def test_clone_voice_maps_422_to_validation_error(fake_requests, sample_file):
    fake_requests.responses = [_FakeResponse(422, text="invalid sample")]
    with pytest.raises(voice_clone.VoiceCloneValidationError):
        voice_clone.clone_voice("Bad", [sample_file])
    assert len(fake_requests.calls) == 1


def test_clone_voice_maps_429_to_quota_error(fake_requests, sample_file):
    fake_requests.responses = [_FakeResponse(429, text="quota exceeded")]
    with pytest.raises(voice_clone.VoiceCloneQuotaError):
        voice_clone.clone_voice("Greedy", [sample_file])
    assert len(fake_requests.calls) == 1


def test_clone_voice_missing_voice_id_raises(fake_requests, sample_file):
    fake_requests.responses = [_FakeResponse(200, {"requires_verification": True})]
    with pytest.raises(voice_clone.VoiceCloneError):
        voice_clone.clone_voice("NoId", [sample_file])


# --------------------------------------------------------------------------- #
# clone_voice — input validation (no network)
# --------------------------------------------------------------------------- #
def test_clone_voice_requires_name(fake_requests, sample_file):
    with pytest.raises(voice_clone.VoiceCloneValidationError):
        voice_clone.clone_voice("   ", [sample_file])
    assert fake_requests.calls == []


def test_clone_voice_requires_samples(fake_requests):
    with pytest.raises(voice_clone.VoiceCloneValidationError):
        voice_clone.clone_voice("Empty", [])
    assert fake_requests.calls == []


def test_clone_voice_rejects_missing_file(fake_requests):
    with pytest.raises(voice_clone.VoiceCloneValidationError):
        voice_clone.clone_voice("Ghost", ["/nope/does-not-exist.mp3"])
    assert fake_requests.calls == []


def test_clone_voice_rejects_unsupported_extension(fake_requests, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_bytes(b"hello")
    with pytest.raises(voice_clone.VoiceCloneValidationError):
        voice_clone.clone_voice("Txt", [str(bad)])
    assert fake_requests.calls == []


def test_clone_voice_rejects_empty_file(fake_requests, tmp_path):
    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")
    with pytest.raises(voice_clone.VoiceCloneValidationError):
        voice_clone.clone_voice("Empty", [str(empty)])
    assert fake_requests.calls == []


def test_clone_voice_requires_api_key(monkeypatch, sample_file):
    fake = _FakeRequests()
    monkeypatch.setattr(voice_clone, "requests", fake)
    monkeypatch.setattr(voice_clone, "_get_api_key", lambda: "")
    with pytest.raises(voice_clone.VoiceCloneAuthError):
        voice_clone.clone_voice("NoKey", [sample_file])
    assert fake.calls == []


# --------------------------------------------------------------------------- #
# delete_voice
# --------------------------------------------------------------------------- #
def test_delete_voice_success(fake_requests):
    fake_requests.responses = [_FakeResponse(200, {})]
    assert voice_clone.delete_voice("prov_abc123") is True
    call = fake_requests.calls[0]
    assert call["method"] == "DELETE"
    assert call["url"] == "https://api.elevenlabs.io/v1/voices/prov_abc123"
    assert call["headers"]["xi-api-key"] == "test-key"


def test_delete_voice_404_is_idempotent(fake_requests):
    fake_requests.responses = [_FakeResponse(404, text="not found")]
    assert voice_clone.delete_voice("gone") is True


def test_delete_voice_auth_error(fake_requests):
    fake_requests.responses = [_FakeResponse(401, text="bad key")]
    with pytest.raises(voice_clone.VoiceCloneAuthError):
        voice_clone.delete_voice("prov_abc123")


def test_delete_voice_requires_id(fake_requests):
    with pytest.raises(voice_clone.VoiceCloneValidationError):
        voice_clone.delete_voice("  ")
    assert fake_requests.calls == []


# --------------------------------------------------------------------------- #
# get_shared_or_user_voice
# --------------------------------------------------------------------------- #
def test_get_voice_success(fake_requests):
    fake_requests.responses = [
        _FakeResponse(200, {"voice_id": "prov_abc123", "name": "Brand"})
    ]
    payload = voice_clone.get_shared_or_user_voice("prov_abc123")
    assert payload["name"] == "Brand"
    call = fake_requests.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://api.elevenlabs.io/v1/voices/prov_abc123"


def test_get_voice_not_found_raises(fake_requests):
    fake_requests.responses = [_FakeResponse(422, text="missing")]
    with pytest.raises(voice_clone.VoiceCloneValidationError):
        voice_clone.get_shared_or_user_voice("prov_abc123")


# --------------------------------------------------------------------------- #
# API-key resolution falls back to the environment (config-free)
# --------------------------------------------------------------------------- #
def test_api_key_from_environment(monkeypatch):
    monkeypatch.setattr(voice_clone, "config", None)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env-key-123")
    assert voice_clone._get_api_key() == "env-key-123"
    assert voice_clone.is_enabled() is True
