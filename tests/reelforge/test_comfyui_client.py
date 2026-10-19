"""Native-ComfyUI HTTP client — every test injects a fake transport (NO network).

The client is the only thing that touches the network; a canned
:class:`FakeComfyTransport` replays scripted ``/upload/image`` / ``/prompt`` /
``/history`` / ``/view`` responses so the wrapper logic (error normalization,
pending-vs-terminal history semantics, view-URL building) is unit-tested without
a live ComfyUI server or GPU.
"""

from __future__ import annotations

import pytest

from app.services.render.backends._comfyui_client import (
    ComfyTransport,
    ComfyUIClient,
    RequestsComfyTransport,
)
from app.services.render.backends.base import BackendError


class FakeResp:
    def __init__(self, status_code=200, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body

    @property
    def text(self):
        return str(self._body)


class FakeComfyTransport:
    """Records calls + replays scripted responses per verb."""

    def __init__(self, *, json=None, multipart=None, bytes_=None):
        self.json_responses = list(json or [])
        self.multipart_responses = list(multipart or [])
        self.bytes_responses = list(bytes_ or [])
        self.json_calls = []
        self.multipart_calls = []
        self.bytes_calls = []

    def request_json(self, method, url, *, headers=None, params=None, json=None):
        self.json_calls.append({"method": method, "url": url, "json": json})
        return self.json_responses.pop(0)

    def request_multipart(self, url, *, files, data=None, headers=None):
        self.multipart_calls.append({"url": url, "files": files, "data": data})
        return self.multipart_responses.pop(0)

    def request_bytes(self, method, url, *, headers=None, params=None):
        self.bytes_calls.append({"method": method, "url": url})
        return self.bytes_responses.pop(0)


def test_default_transport_conforms_to_protocol():
    assert isinstance(RequestsComfyTransport(), ComfyTransport)


def test_client_requires_base_url():
    with pytest.raises(BackendError):
        ComfyUIClient("")


def test_upload_image_multipart_returns_name_subfolder_type():
    tp = FakeComfyTransport(
        multipart=[FakeResp(200, {"name": "abc.png", "subfolder": "", "type": "input"})]
    )
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    ref = c.upload_image("abc.png", b"\x89PNG...", image_type="input")
    assert ref == {"name": "abc.png", "subfolder": "", "type": "input"}
    call = tp.multipart_calls[0]
    assert call["url"] == "http://gpu:8188/upload/image"
    assert "image" in call["files"]
    assert call["data"]["type"] == "input"


def test_submit_prompt_returns_prompt_id():
    tp = FakeComfyTransport(json=[FakeResp(200, {"prompt_id": "p-1", "number": 3, "node_errors": {}})])
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    body = c.submit_prompt({"106": {"class_type": "X"}}, "cid-1")
    assert body["prompt_id"] == "p-1"
    call = tp.json_calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://gpu:8188/prompt"
    assert call["json"]["client_id"] == "cid-1"
    assert call["json"]["prompt"] == {"106": {"class_type": "X"}}


def test_submit_prompt_400_node_errors_raises_non_retryable():
    tp = FakeComfyTransport(
        json=[FakeResp(400, {"error": "invalid", "node_errors": {"131": ["bad pose"]}})]
    )
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    with pytest.raises(BackendError) as ei:
        c.submit_prompt({"131": {}}, "cid")
    assert ei.value.retryable is False
    assert "node_errors" in str(ei.value)


def test_submit_prompt_5xx_is_retryable():
    tp = FakeComfyTransport(json=[FakeResp(503, {"error": "overloaded"})])
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    with pytest.raises(BackendError) as ei:
        c.submit_prompt({}, "cid")
    assert ei.value.retryable is True


def test_submit_prompt_missing_prompt_id_raises():
    tp = FakeComfyTransport(json=[FakeResp(200, {"number": 1})])
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    with pytest.raises(BackendError):
        c.submit_prompt({}, "cid")


def test_get_history_empty_body_is_pending_not_failure():
    tp = FakeComfyTransport(json=[FakeResp(200, {})])
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    assert c.get_history("p-1") == {}


def test_get_history_404_is_pending_not_failure():
    tp = FakeComfyTransport(json=[FakeResp(404, {})])
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    assert c.get_history("p-1") == {}


def test_get_history_returns_entry_for_prompt_id():
    entry = {"status": {"status_str": "success", "completed": True}, "outputs": {}}
    tp = FakeComfyTransport(json=[FakeResp(200, {"p-1": entry})])
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    assert c.get_history("p-1") == entry


def test_get_history_5xx_raises_retryable():
    tp = FakeComfyTransport(json=[FakeResp(500, {})])
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    with pytest.raises(BackendError) as ei:
        c.get_history("p-1")
    assert ei.value.retryable is True


def test_view_url_builds_query():
    c = ComfyUIClient("http://gpu:8188", transport=FakeComfyTransport())
    url = c.view_url("Fun_00001.mp4", "sub", "output")
    assert url.startswith("http://gpu:8188/view?")
    assert "filename=Fun_00001.mp4" in url
    assert "subfolder=sub" in url
    assert "type=output" in url


def test_fetch_view_returns_raw_bytes():
    tp = FakeComfyTransport(bytes_=[FakeResp(200, None, content=b"MP4DATA")])
    c = ComfyUIClient("http://gpu:8188", transport=tp)
    assert c.fetch_view("Fun_00001.mp4", "", "output") == b"MP4DATA"


def test_download_bytes_network_error_is_retryable():
    class Boom:
        def request_bytes(self, *a, **k):
            raise ConnectionError("refused")

        def request_json(self, *a, **k):
            raise ConnectionError("refused")

        def request_multipart(self, *a, **k):
            raise ConnectionError("refused")

    c = ComfyUIClient("http://gpu:8188", transport=Boom())
    with pytest.raises(BackendError) as ei:
        c.download_bytes("https://cdn/x.png")
    assert ei.value.retryable is True
