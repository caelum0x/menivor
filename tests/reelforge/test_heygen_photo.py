"""Custom avatar from a photo — HeyGen talking-photo support (§ custom-avatar).

Covers the talking-photo path added to the HeyGen backend:

* ``HeyGenClient.upload_image`` uploads raw image bytes and returns the asset id.
* ``HeyGenClient.create_talking_photo`` returns a ``talking_photo_id`` (and its
  documented "image acts as the talking_photo" fallback).
* ``HeyGenProvider.create_talking_photo`` uploads + creates end-to-end.
* ``HeyGenProvider.generate_avatar(character_kind='talking_photo')`` sends a
  ``talking_photo`` character payload; the default kind stays an ``avatar``.

All HeyGen HTTP is faked — no socket is ever opened.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from app.services.avatar import heygen


# --------------------------------------------------------------------------- #
# A genuinely-public IP literal for the signed download URL: the SSRF guard
# accepts it without a DNS lookup, so these tests stay hermetic.
# --------------------------------------------------------------------------- #
_PUBLIC_VIDEO_URL: str = "https://8.8.8.8/x.mp4"


class _Resp:
    def __init__(self, payload: dict | None = None, chunks: list[bytes] | None = None) -> None:
        self._payload = payload or {}
        self._chunks = chunks or []
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload

    def iter_content(self, chunk_size: int = 1 << 16):
        yield from self._chunks


class _FakeSession:
    """Emulates the DNS-pinned ``requests.Session`` used for the download."""

    def __init__(self, parent: "_FakeRequests") -> None:
        self._parent = parent

    def mount(self, prefix, adapter) -> None:  # noqa: ANN001
        return None

    def get(self, url, stream=None, timeout=None, allow_redirects=None):  # noqa: ANN001
        assert allow_redirects is False
        self._parent.calls.append(("GET-STREAM", url))
        return _Resp(chunks=[b"fake-mp4-bytes"])

    def close(self) -> None:
        return None


class _FakeRequests:
    """Fakes HeyGen upload / talking-photo / generate / status / download.

    ``upload_payload`` -> the ``data`` node returned by the asset upload.
    ``talking_photo_payload`` -> the full body returned by the talking-photo
    creation endpoint. ``status_data`` -> terminal ``completed`` status data.
    Captured POST bodies land in ``posted`` keyed by URL.
    """

    def __init__(
        self,
        *,
        upload_payload: dict | None = None,
        talking_photo_payload: dict | None = None,
        status_data: dict[str, Any] | None = None,
    ) -> None:
        self._upload_payload = upload_payload if upload_payload is not None else {"id": "asset-1"}
        self._talking_photo_payload = (
            talking_photo_payload
            if talking_photo_payload is not None
            else {"data": {"talking_photo_id": "tp_123"}}
        )
        self._status_data = status_data or {
            "status": "completed",
            "video_url": _PUBLIC_VIDEO_URL,
            "duration": 30.0,
        }
        self.calls: list[tuple[str, str]] = []
        self.posted: dict[str, Any] = {}

    def post(self, url, headers=None, data=None, json=None, timeout=None):  # noqa: ANN001
        self.calls.append(("POST", url))
        self.posted[url] = {"data": data, "json": json, "headers": headers}
        if url == heygen.HeyGenClient.UPLOAD:
            return _Resp({"data": self._upload_payload})
        if url == heygen.HeyGenClient.TALKING_PHOTO:
            return _Resp(self._talking_photo_payload)
        if url == heygen.HeyGenClient.GEN:
            return _Resp({"data": {"video_id": "vidX"}})
        return _Resp({})

    def get(self, url, headers=None, params=None, timeout=None, stream=None):  # noqa: ANN001
        self.calls.append(("GET", url))
        if stream:
            return _Resp(chunks=[b"fake-mp4-bytes"])
        return _Resp({"data": self._status_data})

    def Session(self) -> _FakeSession:
        return _FakeSession(self)


class _FakeR2:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str]] = []

    def upload_file(self, local_path: str, key: str, content_type=None) -> str:  # noqa: ANN001
        self.uploads.append((local_path, key))
        return f"https://cdn.example.com/{key}"


def _enabled_provider() -> heygen.HeyGenProvider:
    provider = heygen.HeyGenProvider()
    provider._api_key = "k"
    provider._client = heygen.HeyGenClient(api_key="k")
    return provider


def _write_temp_image(suffix: str = ".jpg", body: bytes = b"\xff\xd8\xff-jpeg") -> str:
    fd, path = tempfile.mkstemp(prefix="heygen_photo_test", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(body)
    return path


def _cleanup(*paths: str | None) -> None:
    for path in paths:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# _guess_image_mime + _build_character: units
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("selfie.jpg", "image/jpeg"),
        ("SELFIE.JPEG", "image/jpeg"),
        ("face.png", "image/png"),
        ("pic.webp", "image/webp"),
        ("mystery.gif", "image/jpeg"),
        ("noext", "image/jpeg"),
    ],
)
def test_guess_image_mime(name: str, expected: str) -> None:
    assert heygen._guess_image_mime(name) == expected


def test_build_character_talking_photo() -> None:
    character = heygen.HeyGenProvider._build_character("tp_9", "talking_photo")
    assert character == {"type": "talking_photo", "talking_photo_id": "tp_9"}


def test_build_character_default_avatar() -> None:
    character = heygen.HeyGenProvider._build_character("av_9", "avatar")
    assert character == {"type": "avatar", "avatar_id": "av_9", "avatar_style": "normal"}


def test_build_character_unknown_kind_falls_back_to_avatar() -> None:
    character = heygen.HeyGenProvider._build_character("av_9", "bogus")
    assert character["type"] == "avatar"
    assert character["avatar_id"] == "av_9"


# --------------------------------------------------------------------------- #
# HeyGenClient.upload_image
# --------------------------------------------------------------------------- #
def test_upload_image_returns_asset_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests(upload_payload={"id": "asset-42"})
    monkeypatch.setattr(heygen, "requests", fake)

    path = _write_temp_image()
    try:
        asset_ref = heygen.HeyGenClient(api_key="k").upload_image(path)
    finally:
        _cleanup(path)

    assert asset_ref == "asset-42"
    # Raw bytes were POSTed to the asset endpoint with the image Content-Type.
    posted = fake.posted[heygen.HeyGenClient.UPLOAD]
    assert posted["data"] == b"\xff\xd8\xff-jpeg"
    assert posted["headers"]["Content-Type"] == "image/jpeg"


def test_upload_image_falls_back_to_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests(upload_payload={"url": "https://img.heygen/asset.jpg"})
    monkeypatch.setattr(heygen, "requests", fake)

    path = _write_temp_image()
    try:
        asset_ref = heygen.HeyGenClient(api_key="k").upload_image(path)
    finally:
        _cleanup(path)

    assert asset_ref == "https://img.heygen/asset.jpg"


def test_upload_image_rejects_bad_mime() -> None:
    with pytest.raises(ValueError):
        heygen.HeyGenClient(api_key="k").upload_image("/tmp/whatever.jpg", mime="image/gif")


def test_upload_image_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        heygen.HeyGenClient(api_key="k").upload_image("/no/such/file.jpg")


def test_upload_image_no_asset_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests(upload_payload={})
    monkeypatch.setattr(heygen, "requests", fake)

    path = _write_temp_image()
    try:
        with pytest.raises(heygen.HeyGenError):
            heygen.HeyGenClient(api_key="k").upload_image(path)
    finally:
        _cleanup(path)


# --------------------------------------------------------------------------- #
# HeyGenClient.create_talking_photo
# --------------------------------------------------------------------------- #
def test_create_talking_photo_returns_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests(talking_photo_payload={"data": {"talking_photo_id": "tp_777"}})
    monkeypatch.setattr(heygen, "requests", fake)

    tp_id = heygen.HeyGenClient(api_key="k").create_talking_photo("asset-1")

    assert tp_id == "tp_777"
    # A bare asset id is sent as image_asset_id (not a url).
    posted = fake.posted[heygen.HeyGenClient.TALKING_PHOTO]
    assert posted["json"] == {"image_asset_id": "asset-1"}


def test_create_talking_photo_url_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests(talking_photo_payload={"data": {"id": "tp_url"}})
    monkeypatch.setattr(heygen, "requests", fake)

    tp_id = heygen.HeyGenClient(api_key="k").create_talking_photo("https://img/asset.jpg")

    assert tp_id == "tp_url"
    posted = fake.posted[heygen.HeyGenClient.TALKING_PHOTO]
    assert posted["json"] == {"image_url": "https://img/asset.jpg"}


def test_create_talking_photo_fallback_to_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    # HeyGen accepts the image but returns no distinct id: the uploaded
    # reference itself acts as the talking_photo_id (documented fallback).
    fake = _FakeRequests(talking_photo_payload={"data": {}})
    monkeypatch.setattr(heygen, "requests", fake)

    tp_id = heygen.HeyGenClient(api_key="k").create_talking_photo("asset-1")

    assert tp_id == "asset-1"


def test_create_talking_photo_error_body_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests(talking_photo_payload={"error": "quota exceeded"})
    monkeypatch.setattr(heygen, "requests", fake)

    with pytest.raises(heygen.HeyGenError):
        heygen.HeyGenClient(api_key="k").create_talking_photo("asset-1")


def test_create_talking_photo_empty_reference_raises() -> None:
    with pytest.raises(ValueError):
        heygen.HeyGenClient(api_key="k").create_talking_photo("   ")


# --------------------------------------------------------------------------- #
# HeyGenProvider.create_talking_photo (upload + create)
# --------------------------------------------------------------------------- #
def test_provider_create_talking_photo_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRequests(
        upload_payload={"id": "asset-9"},
        talking_photo_payload={"data": {"talking_photo_id": "tp_final"}},
    )
    monkeypatch.setattr(heygen, "requests", fake)

    path = _write_temp_image(suffix=".png")
    try:
        tp_id = _enabled_provider().create_talking_photo(path)
    finally:
        _cleanup(path)

    assert tp_id == "tp_final"
    # png extension -> image/png content type on the upload.
    assert fake.posted[heygen.HeyGenClient.UPLOAD]["headers"]["Content-Type"] == "image/png"
    # The asset id from upload was threaded into the talking-photo creation.
    assert fake.posted[heygen.HeyGenClient.TALKING_PHOTO]["json"] == {"image_asset_id": "asset-9"}


def test_provider_create_talking_photo_disabled_returns_none() -> None:
    provider = heygen.HeyGenProvider()
    provider._api_key = ""
    assert provider.create_talking_photo("/tmp/x.jpg") is None


def test_provider_create_talking_photo_upload_failure_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _enabled_provider()

    def _boom(*_a: Any, **_k: Any) -> str:
        raise RuntimeError("upload exploded")

    monkeypatch.setattr(provider._client, "upload_image", _boom)
    assert provider.create_talking_photo("/tmp/x.jpg") is None


# --------------------------------------------------------------------------- #
# HeyGenProvider.generate_avatar — character_kind routing
# --------------------------------------------------------------------------- #
def test_generate_avatar_talking_photo_sends_talking_photo_character(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRequests()
    monkeypatch.setattr(heygen, "requests", fake)
    monkeypatch.setattr("app.services.storage.r2.r2_client", _FakeR2(), raising=False)

    result = _enabled_provider().generate_avatar(
        "https://r2/audio.mp3",
        "tp_555",
        expected_duration_s=30.0,
        character_kind="talking_photo",
    )
    try:
        assert result is not None
        payload = fake.posted[heygen.HeyGenClient.GEN]["json"]
        character = payload["video_inputs"][0]["character"]
        assert character == {"type": "talking_photo", "talking_photo_id": "tp_555"}
        # Voice is still the external audio input (no HeyGen TTS).
        assert payload["video_inputs"][0]["voice"] == {
            "type": "audio",
            "audio_url": "https://r2/audio.mp3",
        }
    finally:
        _cleanup(result.get("avatar_video") if result else None)


def test_generate_avatar_default_kind_sends_avatar_character(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRequests()
    monkeypatch.setattr(heygen, "requests", fake)
    monkeypatch.setattr("app.services.storage.r2.r2_client", _FakeR2(), raising=False)

    result = _enabled_provider().generate_avatar(
        "https://r2/audio.mp3",
        "avatar-1",
        expected_duration_s=30.0,
    )
    try:
        assert result is not None
        character = fake.posted[heygen.HeyGenClient.GEN]["json"]["video_inputs"][0]["character"]
        assert character == {
            "type": "avatar",
            "avatar_id": "avatar-1",
            "avatar_style": "normal",
        }
    finally:
        _cleanup(result.get("avatar_video") if result else None)
