"""Character turnaround sheets and reference-conditioned images (Very ___ Time v2).

Covers: the fal image body with and without reference images, the executor
passing references to fal and refusing them elsewhere, the Seedream 4.5 edit
row, the house image lane, the sheet prompt, sheet generation (owned asset +
``sheet`` reference binding), the newest-sheet lookup and the priced endpoint
(debit, refund on failure, ownership, rate limit).
"""

from __future__ import annotations

import hashlib
import io
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.characters import hub, turnaround  # noqa: F401 - hub registers its tables
from app.domains.gateway import _fal_image, house_image as house_image_mod, media_catalog, provider_execution
from app.domains.gateway.media_gateway import _provider_request
from app.domains.media.repository import MediaRepository
from app.domains.media.service import require_owned_asset
from app.integrations.railyard import meters  # noqa: F401 - registers the outbox table
from app.models.db import character_refs, characters  # noqa: F401 - registers the tables
from app.models.db.base import Base
from app.models.db.character_refs import CharacterReference
from app.models.db.characters import Character
from app.models.db.models import CreditLedger, Job, User
from app.models.db.repositories import CreditRepository
from app.models.exception import HttpException
from app.services import ratelimit
from app.utils import utils

KEY = "sheet-key"
H = {"x-api-key": KEY}


def _png(colour=(120, 60, 40), size=(640, 640)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return out.getvalue()


# --------------------------------------------------------------------------- #
# fal body and executor
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _FalHttp:
    def __init__(self):
        self.posts: list[dict] = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        if method == "POST":
            self.posts.append(json)
            return _Resp({"request_id": "r1", "status_url": "https://q/s", "response_url": "https://q/r"})
        if url.endswith("/s"):
            return _Resp({"status": "COMPLETED"})
        return _Resp({"images": [{"url": "https://cdn.example.com/out.png"}]})


def test_fal_body_carries_image_urls_only_when_given():
    http = _FalHttp()
    assert _fal_image.fal_generate_image("fal-ai/x", "a cat", api_key="k", session=http) == \
        "https://cdn.example.com/out.png"
    _fal_image.fal_generate_image("fal-ai/x", "a cat", api_key="k", session=http,
                                  image_urls=("https://a.example.com/1.png", "", "https://a.example.com/2.png"))
    assert http.posts[0] == {"prompt": "a cat"}
    assert http.posts[1] == {"prompt": "a cat",
                             "image_urls": ["https://a.example.com/1.png", "https://a.example.com/2.png"]}


def _row(model_id):
    row = media_catalog.get_row(model_id)
    assert row is not None
    return row


def test_executor_sends_references_to_fal():
    http = _FalHttp()
    row = _row("bytedance-seed/seedream-4.5-edit")
    request = _provider_request(row, correlation_id="c1", prompt="sheet", cost_micros=row.price_micros,
                                input_refs=("https://a.example.com/g.png",))
    result = provider_execution.MediaProviderExecutor(api_key="k", session_http=http).submit(request)
    assert result.outputs[0].reference == "https://cdn.example.com/out.png"
    assert http.posts[0]["image_urls"] == ["https://a.example.com/g.png"]


def test_executor_refuses_references_on_other_image_providers():
    row = _row("openai/gpt-image-1")
    request = _provider_request(row, correlation_id="c1", prompt="sheet", cost_micros=row.price_micros,
                                input_refs=("https://a.example.com/g.png",))
    with pytest.raises(Exception) as caught:
        provider_execution.MediaProviderExecutor(api_key="k").submit(request)
    assert "reference images" in str(caught.value)


def test_seedream_edit_row_takes_reference_images():
    row = _row("bytedance-seed/seedream-4.5-edit")
    assert row.modality == media_catalog.IMAGE and row.provider == "fal-image"
    assert row.model_ref == "fal-ai/bytedance/seedream/v4.5/edit"
    assert "images" in row.inputs and row.price_micros == 40_000 and row.price_verified
    assert row.id in {m.id for m in media_catalog.image_models()}


# --------------------------------------------------------------------------- #
# house image lane
# --------------------------------------------------------------------------- #
class _FakeExecutor:
    calls: list = []

    def submit(self, request):
        _FakeExecutor.calls.append(request)
        return SimpleNamespace(outputs=(SimpleNamespace(reference="https://cdn.example.com/x.png"),))


def test_house_image_sends_references_and_downloads(monkeypatch):
    _FakeExecutor.calls = []
    monkeypatch.setattr(provider_execution, "MediaProviderExecutor", _FakeExecutor)
    data = house_image_mod.house_image("a host", model_id="bytedance-seed/seedream-4.5-edit",
                                       reference_urls=("https://a.example.com/g.png",), negative="logo",
                                       download=lambda url: b"img:" + url.encode())
    assert data == b"img:https://cdn.example.com/x.png"
    request = _FakeExecutor.calls[0]
    assert request.input_refs == ("https://a.example.com/g.png",)
    assert request.prompt == "a host. Avoid: logo"
    assert request.parameters["image_mode"] == "reference"


def test_house_image_refusals(monkeypatch):
    monkeypatch.setattr(provider_execution, "MediaProviderExecutor", _FakeExecutor)
    with pytest.raises(LookupError):
        house_image_mod.house_image("x", model_id="nobody/none")
    with pytest.raises(ValueError, match="does not take reference images"):
        house_image_mod.house_image("x", model_id="ideogram/ideogram-v3", reference_urls=("https://a.example.com/g",))
    with pytest.raises(ValueError, match="prompt"):
        house_image_mod.house_image("  ", model_id="ideogram/ideogram-v3")


# --------------------------------------------------------------------------- #
# sheet prompt
# --------------------------------------------------------------------------- #
def test_sheet_prompt_has_three_views_and_the_guard_text():
    prompt, negative = turnaround.sheet_prompt(["70s tailor", "silver moustache"], style="console look",
                                               wearing="an oxblood shirt")
    for part in ("turnaround sheet", "front view", "side profile view", "back view", "A-pose",
                 "flat blue-grey studio background", "70s tailor, silver moustache", "wearing an oxblood shirt",
                 "console look", "No text other than the garment print", "No logos, no flags"):
        assert part in prompt
    for part in ("different person", "extra limbs", "text", "watermark"):
        assert part in negative
    assert "one recurring character" in turnaround.sheet_prompt([])[0]


# --------------------------------------------------------------------------- #
# DB fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def maker(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    ratelimit._local_buckets.clear()
    monkeypatch.delenv(turnaround.SHEET_CREDITS_ENV, raising=False)
    monkeypatch.delenv(turnaround.SHEET_MODEL_ENV, raising=False)
    monkeypatch.delenv(turnaround.SHEET_REFERENCE_MODEL_ENV, raising=False)
    with factory() as s:
        s.add(User(email="sheet@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.add(User(email="other@example.com", api_key_hash=hashlib.sha256(b"other").hexdigest()))
        s.commit()
    return factory


def _uid(maker, email="sheet@example.com") -> str:
    with maker() as s:
        return s.query(User).filter(User.email == email).one().id


def _owned_upload(session, user_id, key):
    repo = MediaRepository(session)
    repo.reserve_owned_upload(user_id, key, content_type="image/png", size=10)
    repo.register_owned_upload(user_id, key, "image")


def _character(maker, email="sheet@example.com", refs=("uploads/u/ref.png",)) -> str:
    uid = _uid(maker, email)
    with maker() as s:
        for key in refs:
            _owned_upload(s, uid, key)
        row = Character(user_id=uid, name="Selim", descriptors=["70s tailor", "silver moustache"],
                        reference_images=list(refs), negative=[], style="atelier film", lora_ref="",
                        identity_key="v2|" + "c" * 64)
        s.add(row)
        s.commit()
        return row.id


class _Fakes:
    def __init__(self, fail=False):
        self.images: list[dict] = []
        self.uploads: dict[str, bytes] = {}
        self.fail = fail

    def image(self, prompt, *, model_id, reference_urls=(), negative=""):
        self.images.append({"prompt": prompt, "model": model_id, "refs": list(reference_urls), "negative": negative})
        if self.fail:
            raise RuntimeError("provider down")
        return _png(size=(800, 600))

    def upload(self, key, data, content_type):
        self.uploads[key] = data

    @staticmethod
    def presign(key):
        return f"https://signed.example.com/{key}"


# --------------------------------------------------------------------------- #
# generate_sheet / sheet_key
# --------------------------------------------------------------------------- #
def test_generate_sheet_without_references_uses_the_text_model(maker):
    fakes, uid = _Fakes(), _uid(maker)
    with maker() as s:
        out = turnaround.generate_sheet(s, user_id=uid, descriptors=["a calm host"], wearing="an oxblood shirt",
                                        image_fn=fakes.image, upload_fn=fakes.upload, presign_fn=fakes.presign)
        require_owned_asset(s, user_id=uid, key=out["key"])  # a caller-owned upload
    assert out["model"] == "ideogram/ideogram-v3" and out["bound"] is False and out["character_id"] is None
    assert out["key"].startswith("uploads/sheets/") and out["key"].endswith(".png")
    assert fakes.images[0]["refs"] == []
    with Image.open(io.BytesIO(fakes.uploads[out["key"]])) as img:
        assert img.size == (1536, 1024) and img.format == "PNG"


def test_generate_sheet_with_references_binds_a_sheet_reference(maker):
    fakes, uid = _Fakes(), _uid(maker)
    cid = _character(maker)
    with maker() as s:
        out = turnaround.generate_sheet(s, user_id=uid, descriptors=["70s tailor"], character_id=cid,
                                        reference_keys=["uploads/u/ref.png", "https://evil.example.com/x.png"],
                                        image_fn=fakes.image, upload_fn=fakes.upload, presign_fn=fakes.presign)
        s.commit()
    assert out["model"] == "bytedance-seed/seedream-4.5-edit" and out["bound"] is True
    assert fakes.images[0]["refs"] == ["https://signed.example.com/uploads/u/ref.png"]
    assert fakes.images[0]["prompt"].startswith("The reference images show the character")
    with maker() as s:
        roles = {r.r2_key: r.role for r in s.query(CharacterReference).filter_by(character_id=cid)}
        assert roles == {out["key"]: "sheet"}
        assert out["key"] in s.get(Character, cid).reference_images
        assert turnaround.sheet_key(s, cid) == out["key"]


def test_generate_sheet_refuses_someone_elses_reference(maker):
    fakes = _Fakes()
    other = _uid(maker, "other@example.com")
    with maker() as s:
        _owned_upload(s, other, "uploads/o/theirs.png")
        s.commit()
    with maker() as s, pytest.raises(turnaround.SheetError) as caught:
        turnaround.generate_sheet(s, user_id=_uid(maker), descriptors=["x"], reference_keys=["uploads/o/theirs.png"],
                                  image_fn=fakes.image, upload_fn=fakes.upload, presign_fn=fakes.presign)
    assert caught.value.status_code == 403 and fakes.images == []


def test_sheet_key_is_the_newest_sheet(maker):
    cid, uid = _character(maker, refs=()), _uid(maker)
    now = datetime.now(timezone.utc)
    with maker() as s:
        s.add(CharacterReference(character_id=cid, user_id=uid, r2_key="uploads/a.png", role="sheet",
                                 created_at=now - timedelta(minutes=5)))
        s.add(CharacterReference(character_id=cid, user_id=uid, r2_key="uploads/face.png", role="face",
                                 created_at=now))
        s.add(CharacterReference(character_id=cid, user_id=uid, r2_key="uploads/b.png", role="sheet",
                                 created_at=now - timedelta(minutes=1)))
        s.commit()
    with maker() as s:
        assert turnaround.sheet_key(s, cid) == "uploads/b.png"
        assert turnaround.sheet_key(s, "nobody") is None


# --------------------------------------------------------------------------- #
# endpoint
# --------------------------------------------------------------------------- #
def _client() -> TestClient:
    app = FastAPI()
    app.include_router(turnaround.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def _balance(maker) -> int:
    with maker() as s:
        return CreditRepository(s).balance(_uid(maker))


def _wire(monkeypatch, fakes):
    monkeypatch.setattr(turnaround, "_default_image", fakes.image)
    monkeypatch.setattr(turnaround, "_default_upload", fakes.upload)
    monkeypatch.setattr(turnaround, "_default_presign", fakes.presign)
    import app.domains.gallery.service as gallery

    monkeypatch.setattr(gallery, "media_url", lambda key: f"https://signed.example.com/{key}" if key else "")


def test_endpoint_debits_then_binds_the_sheet(maker, monkeypatch):
    fakes = _Fakes()
    _wire(monkeypatch, fakes)
    cid = _character(maker)
    with maker() as s:
        CreditRepository(s).grant(_uid(maker), 3, "test_grant")
        s.commit()
    resp = _client().post(f"/api/v1/characters/{cid}/turnaround", json={"style": "console cutscene"}, headers=H)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["credits"] == 1 and data["character_id"] == cid
    assert data["image_url"] == f"https://signed.example.com/{data['key']}"
    assert _balance(maker) == 2
    assert "console cutscene" in fakes.images[0]["prompt"]
    with maker() as s:
        job = s.query(Job).filter(Job.kind == turnaround.JOB_KIND).one()
        assert job.state == turnaround.TASK_STATE_COMPLETE and job.result_key == data["key"]
        assert turnaround.sheet_key(s, cid) == data["key"]


def test_endpoint_refunds_once_when_the_image_fails(maker, monkeypatch):
    fakes = _Fakes(fail=True)
    _wire(monkeypatch, fakes)
    cid = _character(maker)
    with maker() as s:
        CreditRepository(s).grant(_uid(maker), 1, "test_grant")
        s.commit()
    resp = _client().post(f"/api/v1/characters/{cid}/turnaround", json={}, headers=H)
    assert resp.status_code == 502
    assert resp.json()["data"] == {"code": "sheet_failed", "refunded": 1}
    assert _balance(maker) == 1
    with maker() as s:
        reasons = [r.reason for r in s.query(CreditLedger).order_by(CreditLedger.id)]
        assert reasons.count(turnaround.REFUND_REASON) == 1
        assert s.query(Job).filter(Job.kind == turnaround.JOB_KIND).one().state == turnaround.TASK_STATE_FAILED


def test_endpoint_needs_credits_and_your_own_character(maker, monkeypatch):
    fakes = _Fakes()
    _wire(monkeypatch, fakes)
    mine, theirs = _character(maker), _character(maker, email="other@example.com", refs=())
    client = _client()
    assert client.post(f"/api/v1/characters/{theirs}/turnaround", json={}, headers=H).status_code == 404
    resp = client.post(f"/api/v1/characters/{mine}/turnaround", json={}, headers=H)
    assert resp.status_code == 402 and resp.json()["data"]["code"] == "credits_required"
    assert fakes.images == []


def test_endpoint_is_rate_limited(maker, monkeypatch):
    fakes = _Fakes()
    _wire(monkeypatch, fakes)
    monkeypatch.setenv(turnaround.SHEET_CREDITS_ENV, "0")
    cid = _character(maker)
    client = _client()
    codes = [client.post(f"/api/v1/characters/{cid}/turnaround", json={}, headers=H).status_code
             for _ in range(turnaround.RATE_LIMIT + 1)]
    assert codes[:turnaround.RATE_LIMIT] == [200] * turnaround.RATE_LIMIT and codes[-1] == 429
