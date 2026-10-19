"""Native platform-publish connectors — real API contracts over a fake transport.

Each test drives the connector's real logic (endpoint choice, payload assembly,
response parsing, error mapping) and asserts the exact request it makes; only the
network is faked (the injectable :class:`Transport`). This is the boundary the
production code uses too, so the assertions cover the actual API contracts for
YouTube Data API v3, TikTok Content Posting API and Instagram Graph API.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domains.publishing.connectors import (
    PublishError,
    PublishRequest,
    available_platforms,
    get_connector,
)
from app.domains.publishing.native_service import (
    _clip_watermark_source,
    _watermark_block_reason,
)


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
            {"method": method, "url": url, "headers": headers or {}, "params": params or {}, "json": json, "data": data}
        )
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self._responses.pop(0)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_all_native_connectors_registered():
    assert set(available_platforms()) == {"youtube", "tiktok", "instagram"}


# --------------------------------------------------------------------------- #
# YouTube Data API v3 — resumable upload
# --------------------------------------------------------------------------- #
def test_youtube_resumable_upload_two_step(tmp_path):
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"\x00\x01FAKE-MP4")
    transport = FakeTransport([
        _Resp(200, headers={"Location": "https://upload.googleapis.com/session/xyz"}),
        _Resp(200, {"id": "vid123", "snippet": {"title": "x"}}),
    ])
    conn = get_connector("youtube")
    req = PublishRequest(
        platform="youtube", access_token="tok", video_path=str(video),
        title="My Short", hashtags=("fyp", "ai"), privacy="public",
    )
    res = conn.publish(req, transport=transport)

    assert res.status == "published"
    assert res.external_id == "vid123"
    assert res.url == "https://youtube.com/shorts/vid123"
    # Step 1: resumable init POST with snippet+status and a Bearer token.
    init = transport.calls[0]
    assert init["method"] == "POST"
    assert init["url"] == "https://www.googleapis.com/upload/youtube/v3/videos"
    assert init["params"] == {"uploadType": "resumable", "part": "snippet,status"}
    assert init["headers"]["Authorization"] == "Bearer tok"
    assert init["json"]["snippet"]["title"] == "My Short"
    assert init["json"]["status"]["privacyStatus"] == "public"
    assert "#Shorts" in init["json"]["snippet"]["description"]
    # Step 2: PUT the actual bytes to the returned session URL.
    put = transport.calls[1]
    assert put["method"] == "PUT"
    assert put["url"] == "https://upload.googleapis.com/session/xyz"
    assert put["data"] == b"\x00\x01FAKE-MP4"


def test_youtube_requires_local_path():
    conn = get_connector("youtube")
    transport = FakeTransport([_Resp(200, headers={"Location": "https://u/s"})])
    with pytest.raises(PublishError):
        conn.publish(PublishRequest(platform="youtube", access_token="tok"), transport=transport)


def test_youtube_init_http_error_raises():
    conn = get_connector("youtube")
    transport = FakeTransport([_Resp(403, {"error": {"message": "forbidden"}})])
    with pytest.raises(PublishError):
        conn.publish(
            PublishRequest(platform="youtube", access_token="tok", video_path="/nope"),
            transport=transport,
        )


# --------------------------------------------------------------------------- #
# TikTok Content Posting API — PULL_FROM_URL direct post
# --------------------------------------------------------------------------- #
def test_tiktok_pull_from_url_init_and_status():
    transport = FakeTransport([
        _Resp(200, {"data": {"publish_id": "pub_1"}, "error": {"code": "ok"}}),
        _Resp(200, {"data": {"status": "PUBLISH_COMPLETE"}, "error": {"code": "ok"}}),
    ])
    conn = get_connector("tiktok")
    req = PublishRequest(
        platform="tiktok", access_token="tok",
        video_url="https://r2.example/reel.mp4", caption="hello", hashtags=("fyp",),
        privacy="public",
    )
    res = conn.publish(req, transport=transport)

    assert res.status == "published"
    assert res.external_id == "pub_1"
    init = transport.calls[0]
    assert init["url"] == "https://open.tiktokapis.com/v2/post/publish/video/init/"
    assert init["headers"]["Authorization"] == "Bearer tok"
    assert init["json"]["source_info"] == {"source": "PULL_FROM_URL", "video_url": "https://r2.example/reel.mp4"}
    assert init["json"]["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert init["json"]["post_info"]["title"] == "hello #fyp"


def test_tiktok_processing_when_not_complete():
    transport = FakeTransport([
        _Resp(200, {"data": {"publish_id": "pub_2"}}),
        _Resp(200, {"data": {"status": "PROCESSING_UPLOAD"}}),
    ])
    res = get_connector("tiktok").publish(
        PublishRequest(platform="tiktok", access_token="t", video_url="https://x/y.mp4"),
        transport=transport,
    )
    assert res.status == "processing"
    assert res.external_id == "pub_2"


def test_tiktok_requires_video_url():
    with pytest.raises(PublishError):
        get_connector("tiktok").publish(
            PublishRequest(platform="tiktok", access_token="t"), transport=FakeTransport([])
        )


# --------------------------------------------------------------------------- #
# TikTok error classification (ported from gitroomhq/postiz-app, AGPL-3.0 —
# see NOTICE; adapted to this module's PublishError/retryable contract)
# --------------------------------------------------------------------------- #
def test_tiktok_daily_app_cap_is_not_retryable_and_has_clear_message():
    transport = FakeTransport([
        _Resp(403, {"error": {"code": "reached_active_user_cap", "message": "..."}}),
    ])
    with pytest.raises(PublishError) as exc_info:
        get_connector("tiktok").publish(
            PublishRequest(platform="tiktok", access_token="t", video_url="https://x/y.mp4"),
            transport=transport,
        )
    assert "daily app-wide posting limit" in str(exc_info.value)
    assert exc_info.value.retryable is False


def test_tiktok_daily_post_limit_is_retryable():
    transport = FakeTransport([
        _Resp(403, {"error": {"code": "spam_risk_too_many_posts"}}),
    ])
    with pytest.raises(PublishError) as exc_info:
        get_connector("tiktok").publish(
            PublishRequest(platform="tiktok", access_token="t", video_url="https://x/y.mp4"),
            transport=transport,
        )
    assert "daily post limit" in str(exc_info.value)
    assert exc_info.value.retryable is True


def test_tiktok_privacy_level_mismatch_classified_on_http_200_error_object():
    # TikTok wraps some rejections in a 200 response with a non-"ok" error code.
    transport = FakeTransport([
        _Resp(200, {"error": {"code": "privacy_level_option_mismatch", "message": "..."}}),
    ])
    with pytest.raises(PublishError) as exc_info:
        get_connector("tiktok").publish(
            PublishRequest(platform="tiktok", access_token="t", video_url="https://x/y.mp4"),
            transport=transport,
        )
    assert "privacy level isn't allowed" in str(exc_info.value)
    assert exc_info.value.retryable is False


def test_tiktok_unrecognized_error_falls_back_to_raw_body():
    transport = FakeTransport([
        _Resp(500, {"error": {"code": "some_new_tiktok_error_code"}}),
    ])
    with pytest.raises(PublishError) as exc_info:
        get_connector("tiktok").publish(
            PublishRequest(platform="tiktok", access_token="t", video_url="https://x/y.mp4"),
            transport=transport,
        )
    assert "publish init failed" in str(exc_info.value)
    assert exc_info.value.retryable is True  # unclassified 5xx still retries


# --------------------------------------------------------------------------- #
# Instagram Graph API — container → publish
# --------------------------------------------------------------------------- #
def test_instagram_container_then_publish():
    transport = FakeTransport([
        _Resp(200, {"id": "container_1"}),         # create container
        _Resp(200, {"status_code": "FINISHED"}),   # container status
        _Resp(200, {"id": "media_9"}),             # media_publish
    ])
    conn = get_connector("instagram")
    req = PublishRequest(
        platform="instagram", access_token="tok", external_account_id="ig_user_1",
        video_url="https://r2.example/reel.mp4", caption="cool", hashtags=("reels",),
    )
    res = conn.publish(req, transport=transport)

    assert res.status == "published"
    assert res.external_id == "media_9"
    assert res.url == "https://www.instagram.com/reel/media_9/"
    create = transport.calls[0]
    assert create["url"].endswith("/ig_user_1/media")
    assert create["params"]["media_type"] == "REELS"
    assert create["params"]["video_url"] == "https://r2.example/reel.mp4"
    assert create["params"]["caption"] == "cool #reels"
    publish = transport.calls[2]
    assert publish["url"].endswith("/ig_user_1/media_publish")
    assert publish["params"]["creation_id"] == "container_1"


def test_instagram_processing_when_container_not_ready():
    transport = FakeTransport([
        _Resp(200, {"id": "container_2"}),
        _Resp(200, {"status_code": "IN_PROGRESS"}),
    ])
    res = get_connector("instagram").publish(
        PublishRequest(platform="instagram", access_token="t", external_account_id="ig1",
                       video_url="https://x/y.mp4"),
        transport=transport,
    )
    assert res.status == "processing"
    assert res.external_id == "container_2"


def test_instagram_requires_ig_user_id():
    with pytest.raises(PublishError):
        get_connector("instagram").publish(
            PublishRequest(platform="instagram", access_token="t", video_url="https://x/y.mp4"),
            transport=FakeTransport([]),
        )


# --------------------------------------------------------------------------- #
# caption + hashtag assembly
# --------------------------------------------------------------------------- #
def test_caption_with_tags_normalizes_hashes():
    req = PublishRequest(platform="tiktok", access_token="t", caption="watch this", hashtags=("fyp", "#ai"))
    assert req.caption_with_tags() == "watch this #fyp #ai"


# --------------------------------------------------------------------------- #
# Foreign-watermark cross-post guard (a clip auto-clipped from a pasted
# TikTok/YouTube/etc. link still carries that platform's watermark; posting it
# as-is to a platform that suppresses rival watermarks must be held, not
# silently reach-killed). See native_service.publish_reel_native.
# --------------------------------------------------------------------------- #
def test_clip_watermark_source_reads_the_clipping_stage():
    job = SimpleNamespace(stages={"clips": [{"source_ref": "platform:tiktok:abc123"}]})
    assert _clip_watermark_source(job) == "tiktok"


def test_clip_watermark_source_none_for_an_avatar_reel_job():
    job = SimpleNamespace(stages={})
    assert _clip_watermark_source(job) == ""
    assert _clip_watermark_source(SimpleNamespace(stages=None)) == ""


def test_clip_watermark_source_ignores_a_non_platform_ref():
    job = SimpleNamespace(stages={"clips": [{"source_ref": "upload:xyz"}]})
    assert _clip_watermark_source(job) == ""


def test_watermark_block_reason_blocks_tiktok_clip_onto_instagram():
    reason = _watermark_block_reason("instagram", "tiktok")
    assert "tiktok" in reason
    assert "instagram" in reason


def test_watermark_block_reason_allows_a_clean_source():
    assert _watermark_block_reason("instagram", "") == ""


def test_watermark_block_reason_allows_an_unsuppressed_pair():
    # X suppresses nothing in the shared policy table.
    assert _watermark_block_reason("x", "tiktok") == ""
