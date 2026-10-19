"""Wave Q verifier gaps (c) and (d).

(c) ``ott.title.published`` and the new-episode push fire when a title becomes
    watchable (published AND packaged), once per title: not at a publish click
    on an unpackaged title, exactly once when its packaging then finishes, at
    publish for an already packaged title, and never again after a free-to-paid
    re-packaging.
(d) Outgoing webhooks carry Standard Webhooks ``webhook-id`` /
    ``webhook-timestamp`` / ``webhook-signature`` (HMAC keyed by the raw secret
    bytes) next to the deprecated body-only ``X-Menivor-Signature``; the verify
    helper enforces a 5 minute window and still accepts the body-only header
    when the new headers are absent; a retry keeps the id and re-signs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

import app.domains.ott_live.models  # noqa: F401
from app.domains.ott import events, service as ott_service
from app.domains.ott.models import OttTitle
from app.domains.ott_viewers.models import OttViewerPush
from app.models.db.models import AuditLog, WebhookDelivery, Workspace, WorkspaceMember
from app.services import push, webhook_subscriptions, webhooks
from app.services.ott_transcode import keys, service as transcode
from app.services.ott_transcode.models import OttEncodeJob

from tests.reelforge import _wp_p3_ott as h

HOOK_URL = "https://93.184.216.34/hook"
TOKEN = "ExponentPushToken[cccccccccccccccccccc]"


class _Response:
    def __init__(self, code: int) -> None:
        self.status_code = code


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "test-webhook-signing-key")
    monkeypatch.setenv(keys.SECRET_ENV, "k" * 32)
    import app.models.db.base as db_base

    monkeypatch.setattr(db_base, "get_session", h.session_cm(factory))
    monkeypatch.setattr("app.services.ott_transcode.router.enqueue_box1", lambda job_id: None)

    class _Task:  # the worker path runs in-process
        @staticmethod
        def delay(*args):
            events.emit_now(*args, session=None)

    monkeypatch.setattr(events, "emit_task", _Task)
    posted: list[dict] = []
    monkeypatch.setattr(webhooks, "_validate_and_resolve", lambda url: (None, "93.184.216.34"))
    monkeypatch.setattr(webhooks, "_post", lambda url, *, data, headers, timeout, pinned_ip: (
        posted.append({"body": data, "headers": dict(headers)}) or _Response(200)))
    batches: list[list[dict]] = []
    monkeypatch.setattr(push, "_post_batch", lambda messages: batches.append(messages) or [
        {"status": "ok"} for _ in messages])

    owner = h.owner(factory)
    cid, _ids = h.channel(factory, owner, "maya", titles=0)
    with factory() as s:
        ws = Workspace(owner_id=owner, name="Studio")
        s.add(ws)
        s.flush()
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=owner, role="owner"))
        _sub, secret = webhook_subscriptions.create(s, ws.id, HOOK_URL, [events.TITLE_PUBLISHED])
        s.add(OttViewerPush(viewer_id="v1", channel_id=cid, token=TOKEN, platform="ios", topics=["episodes"]))
        s.commit()
    return {"factory": factory, "owner": owner, "cid": cid, "posted": posted, "batches": batches, "secret": secret}


def _draft(env, *, package_status: str = "none", tier: str = "free") -> str:
    with env["factory"]() as s:
        title = OttTitle(channel_id=env["cid"], title="Episode one", kind="episode", genres=[], geo_countries=[],
                         status="draft", package_status=package_status, duration_s=60, access_tier=tier,
                         source_key="r2:src/ep1.mp4",
                         manifest_key="ott/x/master.m3u8" if package_status == "ready" else "")
        s.add(title)
        s.commit()
        return title.id


def _publish(env, title_id: str) -> None:
    with env["factory"]() as s:
        ott_service.publish_title(s, env["owner"], title_id)
        s.commit()


def _submit(env, title_id: str) -> str:
    with env["factory"]() as s:
        job = transcode.submit(s, s.get(OttTitle, title_id), source_key="r2:src/ep1.mp4", seconds=60,
                               short_side=720, user_id=env["owner"])
        s.commit()
        return job.id


def _finish(env, job_id: str) -> None:
    with env["factory"]() as s:
        transcode.finish(s, s.get(OttEncodeJob, job_id), cpu_seconds=1.0, packager_sha256="x" * 64)
        s.commit()


def _announced(env) -> list[dict]:
    return [json.loads(p["body"]) for p in env["posted"]
            if json.loads(p["body"]).get("event_type") == events.TITLE_PUBLISHED]


# --------------------------------------------------------------------------- #
# (c) ott.title.published only when watchable, once
# --------------------------------------------------------------------------- #
def test_publish_before_packaging_waits_for_the_packaging_finish(env):
    title_id = _draft(env)
    job_id = _submit(env, title_id)
    _publish(env, title_id)
    assert env["posted"] == [] and env["batches"] == []
    with env["factory"]() as s:
        assert s.execute(select(func.count(WebhookDelivery.id))).scalar_one() == 0
        assert s.get(OttTitle, title_id).status == "published"

    _finish(env, job_id)
    (event,) = _announced(env)
    assert event["title_id"] == title_id and event["event_id"].startswith(f"{events.TITLE_PUBLISHED}:{title_id}:")
    assert [[m["to"] for m in b] for b in env["batches"]] == [[TOKEN]]
    assert env["batches"][0][0]["data"]["title_id"] == title_id
    with env["factory"]() as s:
        marks = s.execute(select(AuditLog).where(AuditLog.action == events.ANNOUNCED_ACTION)).scalars().all()
        assert [(m.target_id, m.meta["event_id"]) for m in marks] == [(title_id, event["event_id"])]

    # Finishing the same job again, or hiding and publishing again, sends nothing.
    _finish(env, job_id)
    with env["factory"]() as s:
        ott_service.unpublish_title(s, env["owner"], title_id)
        s.commit()
    _publish(env, title_id)
    assert len(_announced(env)) == 1 and len(env["batches"]) == 1


def test_publish_after_packaging_announces_at_publish(env):
    title_id = _draft(env, package_status="ready")
    _publish(env, title_id)
    (event,) = _announced(env)
    assert event["title_id"] == title_id
    assert len(env["batches"]) == 1


def test_packaging_without_publish_announces_nothing(env):
    title_id = _draft(env)
    _finish(env, _submit(env, title_id))
    assert env["posted"] == [] and env["batches"] == []
    _publish(env, title_id)  # packaged first, published now: announced at publish
    assert len(_announced(env)) == 1 and len(env["batches"]) == 1


def test_free_to_paid_repackaging_does_not_announce_again(env):
    title_id = _draft(env)
    _finish(env, _submit(env, title_id))
    _publish(env, title_id)
    assert len(_announced(env)) == 1 and len(env["batches"]) == 1

    with env["factory"]() as s:
        ott_service.update_title(s, env["owner"], title_id, {"access_tier": "paid"})
        s.commit()
    with env["factory"]() as s:
        assert s.get(OttTitle, title_id).package_status == "queued"
        jobs = s.execute(select(OttEncodeJob).where(OttEncodeJob.title_id == title_id)).scalars().all()
        assert len(jobs) == 2
        (newest,) = [j.id for j in jobs if j.status != "done"]
    _finish(env, newest)
    with env["factory"]() as s:
        assert s.get(OttTitle, title_id).package_status == "ready"
    assert len(_announced(env)) == 1 and len(env["batches"]) == 1


def test_a_title_announced_before_the_gate_is_not_announced_again_after_a_tier_change(env):
    """A title live before this change has no announcement record: the tier change records it first."""
    with env["factory"]() as s:
        title = OttTitle(channel_id=env["cid"], title="Old episode", kind="episode", genres=[], geo_countries=[],
                         status="published", package_status="ready", duration_s=60, access_tier="free",
                         source_key="r2:src/old.mp4", manifest_key="ott/x/master.m3u8",
                         published_at=datetime.now(timezone.utc) - timedelta(days=3))
        s.add(title)
        s.commit()
        title_id = title.id
    with env["factory"]() as s:
        ott_service.update_title(s, env["owner"], title_id, {"access_tier": "paid"})
        s.commit()
    with env["factory"]() as s:
        newest = s.execute(select(OttEncodeJob.id).where(OttEncodeJob.title_id == title_id)).scalar_one()
    _finish(env, newest)
    assert env["posted"] == [] and env["batches"] == []


# --------------------------------------------------------------------------- #
# (d) Standard Webhooks signature
# --------------------------------------------------------------------------- #
SECRET = "c2lnbmluZy1zZWNyZXQtZm9yLXRlc3Rz"  # base64-looking on purpose: it is used as raw bytes, never decoded


def _deliver(monkeypatch, statuses, payload, *, clock):
    sent: list[dict] = []
    answers = list(statuses)
    monkeypatch.setattr(webhooks, "_validate_and_resolve", lambda url: (None, "93.184.216.34"))
    monkeypatch.setattr(webhooks, "RETRY_BACKOFF_S", 0.0)
    monkeypatch.setattr(webhooks, "_unix_now", lambda: clock.pop(0) if len(clock) > 1 else clock[0])

    def _post(url, *, data, headers, timeout, pinned_ip):
        sent.append({"body": data, "headers": dict(headers)})
        return _Response(answers.pop(0) if answers else 200)

    monkeypatch.setattr(webhooks, "_post", _post)
    result = webhooks.deliver_webhook(HOOK_URL, payload, secret=SECRET)
    return result, sent


def test_signature_headers_are_present_and_verify(monkeypatch):
    result, sent = _deliver(monkeypatch, [200], {"event_id": "evt_1", "event_type": "job.completed"},
                            clock=[1_700_000_000])
    assert result["delivered"] is True
    (post,) = sent
    hd, body = post["headers"], post["body"]
    assert hd["webhook-id"] == "evt_1" and hd["webhook-timestamp"] == "1700000000"
    expected = base64.b64encode(hmac.new(SECRET.encode(), b"evt_1.1700000000." + body, hashlib.sha256).digest())
    assert hd["webhook-signature"] == "v1," + expected.decode()
    legacy = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert hd["X-Menivor-Signature"] == legacy == hd["X-ReelForge-Signature"]
    assert webhooks.verify_signature(SECRET, hd, body, now=1_700_000_100) == "v1"
    # Header names are case-insensitive for receivers behind proxies.
    assert webhooks.verify_signature(SECRET, {k.upper(): v for k, v in hd.items()}, body,
                                     now=1_700_000_000) == "v1"


def test_tampered_body_timestamp_or_id_is_rejected(monkeypatch):
    _result, sent = _deliver(monkeypatch, [200], {"event_id": "evt_2"}, clock=[1_700_000_000])
    hd, body = sent[0]["headers"], sent[0]["body"]
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, hd, body + b" ", now=1_700_000_000)
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, {**hd, "webhook-timestamp": "1700000001"}, body, now=1_700_000_000)
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, {**hd, "webhook-id": "evt_3"}, body, now=1_700_000_000)
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature("another-secret", hd, body, now=1_700_000_000)
    # With the new headers present, a valid body-only signature cannot stand in for a broken v1 one.
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, {**hd, "webhook-signature": "v1,AAAA"}, body, now=1_700_000_000)
    partial = {k: v for k, v in hd.items() if k != "webhook-signature"}
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, partial, body, now=1_700_000_000)


def test_stale_and_future_timestamps_are_rejected(monkeypatch):
    _result, sent = _deliver(monkeypatch, [200], {"event_id": "evt_4"}, clock=[1_700_000_000])
    hd, body = sent[0]["headers"], sent[0]["body"]
    assert webhooks.verify_signature(SECRET, hd, body, now=1_700_000_300) == "v1"
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, hd, body, now=1_700_000_301)
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, hd, body, now=1_699_999_699)


def test_legacy_body_only_signature_still_verifies():
    body = json.dumps({"event_id": "evt_5"}).encode()
    legacy = webhooks.compute_signature(body, SECRET)
    assert webhooks.verify_signature(SECRET, {"X-Menivor-Signature": legacy}, body) == "legacy"
    assert webhooks.verify_signature(SECRET, {"x-reelforge-signature": legacy}, body) == "legacy"
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, {"X-Menivor-Signature": legacy}, body + b"x")
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify_signature(SECRET, {}, body)


def test_in_call_retry_keeps_the_id_and_re_signs(monkeypatch):
    result, sent = _deliver(monkeypatch, [503, 200], {"event_id": "evt_6"},
                            clock=[1_700_000_000, 1_700_000_007])
    assert result["delivered"] is True and len(sent) == 2
    first, second = sent[0]["headers"], sent[1]["headers"]
    assert first["webhook-id"] == second["webhook-id"] == "evt_6"
    assert (first["webhook-timestamp"], second["webhook-timestamp"]) == ("1700000000", "1700000007")
    assert first["webhook-signature"] != second["webhook-signature"]
    assert webhooks.verify_signature(SECRET, second, sent[1]["body"], now=1_700_000_007) == "v1"


def test_a_payload_without_event_id_gets_one_id_for_all_its_attempts(monkeypatch):
    _result, sent = _deliver(monkeypatch, [500, 500, 200], {"job_id": "j1"}, clock=[1_700_000_000])
    ids = {p["headers"]["webhook-id"] for p in sent}
    assert len(sent) == 3 and len(ids) == 1 and next(iter(ids)).startswith("msg_")
    assert webhooks.message_id({"event_id": "bad id\r\nx"}) == webhooks.message_id({"event_id": "bad id\r\nx"})
    assert webhooks.message_id({"event_id": "bad id\r\nx"}).startswith("msg_")


def test_outbox_retry_keeps_the_webhook_id_with_a_fresh_timestamp(env, monkeypatch):
    statuses = [409]

    def _post(url, *, data, headers, timeout, pinned_ip):
        env["posted"].append({"body": data, "headers": dict(headers)})
        return _Response(statuses.pop(0) if statuses else 200)

    monkeypatch.setattr(webhooks, "_post", _post)
    clock = [1_700_000_000]
    monkeypatch.setattr(webhooks, "_unix_now", lambda: clock[0])
    _publish(env, _draft(env, package_status="ready"))
    assert len(env["posted"]) == 1
    clock[0] = 1_700_007_200
    with env["factory"]() as s:
        retried = webhook_subscriptions.retry_pending(s, now=datetime.now(timezone.utc) + timedelta(hours=2))
        assert [r.status for r in retried] == [webhook_subscriptions.DELIVERY_DELIVERED]
        s.commit()
    first, second = env["posted"]
    event_id = json.loads(first["body"])["event_id"]
    assert first["headers"]["webhook-id"] == second["headers"]["webhook-id"] == event_id
    assert first["headers"]["webhook-timestamp"] == "1700000000"
    assert second["headers"]["webhook-timestamp"] == "1700007200"
    assert second["body"] == first["body"]
    for post, moment in ((first, 1_700_000_000), (second, 1_700_007_200)):
        assert webhooks.verify_signature(env["secret"], post["headers"], post["body"], now=moment) == "v1"
