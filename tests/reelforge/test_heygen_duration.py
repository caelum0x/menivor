"""HeyGen render-duration coercion + §8 drift-gate honesty (regression).

Root-cause guard for the drift-gate bypass: when HeyGen's completed-status
payload omits ``duration``, the provider MUST surface ``None`` (an unverifiable
render) rather than fabricating the expected audio duration. Fabrication made
the downstream drift gate compare the expected value against itself and pass
unconditionally, so a truncated render desynced compose with no error recorded.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.avatar import heygen


# --------------------------------------------------------------------------- #
# HTTP + storage doubles
# --------------------------------------------------------------------------- #
# A genuinely-public IP literal for the signed download URL: the SSRF guard
# accepts it without a DNS lookup (IP-literal fast path), so these tests stay
# hermetic while still exercising the real ``_validate_and_resolve`` guard. No
# socket is ever opened because ``requests`` is fully faked below.
_PUBLIC_VIDEO_URL: str = "https://8.8.8.8/x.mp4"


class _Resp:
    def __init__(
        self,
        payload: dict | None = None,
        chunks: list[bytes] | None = None,
        status_code: int = 200,
    ) -> None:
        self._payload = payload or {}
        self._chunks = chunks or []
        self.status_code = status_code

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

    def mount(self, prefix, adapter) -> None:  # noqa: ANN001 - pinned adapter
        return None

    def get(self, url, stream=None, timeout=None, allow_redirects=None):  # noqa: ANN001
        # allow_redirects MUST be disabled so a 3xx cannot bounce to metadata.
        assert allow_redirects is False
        self._parent.calls.append(("GET-STREAM", url))
        return _Resp(chunks=[b"fake-mp4-bytes"], status_code=200)

    def close(self) -> None:
        return None


class _FakeRequests:
    """Emulates HeyGen generate -> status(completed) -> signed-URL download.

    ``status_data`` is the terminal ``data`` dict returned on ``completed``;
    omit ``duration`` from it to reproduce the schema-drift scenario.
    """

    def __init__(self, status_data: dict[str, Any]) -> None:
        self._status_data = status_data
        self.calls: list[tuple[str, str]] = []

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        self.calls.append(("POST", url))
        return _Resp({"data": {"video_id": "vidX"}})

    def get(self, url, headers=None, params=None, timeout=None, stream=None):  # noqa: ANN001
        self.calls.append(("GET", url))
        if stream:  # signed-URL download (legacy path; download now uses Session)
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


def _cleanup(result: dict | None) -> None:
    import os

    if result and result.get("avatar_video"):
        try:
            os.remove(result["avatar_video"])
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# _coerce_duration: unit
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (5.0, 5.0),
        ("7.5", 7.5),
        (3, 3.0),
        (None, None),
        ("not-a-number", None),
        (object(), None),
    ],
)
def test_coerce_duration(raw: object, expected: float | None) -> None:
    assert heygen.HeyGenProvider._coerce_duration(raw) == expected


# --------------------------------------------------------------------------- #
# Regression: missing duration must NOT fabricate the expected value
# --------------------------------------------------------------------------- #
def test_generate_avatar_missing_duration_surfaces_none_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # HeyGen completes but the status payload omits 'duration' (schema drift).
    fake_requests = _FakeRequests(
        status_data={"status": "completed", "video_url": _PUBLIC_VIDEO_URL}
    )
    monkeypatch.setattr(heygen, "requests", fake_requests)
    monkeypatch.setattr("app.services.storage.r2.r2_client", _FakeR2(), raising=False)

    captured: list[str] = []
    sink_id = heygen.logger.add(
        lambda m: captured.append(m.record["message"]), level="WARNING"
    )
    try:
        provider = _enabled_provider()
        result = provider.generate_avatar(
            "https://r2/audio.mp3",
            "avatar-1",
            expected_duration_s=30.0,
        )
    finally:
        heygen.logger.remove(sink_id)

    assert result is not None
    # The core fix: the unknown duration is surfaced as None, NOT fabricated as
    # the expected value — so the downstream drift gate cannot silently pass.
    assert result["duration"] is None
    # The §8 gate is not silently bypassed: it warns it is unverifiable...
    assert any("could not be verified against" in m for m in captured)
    # ...and does NOT emit a (fabricated) zero-delta pass.
    assert not any("drift beyond tolerance" in m for m in captured)
    _cleanup(result)


# --------------------------------------------------------------------------- #
# A genuine numeric report still flows through + drifts warn
# --------------------------------------------------------------------------- #
def test_generate_avatar_reports_numeric_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_requests = _FakeRequests(
        status_data={"status": "completed", "video_url": _PUBLIC_VIDEO_URL, "duration": 5.0}
    )
    monkeypatch.setattr(heygen, "requests", fake_requests)
    monkeypatch.setattr("app.services.storage.r2.r2_client", _FakeR2(), raising=False)

    provider = _enabled_provider()
    result = provider.generate_avatar(
        "https://r2/audio.mp3", "avatar-1", expected_duration_s=5.0
    )
    assert result is not None
    assert result["duration"] == 5.0
    _cleanup(result)


def test_generate_avatar_duration_drift_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # HeyGen reports 5.0s but the audio authority expects 10.0s -> real drift.
    fake_requests = _FakeRequests(
        status_data={"status": "completed", "video_url": _PUBLIC_VIDEO_URL, "duration": 5.0}
    )
    monkeypatch.setattr(heygen, "requests", fake_requests)
    monkeypatch.setattr("app.services.storage.r2.r2_client", _FakeR2(), raising=False)

    captured: list[str] = []
    sink_id = heygen.logger.add(
        lambda m: captured.append(m.record["message"]), level="WARNING"
    )
    try:
        provider = _enabled_provider()
        result = provider.generate_avatar(
            "https://r2/audio.mp3", "avatar-1", expected_duration_s=10.0
        )
    finally:
        heygen.logger.remove(sink_id)

    assert result is not None
    assert result["duration"] == 5.0  # provider never rewrites the render
    assert any("drift beyond tolerance" in m for m in captured)
    _cleanup(result)


# --------------------------------------------------------------------------- #
# SSRF: HeyGen-supplied download URLs are untrusted (regression)
# --------------------------------------------------------------------------- #
class _ExplodingSession:
    """A ``requests.Session`` double that fails if the download is ever made."""

    def mount(self, prefix, adapter) -> None:  # noqa: ANN001
        return None

    def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("SSRF guard did not block the download before fetch")

    def close(self) -> None:
        return None


class _ExplodingRequests:
    def Session(self) -> _ExplodingSession:
        return _ExplodingSession()


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://127.0.0.1/secret",  # loopback
        "http://10.0.0.5/internal",  # RFC-1918 private
        "http://192.168.1.1/admin",  # RFC-1918 private
        "http://localhost/x.mp4",  # blocked hostname
        "file:///etc/passwd",  # non-http scheme
        "ftp://example.com/x.mp4",  # non-http scheme
        "",  # empty / missing url
    ],
)
def test_download_to_temp_rejects_ssrf_targets(
    bad_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the guard fails open, ``_ExplodingSession.get`` raises AssertionError,
    # proving no network fetch happens for an internal/blocked/invalid target.
    monkeypatch.setattr(heygen, "requests", _ExplodingRequests())
    assert heygen.HeyGenProvider._download_to_temp(bad_url, "vidX") is None


def test_generate_avatar_rejects_ssrf_video_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # HeyGen "completes" but returns a crafted metadata URL — the pipeline must
    # refuse to fetch it and surface no result, never touching the download.
    fake_requests = _FakeRequests(
        status_data={
            "status": "completed",
            "video_url": "http://169.254.169.254/latest/meta-data/",
            "duration": 5.0,
        }
    )
    monkeypatch.setattr(heygen, "requests", fake_requests)
    monkeypatch.setattr("app.services.storage.r2.r2_client", _FakeR2(), raising=False)

    provider = _enabled_provider()
    result = provider.generate_avatar(
        "https://r2/audio.mp3", "avatar-1", expected_duration_s=5.0
    )

    assert result is None
    # The signed-URL download was never attempted for the internal target.
    assert not any(call[0] == "GET-STREAM" for call in fake_requests.calls)
