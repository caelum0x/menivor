"""Approvals feed (M-4): adapters, idempotent decisions and the HTTP contract Rally reads.

Runs the real approvals service, social autopilot and extended-publishing
repository on in-memory SQLite. Only the platform reply call and the Celery
enqueue are faked; the test asserts that rejecting a reply draft never calls
the platform.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.ads.allocation_models import AdAllocationProposal
from app.domains.approvals import adapters, router as approvals_router, service
from app.domains.approvals.models import ApprovalItem
from app.domains.design import models as _design_models  # noqa: F401 - registers design_docs
from app.domains.publishing.extended import posts as ext_posts
from app.domains.publishing.extended.models import PlatformPost
from app.domains.social_inbox import autopilot, replies, sync
from app.domains.social_inbox.engagement_models import EngagementAction
from app.models.db.base import Base
from app.models.db.models import User

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


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

    for module in (service, adapters, sync, replies, autopilot, ext_posts):
        monkeypatch.setattr(module, "get_session", _session)
    monkeypatch.setattr(sync, "oauth_connect", object(), raising=False)
    sent: list[tuple[str, str, str]] = []

    def _fake_send(user_id, thread_id, text):
        sent.append((user_id, thread_id, text))
        return SimpleNamespace(reply_external_id="ext-1")

    monkeypatch.setattr(autopilot, "send_reply", _fake_send)
    enqueued: list[str] = []
    monkeypatch.setattr(ext_posts, "_enqueue", lambda post_id: enqueued.append(post_id))
    # Approving a publishing source follows the launch gate; these tests run it open.
    monkeypatch.setattr(service, "_publishing_open", lambda: True)
    return SimpleNamespace(Factory=Factory, session=_session, sent=sent, enqueued=enqueued)


def _seed(db) -> dict:
    with db.session() as s:
        user = User(email="owner@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest(), credits=0)
        other = User(email="other@example.com", api_key_hash=hashlib.sha256(b"o").hexdigest(), credits=0)
        s.add_all([user, other])
        s.flush()
        draft = EngagementAction(user_id=user.id, thread_id="thread1", platform="instagram", kind="reply",
                                 status="pending_approval", text="Thanks a lot!", excerpt="Love it",
                                 author_name="Ana", detail={})
        held = PlatformPost(user_id=user.id, job_id="job1", platform="linkedin", status="held",
                            scheduled_at=NOW, title="Launch", text="We launched", hashtags=[],
                            error="Held for review before posting (needs_edit): claim check", progress={})
        proposal = AdAllocationProposal(user_id=user.id, run_date=date(2026, 9, 25), total_daily_budget_micros=50_000_000,
                                        network_stats={}, current_split={"meta": 0.5, "tiktok": 0.5},
                                        proposed_split={"meta": 0.7, "tiktok": 0.3}, max_delta=0.2, reason="Meta cheaper")
        s.add_all([draft, held, proposal])
        s.flush()
        return {"user": user.id, "other": other.id, "draft": draft.id, "post": held.id, "proposal": proposal.id}


def _item(listing: dict, source: str) -> dict:
    return next(i for i in listing["items"] if i["source"] == source)


def test_list_syncs_all_sources_and_is_idempotent(db):
    ids = _seed(db)
    first = service.list_items(ids["user"])
    second = service.list_items(ids["user"])
    assert first["total"] == second["total"] == 3
    assert first["pending_by_source"] == {"social_reply": 1, "publish_hold": 1, "ad_budget": 1}
    assert {i["id"] for i in first["items"]} == {i["id"] for i in second["items"]}
    budget = _item(first, "ad_budget")
    assert budget["risk"] == "high" and "meta 70%" in budget["summary"]
    assert budget["open_url"].endswith("/ads")
    # Scoped to the owner.
    assert service.list_items(ids["other"])["total"] == 0
    with db.session() as s:
        assert s.get(AdAllocationProposal, ids["proposal"]).approval_item_id == budget["id"]


def test_rejecting_a_reply_draft_never_posts_and_is_idempotent(db):
    ids = _seed(db)
    item = _item(service.list_items(ids["user"]), "social_reply")
    out = service.decide(ids["user"], item["id"], "reject", via="rally")
    assert out["item"]["status"] == "rejected" and out["idempotent"] is False
    assert db.sent == []
    with db.session() as s:
        assert s.get(EngagementAction, ids["draft"]).status == "rejected"
    again = service.decide(ids["user"], item["id"], "reject")
    assert again["idempotent"] is True and again["item"]["status"] == "rejected"
    with pytest.raises(service.ApprovalError) as exc:
        service.decide(ids["user"], item["id"], "approve")
    assert exc.value.status_code == 409
    assert db.sent == []


def test_approving_a_reply_draft_sends_the_edited_text_once(db):
    ids = _seed(db)
    item = _item(service.list_items(ids["user"]), "social_reply")
    out = service.decide(ids["user"], item["id"], "approve", edits={"text": "Thank you, Ana!", "evil": "x"})
    assert out["item"]["status"] == "executed"
    assert out["item"]["edited_payload"] == {"text": "Thank you, Ana!"}
    assert db.sent == [(ids["user"], "thread1", "Thank you, Ana!")]
    service.decide(ids["user"], item["id"], "approve")
    assert len(db.sent) == 1


def test_held_post_approve_requeues_with_gate_override_and_reject_cancels(db):
    ids = _seed(db)
    item = _item(service.list_items(ids["user"]), "publish_hold")
    service.decide(ids["user"], item["id"], "approve")
    assert db.enqueued == [ids["post"]]
    with db.session() as s:
        post = s.get(PlatformPost, ids["post"])
        assert post.status == "scheduled" and post.progress.get("gate_override")
        post.status = "held"  # the gate held it again later
    item2 = _item(service.list_items(ids["user"]), "publish_hold")
    assert item2["id"] == item["id"]
    # A fresh hold of the same post re-opens the same item for a new decision.
    assert item2["status"] == "pending"
    service.decide(ids["user"], item2["id"], "reject")
    with db.session() as s:
        assert s.get(PlatformPost, ids["post"]).status == "canceled"


def test_budget_decisions_update_the_proposal_only(db):
    ids = _seed(db)
    item = _item(service.list_items(ids["user"]), "ad_budget")
    out = service.decide(ids["user"], item["id"], "approve")
    assert out["item"]["result"]["action"] == "budget_approved"
    with db.session() as s:
        assert s.get(AdAllocationProposal, ids["proposal"]).status == "approved"


def test_items_handled_elsewhere_expire_and_foreign_ids_404(db):
    ids = _seed(db)
    item = _item(service.list_items(ids["user"]), "social_reply")
    with db.session() as s:
        s.get(EngagementAction, ids["draft"]).status = "done"
    listing = service.list_items(ids["user"], status="all")
    assert _item(listing, "social_reply")["status"] == "expired"
    with pytest.raises(service.ApprovalError) as exc:
        service.decide(ids["other"], item["id"], "approve")
    assert exc.value.status_code == 404


def test_source_gone_at_decision_time_marks_item_expired(db):
    ids = _seed(db)
    item = _item(service.list_items(ids["user"]), "ad_budget")
    with db.session() as s:
        s.get(AdAllocationProposal, ids["proposal"]).status = "superseded"
    with pytest.raises(service.ApprovalError) as exc:
        service.decide(ids["user"], item["id"], "approve")
    assert exc.value.status_code == 409
    assert service.get_item(ids["user"], item["id"])["status"] == "expired"


def test_producer_enqueue_is_idempotent_and_approve_acts_on_the_source(db, monkeypatch):
    from app.domains.approvals import producers

    monkeypatch.setattr(producers, "get_session", db.session)
    ids = _seed(db)
    a = service.enqueue(ids["user"], "design_publish", "doc1", title="Post design", payload={"x": 1})
    b = service.enqueue(ids["user"], "design_publish", "doc1", title="Post design v2")
    assert a["id"] == b["id"] and b["title"] == "Post design v2"
    # The design behind the item no longer exists: the approval expires instead of recording a no-op.
    with pytest.raises(service.ApprovalError) as exc:
        service.decide(ids["user"], a["id"], "approve")
    assert exc.value.status_code == 404 and exc.value.item["status"] == "expired"
    with pytest.raises(service.ApprovalError):
        service.enqueue(ids["user"], "nope", "x", title="t")


def test_expired_by_deadline(db):
    ids = _seed(db)
    service.enqueue(ids["user"], "catalog_import", "imp1", title="Import", expires_at=NOW - timedelta(days=30))
    listing = service.list_items(ids["user"], source="catalog_import", status="all")
    assert listing["items"][0]["status"] == "expired"


def test_http_contract_matches_rally_parser(db, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    ids = _seed(db)
    monkeypatch.setattr(approvals_router, "get_session", db.session)
    monkeypatch.setattr(approvals_router, "require_database", lambda _rid: None)
    monkeypatch.setattr(approvals_router, "resolve_principal",
                        lambda request, session, rid: SimpleNamespace(id=ids["user"]))
    monkeypatch.setattr(approvals_router, "enforce_rate_limit", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(approvals_router.router)
    client = TestClient(app)

    body = client.get("/api/v1/approvals?status=pending", headers={"x-api-key": "k"}).json()
    items = body["data"]["items"]
    assert len(items) == 3
    for it in items:
        assert {"id", "source", "title", "summary", "risk", "payload", "status", "created_at", "expires_at",
                "open_url"} <= set(it)
        assert it["status"] == "pending"
    target = next(i for i in items if i["source"] == "social_reply")
    res = client.post(f"/api/v1/approvals/{target['id']}/reject", json={"via": "rally"})
    assert res.status_code == 200 and res.json()["data"]["item"]["decided_via"] == "rally"
    res = client.post(f"/api/v1/approvals/{target['id']}/reject")
    assert res.status_code == 200 and res.json()["data"]["idempotent"] is True
    assert client.get("/api/v1/approvals/count").json()["data"]["pending_count"] == 2
    with db.session() as s:
        assert s.query(ApprovalItem).count() == 3


def test_publishing_approvals_are_refused_while_publishing_is_closed(db, monkeypatch):
    """A held post cannot be re-queued in the private beta; rejecting still works."""
    monkeypatch.setattr(service, "_publishing_open", lambda: False)
    with db.session() as s:
        user = User(email="gate@example.com", api_key_hash=hashlib.sha256(b"g").hexdigest(), credits=0)
        s.add(user)
        s.flush()
        uid = user.id
        item = ApprovalItem(user_id=uid, source="publish_hold", external_ref="post-1", title="Held post",
                            summary="", risk="medium", payload={}, status="pending")
        s.add(item)
        s.flush()
        item_id = item.id
    with pytest.raises(service.ApprovalError) as exc:
        service.decide(uid, item_id, service.APPROVE)
    assert exc.value.status_code == 403
    assert "private beta" in str(exc.value)
    assert service.get_item(uid, item_id)["status"] == "pending"
