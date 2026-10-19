"""Very ___ Time media lane: Seedance i2v/r2v rows, the ModelArk adapter, the
structured brief, multi-reference /media/videos and catalog-model B-roll shots.

Only sockets are faked (scripted sessions); the catalog, gateway, executor,
adapters and wallet ledger are the real code.
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

from app.domains.gateway import media_catalog as mc
from app.domains.gateway import video_brief as vb
from app.domains.gateway.provider_execution import MediaProviderExecutor
from app.domains.routing import license_class as lc
from app.domains.routing.providers import seedance_ark as ark
from app.domains.routing.providers.kling_fal import KlingError
from app.domains.wallet.repository import ENTRY_GRANT, WalletRepository
from app.models.db import media_jobs, models  # noqa: F401 - register tables
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

NEW_IDS = {
    "bytedance/seedance-2.0-i2v": ("kling-fal", "bytedance/seedance-2.0/image-to-video", ("prompt", "image")),
    "bytedance/seedance-2.0-r2v": ("kling-fal", "bytedance/seedance-2.0/reference-to-video", ("prompt", "images")),
    "bytedance/seedance-2.0-i2v-ark": ("ark", ark.DEFAULT_SEEDANCE_ARK_MODEL, ("prompt", "image")),
    "bytedance/seedance-2.0-r2v-ark": ("ark", ark.DEFAULT_SEEDANCE_ARK_MODEL, ("prompt", "images")),
}


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = {}
        self.text = str(body)

    def json(self):
        return self._body


class FakeSession:
    """Scripted ``requests.Session`` stand-in that records every call."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def request(self, method, url, *, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return self._script.pop(0)


def _fal_submit():
    return _Resp(200, {"request_id": "req-1", "status_url": "https://q/s", "response_url": "https://q/r"})


# --------------------------------------------------------------------------- #
# Catalog rows
# --------------------------------------------------------------------------- #
def test_new_rows_exist_route_and_carry_price_sources():
    listed = {m.id for m in mc.video_models()}
    for mid, (provider, ref, inputs) in NEW_IDS.items():
        m = mc.get_model(mid)
        assert m is not None and mid in listed, mid
        assert (m.provider, m.model_ref, m.inputs) == (provider, ref, inputs)
        assert m.price_source.startswith("https://") and m.price_date == "2026-10-05"
        assert m.price_micros > 0 and m.unit == "second" and m.resolution == "720p"
        assert not m.legacy and not m.description.startswith("Legacy:")
        assert lc.model_license(mid).license_class == lc.COMMERCIAL_API
        assert lc.is_model_sellable(mid)


def test_fal_rows_are_verified_and_ark_rows_say_unverified():
    for mid in ("bytedance/seedance-2.0-i2v", "bytedance/seedance-2.0-r2v"):
        m = mc.get_model(mid)
        assert m.price_verified and m.price_micros == 302_400
        assert m.price_source == f"https://fal.ai/models/{m.model_ref}"
    for mid in ("bytedance/seedance-2.0-i2v-ark", "bytedance/seedance-2.0-r2v-ark"):
        m = mc.get_model(mid)
        assert not m.price_verified and "unverified" in m.description


def test_fal_duration_rows_exist_for_the_new_paths():
    from app.domains.gateway.fal_duration import DurationUnsupported, duration_extra

    for ref in ("bytedance/seedance-2.0/image-to-video", "bytedance/seedance-2.0/reference-to-video"):
        assert duration_extra(ref, 5) == {"duration": "5"}
        with pytest.raises(DurationUnsupported):
            duration_extra(ref, 3)


# --------------------------------------------------------------------------- #
# fal adapter wire bodies (through the shared executor)
# --------------------------------------------------------------------------- #
def _submit(model_id, *, image_url="", input_refs=(), session=None, api_key="k"):
    from app.domains.gateway.media_gateway import _provider_request

    m = mc.get_model(model_id)
    req = _provider_request(m, correlation_id="c1", prompt="p", cost_micros=5 * m.price_micros,
                            duration_seconds=5, aspect_ratio="9:16", image_url=image_url,
                            input_refs=input_refs)
    return MediaProviderExecutor(api_key=api_key, session_http=session).submit(req)


def test_fal_i2v_sends_image_url_as_first_frame():
    fake = FakeSession([_fal_submit()])
    _submit("bytedance/seedance-2.0-i2v", image_url="https://cdn.example.com/f.png", session=fake)
    call = fake.calls[0]
    assert call["url"] == "https://queue.fal.run/bytedance/seedance-2.0/image-to-video"
    assert call["json"]["image_url"] == "https://cdn.example.com/f.png"
    assert "image_urls" not in call["json"] and call["json"]["duration"] == "5"


def test_fal_r2v_sends_the_whole_reference_list():
    fake = FakeSession([_fal_submit()])
    refs = ("https://cdn.example.com/1.png", "https://cdn.example.com/2.png", "https://cdn.example.com/3.png")
    _submit("bytedance/seedance-2.0-r2v", input_refs=refs, session=fake)
    body = fake.calls[0]["json"]
    assert fake.calls[0]["url"].endswith("/bytedance/seedance-2.0/reference-to-video")
    assert body["image_urls"] == list(refs) and "image_url" not in body


# --------------------------------------------------------------------------- #
# ModelArk adapter
# --------------------------------------------------------------------------- #
def test_ark_default_endpoint_is_international(monkeypatch):
    monkeypatch.delenv("ARK_BASE_URL", raising=False)
    assert ark.ark_base_url() == "https://ark.ap-southeast.bytepluses.com/api/v3"
    assert "volces" not in ark.SeedanceArkAdapter(api_key="k").base_url
    from engine.services.api_services import video_seedance

    assert video_seedance.DEFAULT_ARK_BASE_URL == ark.DEFAULT_ARK_BASE_URL


def test_ark_base_url_override(monkeypatch):
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.example.com/api/v3/")
    fake = FakeSession([_Resp(200, {"id": "t-1"})])
    ark.SeedanceArkAdapter(api_key="k", session=fake).submit(prompt="p")
    assert fake.calls[0]["url"] == "https://ark.example.com/api/v3/contents/generations/tasks"


def test_ark_i2v_request_body_has_text_and_first_frame(monkeypatch):
    monkeypatch.delenv("ARK_BASE_URL", raising=False)
    fake = FakeSession([_Resp(200, {"id": "t-1"})])
    result = _submit("bytedance/seedance-2.0-i2v-ark", image_url="https://cdn.example.com/f.png",
                     session=fake)
    assert result.handle.run_id == "t-1" and result.handle.provider_key == "ark"
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"
    assert call["headers"]["Authorization"] == "Bearer k"
    body = call["json"]
    assert body["model"] == ark.DEFAULT_SEEDANCE_ARK_MODEL
    assert body["content"] == [
        {"type": "text", "text": "p"},
        {"type": "image_url", "image_url": {"url": "https://cdn.example.com/f.png"}, "role": "first_frame"},
    ]
    assert body["duration"] == 5 and body["ratio"] == "9:16" and body["resolution"] == "720p"


def test_ark_r2v_request_body_tags_every_reference():
    fake = FakeSession([_Resp(200, {"id": "t-2"})])
    refs = ("https://cdn.example.com/1.png", "https://cdn.example.com/2.png")
    _submit("bytedance/seedance-2.0-r2v-ark", input_refs=refs, session=fake)
    images = [c for c in fake.calls[0]["json"]["content"] if c["type"] == "image_url"]
    assert [(c["image_url"]["url"], c["role"]) for c in images] == [
        (refs[0], "reference_image"), (refs[1], "reference_image")]


def test_ark_missing_key_is_a_clean_not_configured_error(monkeypatch):
    from reelforge_provider_adapter.execution import ProviderExecutionException

    monkeypatch.delenv("ARK_API_KEY", raising=False)
    with pytest.raises(KlingError, match="not configured"):
        ark.SeedanceArkAdapter(session=FakeSession([])).submit(prompt="p")
    with pytest.raises(ProviderExecutionException) as info:
        _submit("bytedance/seedance-2.0-i2v-ark", image_url="https://cdn.example.com/f.png",
                session=FakeSession([]), api_key="")
    assert info.value.error.category == "auth" and "ARK_API_KEY" in info.value.error.message
    assert info.value.error.acceptance == "not_accepted"


def test_ark_poll_success_and_failure():
    ok = FakeSession([_Resp(200, {"id": "t-1"}), _Resp(200, {"status": "running"}),
                      _Resp(200, {"status": "succeeded", "content": {"video_url": "https://cdn/o.mp4"}})])
    executor = MediaProviderExecutor(api_key="k", session_http=ok)
    from app.domains.gateway.media_gateway import _provider_request

    m = mc.get_model("bytedance/seedance-2.0-i2v-ark")
    first = executor.submit(_provider_request(m, correlation_id="c", prompt="p", cost_micros=1,
                                              duration_seconds=5, image_url="https://cdn.example.com/f.png"))
    running = executor.poll(first.handle)
    assert running.handle.state == "IN_PROGRESS"
    done = executor.poll(running.handle)
    assert done.handle.state == "COMPLETED" and done.outputs[0].reference == "https://cdn/o.mp4"
    assert ok.calls[1]["url"].endswith("/contents/generations/tasks/t-1") and ok.calls[1]["method"] == "GET"

    bad = FakeSession([_Resp(200, {"status": "failed", "error": {"message": "content policy"}})])
    failed = MediaProviderExecutor(api_key="k", session_http=bad).poll(first.handle)
    assert failed.handle.state == "FAILED" and "content policy" in failed.error.message
    assert not failed.cost.success


def test_ark_submit_errors_follow_the_taxonomy():
    with pytest.raises(KlingError) as info:
        ark.SeedanceArkAdapter(api_key="k", session=FakeSession([_Resp(401, {})])).submit(prompt="p")
    assert info.value.kind == "auth"
    with pytest.raises(KlingError) as info:
        ark.SeedanceArkAdapter(api_key="k", session=FakeSession([_Resp(503, {})])).submit(prompt="p")
    assert info.value.may_have_been_accepted


# --------------------------------------------------------------------------- #
# Brief builder and reference validation
# --------------------------------------------------------------------------- #
def test_brief_order_and_image_role_lines():
    refs = [vb.Reference("https://cdn.example.com/id.png", "identity"),
            vb.Reference("uploads/u1/still.png", "first_frame"),
            vb.Reference("https://cdn.example.com/look.png", "style")]
    text = vb.build_brief_prompt(format="9:16, 5 s, 720p", references=refs, action="He sips tea.",
                                 camera="locked-off", continuity="same oxblood shirt",
                                 audio="room tone; no music", constraints="no text appearing")
    lines = text.split("\n")
    assert [line.split(":", 1)[0] for line in lines] == [
        "Format", "Reference roles", "Action", "Camera", "Continuity", "Audio", "Constraints"]
    roles = lines[1]
    assert "@Image1 is the first frame." in roles
    assert "@Image2 locks the subject's face" in roles and "do not copy @Image2's background" in roles
    assert "@Image3 sets the look only" in roles
    assert [r.role for r in vb.ordered_references(refs)] == ["first_frame", "identity", "style"]


def test_brief_skips_empty_blocks_and_caps_length():
    text = vb.build_brief_prompt(format="9:16", references=[], action="a\nb")
    assert text == "Format: 9:16\nAction: a b"
    long = vb.build_brief_prompt(format="x" * 5000, references=[], action="y" * 5000,
                                 camera="z" * 5000, continuity="w" * 5000, audio="v" * 5000,
                                 constraints="u" * 5000)
    assert len(long) <= vb.MAX_BRIEF_CHARS
    assert long.startswith("Format: " + "x" * vb.MAX_FIELD_CHARS + "\n")


@pytest.mark.parametrize("bad", [
    {"format": "", "action": "a"},
    {"format": "9:16", "action": ""},
    {"format": "9:16", "action": "a", "mood": "x"},
])
def test_brief_validation_errors(bad):
    with pytest.raises(vb.BriefError):
        vb.brief_from_mapping(bad, [])


@pytest.mark.parametrize("url", [
    "http://cdn.example.com/a.png", "https://127.0.0.1/a.png", "https://10.0.0.5/a.png",
    "https://169.254.169.254/latest", "https://[::1]/a.png", "https://localhost/a.png",
    "https://metadata.google.internal/x", "https://user:pw@cdn.example.com/a.png",
    "ftp://cdn.example.com/a.png", "../etc/passwd", "file:///etc/passwd",
])
def test_reference_url_validation_rejects_private_and_odd_urls(url):
    with pytest.raises(vb.BriefError):
        vb.Reference(url, "identity")


def test_reference_list_limits():
    with pytest.raises(vb.BriefError, match="at most 4"):
        vb.parse_references([{"url": f"https://cdn.example.com/{i}.png", "role": "style"} for i in range(5)])
    with pytest.raises(vb.BriefError, match="one reference can be the first frame"):
        vb.parse_references([{"url": "https://cdn.example.com/1.png", "role": "first_frame"},
                             {"url": "https://cdn.example.com/2.png", "role": "first_frame"}])
    with pytest.raises(vb.BriefError, match="role"):
        vb.parse_references([{"url": "https://cdn.example.com/1.png", "role": "mood"}])
    keyed = vb.parse_references([{"key": "jobs/j1/story8/frame-1.png", "role": "first_frame"}])
    assert keyed[0].is_key


# --------------------------------------------------------------------------- #
# POST /media/videos with references + brief
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(monkeypatch):
    mod = importlib.import_module("app.domains.gateway.media_router")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _gs():
        s = factory()
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
        repo.append_entry(acct.id, entry_type=ENTRY_GRANT, reason="topup", available_delta=100_000_000)

    class _U:
        id = "u1"

    monkeypatch.setenv("FAL_KEY", "fal-test-key")
    monkeypatch.setattr(mod, "get_session", _gs)
    monkeypatch.setattr(mod, "_require_db", lambda rid: None)
    monkeypatch.setattr(mod, "_resolve_user", lambda req, s, rid: _U())
    monkeypatch.setattr(mod, "_IMPORT_ERROR", None)
    from app.domains.gateway import media_gateway

    fake = FakeSession([_fal_submit()])
    original = media_gateway.create_video

    def _bound(session, **kwargs):
        kwargs["session_http"] = fake
        return original(session, **kwargs)

    monkeypatch.setattr(media_gateway, "create_video", _bound)
    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(HttpException, lambda r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app), fake, monkeypatch


def test_references_and_brief_build_the_provider_request(client):
    tc, fake, monkeypatch = client
    from app.domains.media import service as media_service
    from app.platform.storage import r2

    owned = []
    monkeypatch.setattr(media_service, "require_owned_asset",
                        lambda session, *, user_id, key: owned.append((user_id, key)))

    class _R2:
        def presign_get(self, key, expires=0):
            return f"https://bucket.r2.example.com/{key}?sig=1"

    monkeypatch.setattr(r2, "get_r2_client", lambda: _R2())
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0-r2v", "duration": 5,
        "references": [{"url": "https://cdn.example.com/sheet.png", "role": "identity"},
                       {"url": "uploads/u1/still.png", "role": "first_frame"}],
        "brief": {"format": "9:16, 5 s, 720p", "action": "He sets the tea glass down.",
                  "camera": "locked-off", "audio": "room tone"},
    })
    assert resp.status_code == 200, resp.text
    assert owned == [("u1", "uploads/u1/still.png")]
    body = fake.calls[0]["json"]
    assert fake.calls[0]["url"].endswith("/bytedance/seedance-2.0/reference-to-video")
    assert body["image_urls"] == ["https://bucket.r2.example.com/uploads/u1/still.png?sig=1",
                                  "https://cdn.example.com/sheet.png"]
    assert body["prompt"].startswith("Format: 9:16, 5 s, 720p\nReference roles: @Image1 is the first frame.")
    assert "@Image2 locks the subject's face" in body["prompt"]


def test_first_frame_reference_on_i2v_becomes_image_url(client):
    tc, fake, _ = client
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0-i2v", "prompt": "slow push-in", "duration": 5,
        "references": [{"url": "https://cdn.example.com/f.png", "role": "first_frame"}]})
    assert resp.status_code == 200, resp.text
    assert fake.calls[0]["json"]["image_url"] == "https://cdn.example.com/f.png"


def test_image_url_alone_still_works(client):
    tc, fake, _ = client
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0-i2v", "prompt": "x", "duration": 5,
        "image_url": "https://cdn.example.com/f.png"})
    assert resp.status_code == 200, resp.text
    assert fake.calls[0]["json"]["image_url"] == "https://cdn.example.com/f.png"


def test_references_to_a_text_to_video_model_are_a_400(client):
    tc, fake, _ = client
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0", "prompt": "x", "duration": 5,
        "references": [{"url": "https://cdn.example.com/f.png", "role": "first_frame"}]})
    assert resp.status_code == 400
    assert "does not take reference images" in resp.json()["message"]
    assert fake.calls == []


def test_identity_reference_on_a_single_image_model_is_a_400(client):
    tc, fake, _ = client
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0-i2v", "prompt": "x", "duration": 5,
        "references": [{"url": "https://cdn.example.com/f.png", "role": "identity"}]})
    assert resp.status_code == 400 and fake.calls == []


def test_private_ip_reference_and_image_url_are_rejected(client):
    tc, fake, _ = client
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0-i2v", "prompt": "x", "duration": 5,
        "references": [{"url": "https://192.168.1.10/f.png", "role": "first_frame"}]})
    assert resp.status_code == 400
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0-i2v", "prompt": "x", "duration": 5,
        "image_url": "https://127.0.0.1/f.png"})
    assert resp.status_code == 400 and fake.calls == []


def test_unowned_reference_key_is_403(client):
    tc, fake, monkeypatch = client
    from app.domains.media import service as media_service

    def _deny(session, *, user_id, key):
        raise media_service.MediaDomainError(403, "media key does not belong to the caller")

    monkeypatch.setattr(media_service, "require_owned_asset", _deny)
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0-i2v", "duration": 5,
        "references": [{"url": "uploads/u2/still.png", "role": "first_frame"}],
        "brief": {"format": "9:16", "action": "a"}})
    assert resp.status_code == 403 and fake.calls == []


def test_bad_brief_is_a_400(client):
    tc, _, _ = client
    resp = tc.post("/api/v1/media/videos", json={
        "model": "bytedance/seedance-2.0-i2v", "duration": 5,
        "brief": {"format": " ", "action": "a"}})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# B-roll shots: catalog model via the gateway executor, old path unchanged
# --------------------------------------------------------------------------- #
@pytest.fixture
def broll(monkeypatch):
    from app.domains.broll import service

    state = {"persisted": [], "rehosted": [], "params": {}}
    monkeypatch.setattr(service, "_load_job_context", lambda jid: ("u1", dict(state["params"])))
    monkeypatch.setattr(service, "_set_progress", lambda jid, p: None)
    monkeypatch.setattr(service, "_sleep", lambda s: None)
    monkeypatch.setattr(service, "_presign_key", lambda key: f"https://bucket.r2.example.com/{key}")
    monkeypatch.setattr(service, "_download_to_temp", lambda url: state.setdefault("downloaded", url) and "/nonexistent.mp4")
    monkeypatch.setattr(service, "_rehost_clip", lambda jid, path: state["rehosted"].append(path) or f"jobs/{jid}/broll/x.mp4")
    monkeypatch.setattr(service, "_persist_and_complete", lambda **kw: state["persisted"].append(kw))
    monkeypatch.setenv("FAL_KEY", "fal-test-key")
    return service, state, monkeypatch


def test_broll_video_model_runs_through_the_gateway(broll):
    service, state, monkeypatch = broll
    fake = FakeSession([_fal_submit(), _Resp(200, {"status": "IN_PROGRESS"}), _Resp(200, {"status": "COMPLETED"}),
                        _Resp(200, {"video": {"url": "https://cdn/out.mp4"}})])
    monkeypatch.setattr(service, "_executor", lambda: MediaProviderExecutor(session_http=fake))

    def _no_provider():
        raise AssertionError("the B-roll provider must not run for a catalog model")

    monkeypatch.setattr("app.domains.broll.get_broll_provider", _no_provider)
    state["params"] = {
        "_correlation_id": "story8:s1:0", "prompt": "", "mode": "i2v", "width": 720, "height": 1280,
        "duration_s": 3.0, "video_model": "bytedance/seedance-2.0-r2v", "credits_cost": 0,
        "references": [{"key": "chars/c1/sheet.png", "role": "identity"},
                       {"key": "jobs/s1/story8/frame-1.png", "role": "first_frame"}],
        "brief": {"format": "9:16, 4 s, 720p", "action": "She looks up.", "camera": "locked-off"},
    }
    out = service.run_broll_generation("j1")
    assert out["video_model"] == "bytedance/seedance-2.0-r2v" and out["duration"] == 4.0
    body = fake.calls[0]["json"]
    assert body["image_urls"] == ["https://bucket.r2.example.com/jobs/s1/story8/frame-1.png",
                                  "https://bucket.r2.example.com/chars/c1/sheet.png"]
    assert body["duration"] == "4"  # 3 s snapped to the nearest length Seedance renders
    assert body["aspect_ratio"] == "9:16"
    assert body["prompt"].startswith("Format: 9:16, 4 s, 720p\nReference roles: @Image1 is the first frame.")
    assert state["downloaded"] == "https://cdn/out.mp4"
    meta = state["persisted"][0]["meta"]
    assert meta["video_model"] == "bytedance/seedance-2.0-r2v" and meta["provider_job_id"] == "req-1"
    assert meta["reference_roles"] == ["identity", "first_frame"]


def test_broll_image_key_alone_is_the_first_frame(broll):
    service, state, monkeypatch = broll
    fake = FakeSession([_fal_submit(), _Resp(200, {"status": "COMPLETED"}),
                        _Resp(200, {"video": {"url": "https://cdn/out.mp4"}})])
    monkeypatch.setattr(service, "_executor", lambda: MediaProviderExecutor(session_http=fake))
    state["params"] = {"prompt": "slow push-in", "image_key": "jobs/s1/story8/frame-2.png",
                       "video_model": "bytedance/seedance-2.0-i2v", "duration_s": 5}
    service.run_broll_generation("j2")
    body = fake.calls[0]["json"]
    assert body["image_url"] == "https://bucket.r2.example.com/jobs/s1/story8/frame-2.png"
    assert body["prompt"] == "slow push-in"


def test_broll_catalog_failure_raises_for_refund(broll):
    service, state, monkeypatch = broll
    fake = FakeSession([_fal_submit(), _Resp(200, {"status": "FAILED", "error": "nsfw"})])
    monkeypatch.setattr(service, "_executor", lambda: MediaProviderExecutor(session_http=fake))
    state["params"] = {"prompt": "x", "image_key": "k/f.png", "video_model": "bytedance/seedance-2.0-i2v"}
    with pytest.raises(RuntimeError, match="nsfw"):
        service.run_broll_generation("j3")
    assert state["persisted"] == []


def test_broll_catalog_refuses_urls_and_text_models(broll):
    service, state, _ = broll
    state["params"] = {"prompt": "x", "video_model": "bytedance/seedance-2.0-r2v",
                       "references": [{"key": "https://cdn.example.com/a.png", "role": "identity"}]}
    with pytest.raises(RuntimeError, match="storage keys"):
        service.run_broll_generation("j4")
    state["params"] = {"prompt": "x", "video_model": "bytedance/seedance-2.0",
                       "image_key": "k/f.png"}
    with pytest.raises(RuntimeError, match="does not take reference images"):
        service.run_broll_generation("j5")
    state["params"] = {"prompt": "x", "video_model": "nope/none"}
    with pytest.raises(RuntimeError, match="not a video model"):
        service.run_broll_generation("j6")


def test_broll_without_video_model_keeps_the_provider_path(broll):
    service, state, monkeypatch = broll
    calls = []

    class _Provider:
        def is_enabled(self):
            return True

        def generate_clip(self, prompt, **kw):
            calls.append((prompt, kw))
            return {"clip_path": "/nonexistent-clip.mp4", "duration": 5.0}

    monkeypatch.setattr("app.domains.broll.get_broll_provider", lambda: _Provider())
    monkeypatch.setattr(service, "_executor", lambda: pytest.fail("gateway must not run"))
    monkeypatch.setattr(service, "_resolve_image_url", lambda mode, key: f"https://bucket.r2.example.com/{key}")
    state["params"] = {"prompt": "city at night", "mode": "i2v", "image_key": "k/f.png"}
    out = service.run_broll_generation("j7")
    assert calls and calls[0][0] == "city at night"
    assert calls[0][1]["image_url"] == "https://bucket.r2.example.com/k/f.png"
    assert out["broll_key"] == "jobs/j7/broll/x.mp4"
    assert state["persisted"][0]["meta"]["mode"] == "i2v"
