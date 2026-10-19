"""Image posts through the extended publish connectors (Design Studio pages).

Connector tests drive the real request assembly against a fake transport and
assert the platform contract; runner tests use in-memory SQLite, a fake R2 and
the real due-runner, so only the network and storage are faked.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.approvals import adapters as approval_adapters
from app.domains.publishing.extended import images as image_media
from app.domains.publishing.extended import posts as post_service
from app.domains.publishing.extended.connections import Credentials
from app.domains.publishing.extended.connectors import PublishContext, PublishError, get, get_for_images
from app.domains.publishing.extended.models import PlatformPost
from app.models.db.base import Base
from app.models.db.models import User

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


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
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "params": params or {},
                           "json": json, "data": data})
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self._responses.pop(0)


def _png(width=40, height=30, color=(10, 120, 200, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def pages(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"page{index}.png"
        path.write_bytes(_png(color=(index * 40, 90, 160, 255)))
        paths.append(str(path))
    return paths


def _ctx(platform, **kw):
    base = dict(platform=platform, access_token="tok", text="New drop #launch", title="Spring sale")
    base.update(kw)
    return PublishContext(**base)


# --------------------------------------------------------------------------- #
# Support matrix
# --------------------------------------------------------------------------- #
def test_image_support_matrix_and_clear_unsupported_reasons():
    for platform in ("instagram", "facebook", "threads", "pinterest", "x", "linkedin", "bluesky",
                     "telegram", "discord", "mastodon"):
        assert image_media.unsupported_reason(platform) == ""
        assert get_for_images(platform) is not None, platform
    assert "TikTok" in image_media.unsupported_reason("tiktok")
    assert "YouTube does not accept image posts" in image_media.unsupported_reason("youtube")
    assert "App Store Connect" in image_media.unsupported_reason("app_store")
    assert image_media.unsupported_reason("myspace").startswith("myspace does not support image posts")
    assert get_for_images("tiktok") is None and get_for_images("youtube") is None
    # Instagram images do not leak into the reel registry.
    assert get("instagram") is None


# --------------------------------------------------------------------------- #
# URL-ingest connectors
# --------------------------------------------------------------------------- #
def test_facebook_single_photo_and_multi_photo_feed_post():
    fb = get("facebook")
    tx = FakeTransport([_Resp(body={"id": "ph1", "post_id": "page_1"})])
    step = fb.publish(_ctx("facebook", target_id="page", target_token="ptok", image_urls=("https://r2/a.png",)),
                      transport=tx)
    assert step.done and step.external_id == "page_1" and step.url == "https://www.facebook.com/page_1"
    assert tx.calls[0]["url"].endswith("/page/photos")
    assert tx.calls[0]["data"]["url"] == "https://r2/a.png" and tx.calls[0]["data"]["message"] == "New drop #launch"

    tx = FakeTransport([_Resp(body={"id": "p1"}), _Resp(body={"id": "p2"}), _Resp(body={"id": "page_9"})])
    step = fb.publish(_ctx("facebook", target_id="page", target_token="ptok",
                           image_urls=("https://r2/a.png", "https://r2/b.png")), transport=tx)
    assert [c["data"]["published"] for c in tx.calls[:2]] == ["false", "false"]
    feed = tx.calls[2]
    assert feed["url"].endswith("/page/feed")
    assert json.loads(feed["data"]["attached_media[1]"]) == {"media_fbid": "p2"}
    assert step.done and step.external_id == "page_9"


def test_instagram_carousel_polls_then_publishes():
    ig = get_for_images("instagram")
    ctx = _ctx("instagram", external_account_id="ig1", image_urls=("https://r2/a.jpg", "https://r2/b.jpg"))
    tx = FakeTransport([_Resp(body={"id": "c1"}), _Resp(body={"id": "c2"}), _Resp(body={"id": "car"}),
                        _Resp(body={"status_code": "IN_PROGRESS"})])
    step = ig.publish(ctx, transport=tx)
    assert not step.done and step.progress["container_id"] == "car"
    assert tx.calls[0]["params"]["is_carousel_item"] == "true" and tx.calls[0]["params"]["image_url"] == "https://r2/a.jpg"
    assert tx.calls[2]["params"]["media_type"] == "CAROUSEL" and tx.calls[2]["params"]["children"] == "c1,c2"
    assert tx.calls[2]["params"]["caption"] == "New drop #launch"

    tx = FakeTransport([_Resp(body={"status_code": "FINISHED"}), _Resp(body={"id": "m1"}),
                        _Resp(body={"permalink": "https://instagram.com/p/x"})])
    done = ig.resume(_ctx("instagram", external_account_id="ig1", progress=step.progress), transport=tx)
    assert done.done and done.external_id == "m1" and done.url == "https://instagram.com/p/x"
    assert tx.calls[1]["url"].endswith("/ig1/media_publish") and tx.calls[1]["params"]["creation_id"] == "car"
    with pytest.raises(PublishError, match="native Instagram connector"):
        ig.publish(_ctx("instagram", external_account_id="ig1"), transport=FakeTransport([]))


def test_threads_single_image_container():
    th = get("threads")
    tx = FakeTransport([_Resp(body={"id": "c1"}), _Resp(body={"status": "FINISHED"}), _Resp(body={"id": "t1"}),
                        _Resp(body={"permalink": "https://threads.net/t1"})])
    step = th.publish(_ctx("threads", external_account_id="u1", image_urls=("https://r2/a.png",)), transport=tx)
    assert tx.calls[0]["params"]["media_type"] == "IMAGE" and tx.calls[0]["params"]["image_url"] == "https://r2/a.png"
    assert step.done and step.external_id == "t1" and step.url == "https://threads.net/t1"


def test_pinterest_carousel_pin_from_urls(monkeypatch):
    pin = get("pinterest")
    tx = FakeTransport([_Resp(body={"id": "pin9"})])
    step = pin.publish(_ctx("pinterest", target_id="board1", image_urls=("https://r2/a.png", "https://r2/b.png")),
                       transport=tx)
    body = tx.calls[0]["json"]
    assert body["media_source"] == {"source_type": "multiple_image_urls",
                                    "items": [{"url": "https://r2/a.png"}, {"url": "https://r2/b.png"}]}
    assert body["board_id"] == "board1" and step.done and step.url.endswith("/pin/pin9/")


# --------------------------------------------------------------------------- #
# Byte-upload connectors
# --------------------------------------------------------------------------- #
def test_x_uploads_each_image_then_posts_all_media_ids(pages):
    x = get("x")
    tx = FakeTransport([_Resp(body={"data": {"id": "m1"}}), _Resp(body={"data": {"id": "m2"}}),
                        _Resp(body={"data": {"id": "post1"}})])
    step = x.publish(_ctx("x", image_paths=tuple(pages[:2])), transport=tx)
    assert tx.calls[0]["url"].endswith("/2/media/upload")
    assert b"tweet_image" in tx.calls[0]["data"] and b"image/png" in tx.calls[0]["data"]
    assert tx.calls[2]["json"]["media"]["media_ids"] == ["m1", "m2"]
    assert step.done and step.external_id == "post1"
    with pytest.raises(PublishError, match="at most 4"):
        x.publish(_ctx("x", image_paths=tuple(pages * 2)), transport=FakeTransport([]))


def test_linkedin_multi_image_post(pages):
    li = get("linkedin")
    responses = []
    for index in range(2):
        responses += [_Resp(body={"value": {"uploadUrl": f"https://up/{index}", "image": f"urn:li:image:{index}"}}),
                      _Resp()]
    responses.append(_Resp(status_code=201, headers={"x-restli-id": "urn:li:share:1"}))
    tx = FakeTransport(responses)
    step = li.publish(_ctx("linkedin", external_account_id="abc", image_paths=tuple(pages[:2])), transport=tx)
    assert tx.calls[0]["json"] == {"initializeUploadRequest": {"owner": "urn:li:person:abc"}}
    assert tx.calls[1]["method"] == "PUT" and tx.calls[1]["data"].startswith(b"\x89PNG")
    content = tx.calls[4]["json"]["content"]
    assert content == {"multiImage": {"images": [{"id": "urn:li:image:0", "altText": "Spring sale"},
                                                 {"id": "urn:li:image:1", "altText": "Spring sale"}]}}
    assert step.done and step.url == "https://www.linkedin.com/feed/update/urn:li:share:1/"


def test_telegram_single_photo_and_album(pages):
    tg = get("telegram")
    tx = FakeTransport([_Resp(body={"ok": True, "result": {"message_id": 5}})])
    step = tg.publish(_ctx("telegram", target_id="@chan", image_paths=(pages[0],), meta={"username": "chan"}),
                      transport=tx)
    assert tx.calls[0]["url"].endswith("/sendPhoto") and b'name="photo"' in tx.calls[0]["data"]
    assert step.done and step.url == "https://t.me/chan/5"

    tx = FakeTransport([_Resp(body={"ok": True, "result": [{"message_id": 7}, {"message_id": 8}]})])
    step = tg.publish(_ctx("telegram", target_id="@chan", image_paths=tuple(pages)), transport=tx)
    data = tx.calls[0]["data"]
    assert tx.calls[0]["url"].endswith("/sendMediaGroup") and b"attach://page2" in data
    assert b'"caption": "New drop #launch"' in data and step.external_id == "@chan:7"
    with pytest.raises(PublishError, match="1024"):
        tg.publish(_ctx("telegram", target_id="@chan", text="x" * 1100, image_paths=(pages[0],)),
                   transport=FakeTransport([]))


def test_discord_attaches_every_page(pages):
    dc = get("discord")
    hook = "https://discord.com/api/webhooks/12345678/" + "a" * 40
    tx = FakeTransport([_Resp(body={"id": "msg1", "channel_id": "c1"})])
    step = dc.publish(_ctx("discord", access_token=hook, image_paths=tuple(pages), meta={"guild_id": "g1"}),
                      transport=tx)
    data = tx.calls[0]["data"]
    assert b'name="files[0]"' in data and b'name="files[2]"' in data and b'"parse": []' in data
    assert step.done and step.url == "https://discord.com/channels/g1/c1/msg1"


def test_mastodon_waits_for_processing_then_posts_all_media(pages):
    ms = get("mastodon")
    meta = {"instance_url": "https://mastodon.social", "post_id": "p1"}
    tx = FakeTransport([_Resp(body={"id": "a", "url": "https://m/a"}), _Resp(status_code=202, body={"id": "b"})])
    step = ms.publish(_ctx("mastodon", image_paths=tuple(pages[:2]), meta=meta), transport=tx)
    assert not step.done and step.progress == {"media_ids": ["a", "b"]}
    tx = FakeTransport([_Resp(body={"id": "a", "url": "u"}), _Resp(body={"id": "b", "url": "u"}),
                        _Resp(body={"id": "s1", "url": "https://mastodon.social/@me/s1"})])
    done = ms.resume(_ctx("mastodon", meta=meta, progress=step.progress), transport=tx)
    assert tx.calls[2]["json"]["media_ids"] == ["a", "b"] and tx.calls[2]["headers"]["Idempotency-Key"]
    assert done.done and done.external_id == "s1"


def test_bluesky_embeds_images(pages):
    bs = get("bluesky")
    tx = FakeTransport([_Resp(body={"accessJwt": "jwt", "did": "did:plc:1", "handle": "me.bsky.social"}),
                        _Resp(body={"blob": {"ref": "b1"}}), _Resp(body={"blob": {"ref": "b2"}}),
                        _Resp(body={"uri": "at://did:plc:1/app.bsky.feed.post/r1", "cid": "c"})])
    step = bs.publish(_ctx("bluesky", external_account_id="me.bsky.social", image_paths=tuple(pages[:2])),
                      transport=tx)
    assert tx.calls[1]["headers"]["Content-Type"] == "image/png"
    embed = tx.calls[3]["json"]["record"]["embed"]
    assert embed["$type"] == "app.bsky.embed.images" and [i["image"] for i in embed["images"]] == [
        {"ref": "b1"}, {"ref": "b2"}]
    assert step.done and step.url == "https://bsky.app/profile/me.bsky.social/post/r1"


# --------------------------------------------------------------------------- #
# Image bytes
# --------------------------------------------------------------------------- #
def test_to_jpeg_flattens_alpha_and_shrink_fits_the_limit():
    jpeg = image_media.to_jpeg(_png(color=(0, 0, 0, 0)))
    assert jpeg.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(jpeg)) as img:
        assert img.mode == "RGB" and img.getpixel((1, 1))[0] > 240  # transparent -> white
    noisy = Image.effect_noise((1400, 1400), 100).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, format="PNG")
    big = buf.getvalue()
    assert len(big) > 976_000
    small = image_media.shrink(big, 976_000)
    assert len(small) <= 976_000 and small.startswith(b"\xff\xd8\xff")
    assert image_media.shrink(b"tiny", 100) == b"tiny"
    assert image_media.jpeg_key("uploads/design-1.png") == "uploads/design-1.jpg"


class FakeR2:
    def __init__(self, blobs):
        self.blobs = dict(blobs)
        self.uploaded = {}

    def presign_get(self, key, expires=3600, download_name=None):
        return f"https://r2.example/{key}?sig=1"

    def download_file(self, key, local_path):
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as fh:
            fh.write(self.blobs[key])
        return local_path

    def upload_bytes(self, key, data, content_type="application/octet-stream"):
        self.uploaded[key] = (data, content_type)
        return key


def test_prepare_urls_for_ingest_and_files_for_upload():
    r2 = FakeR2({"k1.png": _png(), "k2.png": _png()})
    ingest = image_media.prepare("facebook", ["k1.png", "k2.png"], r2=r2)
    assert ingest.urls == ("https://r2.example/k1.png?sig=1", "https://r2.example/k2.png?sig=1")
    assert ingest.paths == ()
    upload = image_media.prepare("telegram", ["k1.png", "k2.png"], r2=r2)
    assert len(upload.paths) == 2 and all(os.path.exists(p) for p in upload.paths)
    upload.remove()
    assert not any(os.path.exists(p) for p in upload.paths)
    copies = image_media.jpeg_copies(["k1.png", "already.jpg"], r2=r2)
    assert copies == ["k1.jpg", "already.jpg"] and r2.uploaded["k1.jpg"][1] == "image/jpeg"


# --------------------------------------------------------------------------- #
# Due-runner
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    for module in (post_service, image_media, approval_adapters):
        monkeypatch.setattr(module, "get_session", _session)
    enqueued: list[str] = []
    monkeypatch.setattr(post_service, "_enqueue", lambda post_id: enqueued.append(post_id))
    monkeypatch.setattr(post_service, "_content_gate", lambda snap: "")
    with _session() as s:
        user = User(email="owner@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest(), credits=0)
        s.add(user)
        s.flush()
        uid = user.id
    return SimpleNamespace(session=_session, user=uid, enqueued=enqueued)


def _image_post(db, platform="telegram", keys=("d/p1.png", "d/p2.png"), status="scheduled", target="chan1"):
    with db.session() as s:
        row = PlatformPost(user_id=db.user, job_id="", platform=platform, status=status, scheduled_at=NOW,
                           next_attempt_at=NOW, text="New drop", title="Sale", hashtags=[], target_id=target,
                           progress={"image_keys": list(keys), "source": {"kind": "design", "design_id": "d1"}})
        s.add(row)
        s.flush()
        return row.id


def test_runner_posts_design_pages_and_removes_temp_files(db, monkeypatch):
    r2 = FakeR2({"d/p1.png": _png(), "d/p2.png": _png()})
    monkeypatch.setattr("app.platform.storage.r2.get_r2_client", lambda: r2)
    monkeypatch.setattr(post_service, "_credentials_for",
                        lambda snap, tx: Credentials(platform="telegram", access_token="1:tok", target_id="@chan",
                                                     meta={"username": "chan"}))
    seen = {}
    original = image_media.prepare

    def _spy(platform, keys, r2=None):
        prepared = original(platform, keys, r2=r2)
        seen["paths"] = prepared.paths
        return prepared

    monkeypatch.setattr(image_media, "prepare", _spy)
    post_id = _image_post(db)
    tx = FakeTransport([_Resp(body={"ok": True, "result": [{"message_id": 11}, {"message_id": 12}]})])
    out = post_service.run_post(post_id, transport=tx, now=NOW)
    assert out["status"] == "published"
    assert tx.calls[0]["url"].endswith("/sendMediaGroup")
    assert not any(os.path.exists(p) for p in seen["paths"])
    with db.session() as s:
        row = s.get(PlatformPost, post_id)
        record = post_service.post_record(row)
    assert record["media_kind"] == "image" and record["image_count"] == 2 and record["url"] == "https://t.me/chan/11"


def test_retry_and_held_approval_keep_the_pages(db):
    post_id = _image_post(db, status="failed")
    record = post_service.retry(db.user, post_id, now=NOW)
    assert record["status"] == "scheduled"
    with db.session() as s:
        assert s.get(PlatformPost, post_id).progress["image_keys"] == ["d/p1.png", "d/p2.png"]
    held = _image_post(db, platform="linkedin", status="held")
    approval_adapters._approve_publish(db.user, held, {})
    with db.session() as s:
        progress = s.get(PlatformPost, held).progress
    assert progress["image_keys"] == ["d/p1.png", "d/p2.png"] and "gate_override" in progress
