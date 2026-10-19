"""Live publisher upload client (:class:`NativeUploadClient`) over a fake transport.

The ``services/publishers`` seam's real client delegates each documented platform
upload to the native connectors; here we drive that real logic (token resolution,
env-credential fallback, request shaping, response mapping, clean degradation)
while faking only the network — the injectable connector ``Transport``. This is
the exact boundary production uses, so the assertions cover the real API
contracts (TikTok Content Posting API, Instagram Graph API, YouTube Data API v3).
"""

from __future__ import annotations

import pytest

from app.services.publishers import (
    NativeUploadClient,
    PublishError,
    TikTokPublisher,
    resolve_platform_creds,
)
from app.services.publishers.env_creds import normalize_platform


class _Resp:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


class FakeTransport:
    """Records every request and replays a scripted queue of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "params": params or {},
                "json": json,
                "data": data,
            }
        )
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self._responses.pop(0)


# --------------------------------------------------------------------------- #
# env credential resolution
# --------------------------------------------------------------------------- #
def test_normalize_platform_dealiases_without_raising():
    assert normalize_platform("youtube_shorts") == "youtube"
    assert normalize_platform("  TikTok ") == "tiktok"
    # Unknown token is returned as-is (soft) rather than raising.
    assert normalize_platform("myspace") == "myspace"


def test_resolve_platform_creds_reads_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "env-tok")
    monkeypatch.setenv("TIKTOK_CLIENT_ID", "cid")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "csecret")
    creds = resolve_platform_creds("tiktok")
    assert creds.access_token == "env-tok"
    assert creds.has_token is True
    assert creds.has_app is True


def test_resolve_platform_creds_absent_is_empty_not_error(monkeypatch):
    for suffix in ("ACCESS_TOKEN", "CLIENT_ID", "CLIENT_SECRET", "EXTERNAL_ACCOUNT_ID"):
        monkeypatch.delenv(f"TIKTOK_{suffix}", raising=False)
    creds = resolve_platform_creds("tiktok")
    assert creds.has_token is False
    assert creds.has_app is False


def test_instagram_external_account_id_alias(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_EXTERNAL_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("INSTAGRAM_USER_ID", "ig-777")
    assert resolve_platform_creds("instagram").external_account_id == "ig-777"


# --------------------------------------------------------------------------- #
# clean degradation (no unexpected network call, no crash)
# --------------------------------------------------------------------------- #
def test_missing_token_degrades_cleanly(monkeypatch):
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    transport = FakeTransport([])  # must never be called
    with pytest.raises(PublishError) as exc:
        NativeUploadClient(transport=transport).upload(
            "tiktok", "", "https://r2/x.mp4", caption="hi"
        )
    assert "TIKTOK_ACCESS_TOKEN" in str(exc.value)
    assert transport.calls == []


def test_unsupported_platform_degrades_cleanly():
    with pytest.raises(PublishError):
        NativeUploadClient(transport=FakeTransport([])).upload(
            "myspace", "tok", "https://r2/x.mp4"
        )


# --------------------------------------------------------------------------- #
# TikTok — env token fallback + explicit token precedence
# --------------------------------------------------------------------------- #
def test_tiktok_uses_env_token_and_returns_mapped_dict(monkeypatch):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "env-token")
    transport = FakeTransport(
        [
            _Resp(200, {"data": {"publish_id": "pub_1"}, "error": {"code": "ok"}}),
            _Resp(200, {"data": {"status": "PUBLISH_COMPLETE"}, "error": {"code": "ok"}}),
        ]
    )
    out = NativeUploadClient(transport=transport).upload(
        "tiktok", "", "https://r2/reel.mp4", caption="hello", hashtags=("fyp",)
    )
    assert out["id"] == "pub_1"
    assert out["status"] == "published"
    assert out["platform"] == "tiktok"
    init = transport.calls[0]
    assert init["url"] == "https://open.tiktokapis.com/v2/post/publish/video/init/"
    assert init["headers"]["Authorization"] == "Bearer env-token"
    assert init["json"]["post_info"]["title"] == "hello #fyp"
    assert init["json"]["source_info"] == {
        "source": "PULL_FROM_URL",
        "video_url": "https://r2/reel.mp4",
    }


def test_supplied_token_beats_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "env-token")
    transport = FakeTransport(
        [
            _Resp(200, {"data": {"publish_id": "p2"}}),
            _Resp(200, {"data": {"status": "PROCESSING_UPLOAD"}}),
        ]
    )
    out = NativeUploadClient(transport=transport).upload(
        "tiktok", "user-token", "https://r2/reel.mp4"
    )
    assert out["status"] == "processing"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer user-token"


def test_connector_http_error_maps_to_publish_error():
    transport = FakeTransport([_Resp(400, {"error": {"code": "spam_risk"}})])
    with pytest.raises(PublishError):
        NativeUploadClient(transport=transport).upload(
            "tiktok", "tok", "https://r2/reel.mp4"
        )


# --------------------------------------------------------------------------- #
# Instagram (Reels) — container → publish, ig user id from env
# --------------------------------------------------------------------------- #
def test_instagram_reels_via_env_user_id(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_EXTERNAL_ACCOUNT_ID", "ig-1")
    transport = FakeTransport(
        [
            _Resp(200, {"id": "container_1"}),
            _Resp(200, {"status_code": "FINISHED"}),
            _Resp(200, {"id": "media_9"}),
        ]
    )
    out = NativeUploadClient(transport=transport).upload(
        "instagram", "tok", "https://r2/reel.mp4", caption="cool", hashtags=("reels",)
    )
    assert out["id"] == "media_9"
    assert out["url"] == "https://www.instagram.com/reel/media_9/"
    assert transport.calls[0]["url"].endswith("/ig-1/media")
    assert transport.calls[0]["params"]["media_type"] == "REELS"


def test_instagram_explicit_external_account_id_overrides_env(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_EXTERNAL_ACCOUNT_ID", "ig-env")
    transport = FakeTransport(
        [
            _Resp(200, {"id": "c"}),
            _Resp(200, {"status_code": "IN_PROGRESS"}),
        ]
    )
    out = NativeUploadClient(transport=transport).upload(
        "instagram", "tok", "https://r2/reel.mp4", external_account_id="ig-arg"
    )
    assert out["status"] == "processing"
    assert transport.calls[0]["url"].endswith("/ig-arg/media")


# --------------------------------------------------------------------------- #
# YouTube (Shorts) — resumable byte upload from a local path
# --------------------------------------------------------------------------- #
def test_youtube_short_from_local_path(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_ACCESS_TOKEN", "yt-token")
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"\x00\x01MP4")
    transport = FakeTransport(
        [
            _Resp(200, headers={"Location": "https://upload.googleapis.com/s/xyz"}),
            _Resp(200, {"id": "vid_1"}),
        ]
    )
    out = NativeUploadClient(transport=transport).upload(
        "youtube",
        "",
        "",
        caption="my short",
        title="My Short",
        video_path=str(video),
    )
    assert out["id"] == "vid_1"
    assert out["url"] == "https://youtube.com/shorts/vid_1"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer yt-token"
    assert transport.calls[1]["method"] == "PUT"
    assert transport.calls[1]["data"] == b"\x00\x01MP4"


# --------------------------------------------------------------------------- #
# BasePublisher drives the live client end-to-end
# --------------------------------------------------------------------------- #
def test_base_publisher_over_native_client():
    transport = FakeTransport(
        [
            _Resp(200, {"data": {"publish_id": "pub_z"}}),
            _Resp(200, {"data": {"status": "PUBLISH_COMPLETE"}}),
        ]
    )
    publisher = TikTokPublisher(NativeUploadClient(transport=transport))
    result = publisher.publish(
        access_token="tok", video_url="https://r2/reel.mp4", caption="hey"
    )
    assert result.provider == "tiktok"
    assert result.external_post_id == "pub_z"
