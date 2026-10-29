"""Buffer and Typefully clients, with HTTP mocked at the transport.

Covers channel listing, asset URLs, Typefully's upload-then-draft sequence,
and free-plan limit errors (Buffer LimitReachedError, Typefully quota / 402).
"""

from __future__ import annotations

import json

import pytest

from app.domains.x_scheduler.buffer_client import BUFFER_URL, BufferClient
from app.domains.x_scheduler.errors import LimitReached
from app.domains.x_scheduler.http import ProviderHTTPError
from app.domains.x_scheduler.typefully_client import TypefullyClient

BUFFER_KEY = "buf_live_secret_value"
TYPEFULLY_KEY = "tf_live_secret_value"


def _json(status: int, payload: dict) -> tuple[int, bytes]:
    return status, json.dumps(payload).encode()


def test_buffer_lists_only_connected_x_channels():
    def transport(method, url, headers, body):
        assert method == "POST" and url == BUFFER_URL
        assert headers["Authorization"] == f"Bearer {BUFFER_KEY}"
        query = json.loads(body)["query"]
        assert "organizations" in query and "channels" in query
        return _json(200, {"data": {"account": {"organizations": [
            {"id": "org1", "name": "Acme", "channels": [
                {"id": "ch-x", "name": "ada", "displayName": "Ada", "service": "twitter",
                 "isDisconnected": False, "isLocked": False},
                {"id": "ch-ig", "name": "adaig", "displayName": "IG", "service": "instagram",
                 "isDisconnected": False, "isLocked": False},
                {"id": "ch-off", "name": "old", "displayName": "Old", "service": "twitter",
                 "isDisconnected": True, "isLocked": False},
            ]},
        ]}}})

    targets = BufferClient(BUFFER_KEY, transport).list_x_channels()
    assert targets == [{
        "id": "ch-x", "name": "Ada", "handle": "ada", "organization": "Acme",
        "service": "x", "provider": "buffer",
    }]


def test_buffer_create_post_sends_a_video_url_and_a_custom_time():
    seen = {}

    def transport(method, url, headers, body):
        seen["input"] = json.loads(body)["variables"]["input"]
        assert headers["Authorization"] == f"Bearer {BUFFER_KEY}"
        return _json(200, {"data": {"createPost": {"__typename": "PostActionSuccess", "post": {"id": "post_1"}}}})

    created = BufferClient(BUFFER_KEY, transport).create_post(
        channel_id="ch-x",
        text="hello",
        asset_url="https://media.example/clip.mp4",
        kind="video",
        when="schedule",
        due_at="2026-11-02T15:00:00Z",
    )
    assert created == {"id": "post_1", "status": "scheduled"}
    assert seen["input"]["mode"] == "customScheduled"
    assert seen["input"]["schedulingType"] == "automatic"
    assert seen["input"]["dueAt"] == "2026-11-02T15:00:00Z"
    assert seen["input"]["assets"] == [{"video": {"url": "https://media.example/clip.mp4"}}]


def test_buffer_queue_uses_add_to_queue_and_an_image_url():
    seen = {}

    def transport(method, url, headers, body):
        seen["input"] = json.loads(body)["variables"]["input"]
        return _json(200, {"data": {"createPost": {"__typename": "PostActionSuccess", "post": {"id": "post_2"}}}})

    created = BufferClient(BUFFER_KEY, transport).create_post(
        channel_id="ch-x", text="", asset_url="https://media.example/still.png",
        kind="image", when="queue", due_at=None,
    )
    assert created["status"] == "queued"
    assert seen["input"]["mode"] == "addToQueue"
    assert "dueAt" not in seen["input"]
    assert seen["input"]["assets"] == [{"image": {"url": "https://media.example/still.png"}}]


def test_buffer_limit_reached_is_a_typed_error_and_not_a_crash():
    def transport(method, url, headers, body):
        return _json(200, {"data": {"createPost": {
            "__typename": "LimitReachedError",
            "message": "You have reached your limit of scheduled posts.",
        }}})

    with pytest.raises(LimitReached) as caught:
        BufferClient(BUFFER_KEY, transport).create_post(
            channel_id="ch-x", text="hi", asset_url="https://media.example/a.mp4",
            kind="video", when="queue", due_at=None,
        )
    assert "10 scheduled posts" in caught.value.message
    assert "Nothing was posted" in caught.value.message
    assert BUFFER_KEY not in caught.value.message


def test_buffer_rejects_a_bad_key_without_echoing_it():
    def transport(method, url, headers, body):
        return 401, json.dumps({"errors": [{"message": f"bad {BUFFER_KEY}"}]}).encode()

    with pytest.raises(ProviderHTTPError) as caught:
        BufferClient(BUFFER_KEY, transport).list_x_channels()
    assert caught.value.status == 401
    assert BUFFER_KEY not in caught.value.message


def test_typefully_lists_social_sets_that_have_x_and_reports_quota():
    def transport(method, url, headers, body):
        assert headers["Authorization"] == f"Bearer {TYPEFULLY_KEY}"
        if url.endswith("/v2/social-sets?limit=50&offset=0"):
            return _json(200, {"results": [
                {"id": 9, "username": "ada", "name": "Ada"},
                {"id": 10, "username": "nope", "name": "No X"},
            ], "next": "", "count": 2, "limit": 50, "offset": 0})
        if url.endswith("/v2/social-sets/9/"):
            return _json(200, {
                "id": 9, "username": "ada", "name": "Ada Lovelace",
                "platforms": {"x": {"username": "ada"}, "linkedin": None},
                "publishing_quota": {"used": 2, "remaining": 8, "resets_at": "2026-11-01T00:00:00Z"},
                "team": None,
            })
        if url.endswith("/v2/social-sets/10/"):
            return _json(200, {"id": 10, "platforms": {"x": None}, "username": "nope", "name": "No X"})
        raise AssertionError(url)

    targets = TypefullyClient(TYPEFULLY_KEY, transport, sleep=lambda _s: None).list_x_social_sets()
    assert len(targets) == 1
    assert targets[0]["id"] == "9"
    assert targets[0]["handle"] == "ada"
    assert targets[0]["publishing_quota"]["remaining"] == 8


def test_typefully_uploads_bytes_then_creates_a_draft_with_publish_at():
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url, dict(headers), body))
        if method == "GET" and url.endswith("/social-sets/9/"):
            return _json(200, {"publishing_quota": {"used": 1, "remaining": 3, "resets_at": "2026-12-01T00:00:00Z"}})
        if method == "POST" and url.endswith("/media/upload"):
            assert json.loads(body)["file_name"] == "clip.mp4"
            return _json(201, {"media_id": "m1", "upload_url": "https://uploads.example/put"})
        if method == "PUT" and url == "https://uploads.example/put":
            assert body == b"mp4-bytes"
            assert "Authorization" not in headers
            assert "Content-Type" not in headers
            return 204, b""
        if method == "GET" and url.endswith("/media/m1"):
            return _json(200, {"status": "ready", "media_id": "m1"})
        if method == "POST" and url.endswith("/drafts"):
            payload = json.loads(body)
            assert payload["publish_at"] == "2026-11-02T15:00:00Z"
            assert payload["platforms"]["x"]["enabled"] is True
            assert payload["platforms"]["x"]["posts"] == [{"text": "caption", "media_ids": ["m1"]}]
            return _json(201, {"id": 42, "status": "scheduled", "private_url": "https://typefully.com/?d=42&a=9"})
        raise AssertionError((method, url))

    created = TypefullyClient(TYPEFULLY_KEY, transport, sleep=lambda _s: None).publish(
        social_set_id="9", text="caption", filename="clip.mp4", data=b"mp4-bytes",
        when="schedule", due_at="2026-11-02T15:00:00Z",
    )
    assert created["id"] == "42"
    assert created["status"] == "scheduled"
    assert [call[0] for call in calls] == ["GET", "POST", "PUT", "GET", "POST"]


def test_typefully_queue_uses_next_free_slot():
    def transport(method, url, headers, body):
        if method == "GET" and url.endswith("/social-sets/9/"):
            return _json(200, {"publishing_quota": {"remaining": 1}})
        if method == "POST" and url.endswith("/media/upload"):
            return _json(201, {"media_id": "m1", "upload_url": "https://uploads.example/put"})
        if method == "PUT":
            return 200, b""
        if method == "GET" and "/media/" in url:
            return _json(200, {"status": "ready"})
        if method == "POST" and url.endswith("/drafts"):
            assert json.loads(body)["publish_at"] == "next-free-slot"
            return _json(201, {"id": 7, "status": "scheduled"})
        raise AssertionError((method, url))

    created = TypefullyClient(TYPEFULLY_KEY, transport, sleep=lambda _s: None).publish(
        social_set_id="9", text="q", filename="a.png", data=b"png", when="queue", due_at=None,
    )
    assert created["status"] == "scheduled"


def test_typefully_monthly_quota_stops_before_upload():
    def transport(method, url, headers, body):
        assert method == "GET"
        return _json(200, {"publishing_quota": {"used": 10, "remaining": 0, "resets_at": "2026-12-01T00:00:00Z"}})

    with pytest.raises(LimitReached) as caught:
        TypefullyClient(TYPEFULLY_KEY, transport, sleep=lambda _s: None).publish(
            social_set_id="9", text="nope", filename="a.png", data=b"png", when="now", due_at=None,
        )
    assert "monthly" in caught.value.message
    assert "Nothing was posted" in caught.value.message
    assert TYPEFULLY_KEY not in caught.value.message


def test_typefully_402_is_a_clear_quota_error():
    def transport(method, url, headers, body):
        if method == "GET" and url.endswith("/social-sets/9/"):
            return _json(200, {"publishing_quota": {"remaining": 2}})
        if method == "POST" and url.endswith("/media/upload"):
            return _json(201, {"media_id": "m1", "upload_url": "https://uploads.example/put"})
        if method == "PUT":
            return 200, b""
        if method == "GET" and "/media/" in url:
            return _json(200, {"status": "ready"})
        if method == "POST" and url.endswith("/drafts"):
            return 402, json.dumps({"error": {"code": "plan_required", "message": "Upgrade to publish."}}).encode()
        raise AssertionError((method, url))

    with pytest.raises(LimitReached) as caught:
        TypefullyClient(TYPEFULLY_KEY, transport, sleep=lambda _s: None).publish(
            social_set_id="9", text="hi", filename="a.png", data=b"png", when="now", due_at=None,
        )
    assert "Nothing was posted" in caught.value.message
    assert "Upgrade to publish" in caught.value.message
