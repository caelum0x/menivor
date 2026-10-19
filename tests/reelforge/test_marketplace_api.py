"""Template Marketplace API tests.

Covers ``app.controllers.v1.marketplace`` — the auth-gated endpoints that publish
an immutable snapshot of a private template to a PUBLIC marketplace and let any
other authenticated user browse/search, view detail, clone and rate it:

* ``GET  /marketplace``            — auth (401), search/sort, and ``limit`` clamp
  (a huge ``limit`` never returns more than 100 rows / never 422s).
* ``GET  /marketplace/{id}``       — detail (404 for unknown/unpublished).
* ``POST /marketplace/publish``    — owner-scoped snapshot; a foreign ``template_id``
  is a 404; the listing is an IMMUTABLE COPY (editing the source preset after
  publish does not mutate the listing).
* ``POST /marketplace/{id}/clone`` — any authed user; bumps ``clone_count`` and
  creates a private preset for the caller.
* ``POST /marketplace/{id}/rate``  — 1..5 upsert (one row per user); out-of-range
  stars are a clean 400; the aggregate is recomputed.
* ``DELETE /marketplace/{id}``     — AUTHOR-ONLY unpublish (a non-author gets 404
  and the listing stays published).

No external I/O: Postgres is replaced by an in-memory SQLite DB behind a
``TestClient``, mirroring ``tests/reelforge/test_ideas_api.py``.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.controllers.v1.marketplace as mkt_mod
from app.models.db.base import Base
from app.models.db.models import MarketplaceTemplate, TemplateRating, User, UserPreset
from app.models.db.repositories import MarketplaceRepository, UserPresetRepository
from app.models.exception import HttpException
from app.utils import utils

_API_KEY = "mkt-key"
_KEY_HASH = hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest()
_HEADERS = {"x-api-key": _API_KEY}

_OTHER_KEY = "other-key"
_OTHER_HASH = hashlib.sha256(_OTHER_KEY.encode("utf-8")).hexdigest()
_OTHER_HEADERS = {"x-api-key": _OTHER_KEY}


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture()
def db_factory():
    """In-memory SQLite engine + session factory with the schema created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    return Factory


def _make_user(Factory, email="author@example.com", key_hash=_KEY_HASH) -> str:
    with Factory() as s:
        u = User(email=email, api_key_hash=key_hash, credits=0)
        s.add(u)
        s.flush()
        uid = u.id
        s.commit()
    return uid


def _make_preset(Factory, user_id: str, name="My kit", config=None) -> str:
    with Factory() as s:
        row = UserPresetRepository(s).create(
            user_id=user_id, name=name, config=config or {}
        )
        rid = row.id
        s.commit()
    return rid


def _publish(Factory, author_id: str, **kwargs) -> str:
    """Insert a published listing directly and return its id."""
    defaults = dict(
        author_user_id=author_id,
        title="A great template",
        description="does great things",
        prompt="Write about {subject}",
        params={"caption_style": "karaoke_yellow"},
        tags=["saas", "demo"],
        language="en",
        layout="split",
    )
    defaults.update(kwargs)
    with Factory() as s:
        row = MarketplaceRepository(s).publish(**defaults)
        tid = row.id
        s.commit()
    return tid


@pytest.fixture()
def mkt_client(monkeypatch, db_factory):
    """FastAPI TestClient wired to the marketplace router + in-memory SQLite.

    Returns ``(client, Factory)``. The rate limiter degrades OPEN without Redis,
    so it never interferes with these tests.
    """
    Factory = db_factory

    @contextmanager
    def _fake_get_session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(mkt_mod, "get_session", _fake_get_session)

    app = FastAPI()
    app.include_router(mkt_mod.router)

    def _http_handler(request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app), Factory


# =========================================================================== #
# GET /marketplace  (browse / search / clamp / auth)
# =========================================================================== #
def test_browse_requires_auth_401(mkt_client):
    client, _ = mkt_client
    resp = client.get("/api/v1/marketplace")  # no x-api-key
    assert resp.status_code == 401, resp.text


def test_browse_lists_published_only(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    _publish(Factory, author, title="Visible one")
    _publish(Factory, author, title="Hidden one", published=False)

    resp = client.get("/api/v1/marketplace", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    titles = {row["title"] for row in data}
    assert "Visible one" in titles
    assert "Hidden one" not in titles


def test_browse_search_by_text_and_tag(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    _publish(Factory, author, title="Budgeting app demo", tags=["finance"])
    _publish(Factory, author, title="Cooking reel", tags=["food"])

    by_text = client.get(
        "/api/v1/marketplace", params={"query": "budgeting"}, headers=_HEADERS
    )
    assert by_text.status_code == 200, by_text.text
    assert [r["title"] for r in by_text.json()["data"]] == ["Budgeting app demo"]

    by_tag = client.get(
        "/api/v1/marketplace", params={"tag": "food"}, headers=_HEADERS
    )
    assert by_tag.status_code == 200, by_tag.text
    assert [r["title"] for r in by_tag.json()["data"]] == ["Cooking reel"]


def test_browse_limit_is_clamped_not_422(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    for i in range(5):
        _publish(Factory, author, title=f"tpl {i}")

    # A pathological limit must clamp to <= 100 and still 200 (never 422 / scan).
    resp = client.get(
        "/api/v1/marketplace", params={"limit": 100000}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["data"]) <= 100


# =========================================================================== #
# GET /marketplace/{id}  (detail)
# =========================================================================== #
def test_detail_happy_path(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    tid = _publish(Factory, author, title="Detail me")

    resp = client.get(f"/api/v1/marketplace/{tid}", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] == tid
    assert data["title"] == "Detail me"
    assert data["tags"] == ["saas", "demo"]


def test_detail_unknown_404(mkt_client):
    client, Factory = mkt_client
    _make_user(Factory)
    resp = client.get("/api/v1/marketplace/does-not-exist", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# POST /marketplace/publish  (owner-scoped snapshot)
# =========================================================================== #
def test_publish_inline_happy_path(mkt_client):
    client, Factory = mkt_client
    _make_user(Factory)

    resp = client.post(
        "/api/v1/marketplace/publish",
        json={
            "title": "Inline listing",
            "description": "d",
            "prompt": "p {subject}",
            "params": {"target_duration_s": 20},
            "tags": ["Saas", "saas", "  demo "],
            "language": "EN",
            "layout": "split",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["title"] == "Inline listing"
    # Tags normalised (lowercased + de-duped); language lowercased.
    assert data["tags"] == ["saas", "demo"]
    assert data["language"] == "en"
    assert data["published"] is True


def test_publish_from_owned_preset_snapshots_immutably(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    pid = _make_preset(
        Factory,
        author,
        name="Kit A",
        config={"prompt": "orig prompt", "tags": ["one"], "language": "en"},
    )

    resp = client.post(
        "/api/v1/marketplace/publish",
        json={"template_id": pid},
        headers=_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    tid = resp.json()["data"]["id"]
    assert resp.json()["data"]["title"] == "Kit A"
    assert resp.json()["data"]["prompt"] == "orig prompt"

    # Mutating the SOURCE preset must NOT change the published snapshot.
    with Factory() as s:
        preset = s.get(UserPreset, pid)
        preset.config = {"prompt": "EDITED", "tags": ["changed"], "language": "tr"}
        s.commit()

    detail = client.get(f"/api/v1/marketplace/{tid}", headers=_HEADERS)
    assert detail.json()["data"]["prompt"] == "orig prompt"
    assert detail.json()["data"]["tags"] == ["one"]


def test_publish_foreign_preset_404(mkt_client):
    client, Factory = mkt_client
    other = _make_user(Factory, email="other@x.com", key_hash=_OTHER_HASH)
    victim_pid = _make_preset(Factory, other, name="Not yours")
    _make_user(Factory)  # the caller (default key)

    resp = client.post(
        "/api/v1/marketplace/publish",
        json={"template_id": victim_pid},
        headers=_HEADERS,
    )
    assert resp.status_code == 404, resp.text


def test_publish_requires_auth_401(mkt_client):
    client, _ = mkt_client
    resp = client.post("/api/v1/marketplace/publish", json={"title": "x"})
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# POST /marketplace/{id}/clone
# =========================================================================== #
def test_clone_creates_private_preset_and_bumps_count(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    cloner = _make_user(Factory, email="cloner@x.com", key_hash=_OTHER_HASH)
    tid = _publish(Factory, author, title="Cloneable")

    resp = client.post(f"/api/v1/marketplace/{tid}/clone", headers=_OTHER_HEADERS)
    assert resp.status_code == 200, resp.text
    preset_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["source_marketplace_id"] == tid

    with Factory() as s:
        preset = s.get(UserPreset, preset_id)
        assert preset is not None
        assert preset.user_id == cloner
        assert preset.config["source_marketplace_id"] == tid
        listing = s.get(MarketplaceTemplate, tid)
        assert listing.clone_count == 1


def test_clone_unknown_404(mkt_client):
    client, Factory = mkt_client
    _make_user(Factory)
    resp = client.post("/api/v1/marketplace/nope/clone", headers=_HEADERS)
    assert resp.status_code == 404, resp.text


# =========================================================================== #
# POST /marketplace/{id}/rate  (1..5 upsert)
# =========================================================================== #
def test_rate_happy_path_and_upsert(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    rater = _make_user(Factory, email="rater@x.com", key_hash=_OTHER_HASH)
    tid = _publish(Factory, author, title="Rate me")

    first = client.post(
        f"/api/v1/marketplace/{tid}/rate", json={"stars": 4}, headers=_OTHER_HEADERS
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["rating_count"] == 1
    assert first.json()["data"]["rating_avg"] == 4.0

    # Re-rating upserts (updates the same row) rather than adding a duplicate.
    second = client.post(
        f"/api/v1/marketplace/{tid}/rate", json={"stars": 2}, headers=_OTHER_HEADERS
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["rating_count"] == 1
    assert second.json()["data"]["rating_avg"] == 2.0

    with Factory() as s:
        rows = (
            s.query(TemplateRating)
            .filter(
                TemplateRating.template_id == tid,
                TemplateRating.user_id == rater,
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].stars == 2


@pytest.mark.parametrize("bad", [0, 6, -1, 99])
def test_rate_out_of_range_400(mkt_client, bad):
    client, Factory = mkt_client
    author = _make_user(Factory)
    tid = _publish(Factory, author)

    resp = client.post(
        f"/api/v1/marketplace/{tid}/rate", json={"stars": bad}, headers=_HEADERS
    )
    assert resp.status_code == 400, resp.text


def test_rate_unknown_404(mkt_client):
    client, Factory = mkt_client
    _make_user(Factory)
    resp = client.post(
        "/api/v1/marketplace/nope/rate", json={"stars": 5}, headers=_HEADERS
    )
    assert resp.status_code == 404, resp.text


def test_rate_requires_auth_401(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    tid = _publish(Factory, author)
    resp = client.post(f"/api/v1/marketplace/{tid}/rate", json={"stars": 5})
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# DELETE /marketplace/{id}  (author-only unpublish)
# =========================================================================== #
def test_author_can_unpublish(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    tid = _publish(Factory, author, title="Mine to hide")

    resp = client.delete(f"/api/v1/marketplace/{tid}", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["unpublished"] is True

    with Factory() as s:
        assert s.get(MarketplaceTemplate, tid).published is False


def test_non_author_cannot_unpublish_404(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    _make_user(Factory, email="stranger@x.com", key_hash=_OTHER_HASH)
    tid = _publish(Factory, author, title="Not yours to hide")

    # A stranger guessing the id must get 404 and the listing stays published.
    resp = client.delete(f"/api/v1/marketplace/{tid}", headers=_OTHER_HEADERS)
    assert resp.status_code == 404, resp.text
    with Factory() as s:
        assert s.get(MarketplaceTemplate, tid).published is True


def test_unpublish_requires_auth_401(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    tid = _publish(Factory, author)
    resp = client.delete(f"/api/v1/marketplace/{tid}")
    assert resp.status_code == 401, resp.text


# =========================================================================== #
# GET /marketplace?sort=proven  (win-score ranking + annotation)
# =========================================================================== #
def _set_rating(Factory, listing_id, rating_avg, rating_count=1):
    """Set a listing's denormalised rating aggregate directly (test setup)."""
    with Factory() as s:
        row = s.get(MarketplaceTemplate, listing_id)
        row.rating_avg = rating_avg
        row.rating_count = rating_count
        s.commit()


def _seed_reel_outcome(Factory, user_id, listing_id, metrics):
    """Clone a listing for ``user_id``, render a reel from it, and log its outcome."""
    from app.models.db.models import Job
    from app.services import hook_performance
    from app.services import marketplace as svc

    with Factory() as s:
        svc.clone_to_user(s, user_id, listing_id)
        job = Job(
            user_id=user_id,
            params={svc.SOURCE_MARKETPLACE_KEY: listing_id, "video_subject": "x"},
        )
        s.add(job)
        s.flush()
        hook_performance.log_performance(s, user_id, job.id, metrics)
        s.commit()


def test_browse_proven_ranks_and_annotates_win_score(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    creator = _make_user(Factory, email="creator@x.com", key_hash=_OTHER_HASH)
    # A second distinct cloner per listing so each clears the k-anonymity floor
    # (``WIN_SCORE_PUBLIC_MIN_COHORT``) and its numeric win_score is exposed.
    creator2 = _make_user(
        Factory,
        email="creator2@x.com",
        key_hash=hashlib.sha256(b"creator2-key").hexdigest(),
    )

    # Listing A: high rating but a WEAK reel; Listing B: low rating but a STRONG
    # reel. Under 'proven', B (proven, better reels) must rank ahead of A even
    # though A is rated higher.
    a = _publish(Factory, author, title="A high-rated")
    b = _publish(Factory, author, title="B strong-reels")
    _set_rating(Factory, a, 5.0)
    _set_rating(Factory, b, 1.0)

    for cloner in (creator, creator2):
        _seed_reel_outcome(
            Factory, cloner, a, {"views": 1000, "likes": 5, "retention_pct": 5.0}
        )
        _seed_reel_outcome(
            Factory,
            cloner,
            b,
            {"views": 1000, "likes": 700, "shares": 200, "retention_pct": 95.0},
        )

    resp = client.get(
        "/api/v1/marketplace", params={"sort": "proven"}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    order = [row["id"] for row in data]
    assert order.index(b) < order.index(a)  # stronger reels first, beats rating

    # Every proven listing is annotated with a numeric win_score; B's beats A's.
    by_id = {row["id"]: row for row in data}
    assert isinstance(by_id[a]["win_score"], (int, float))
    assert isinstance(by_id[b]["win_score"], (int, float))
    assert by_id[b]["win_score"] > by_id[a]["win_score"]


def test_browse_proven_hides_win_score_below_cohort_floor(mkt_client):
    """k-anonymity: a listing cloned by a SINGLE creator still ranks under
    'proven' but never exposes the numeric win_score derived from that one
    creator's private engagement/retention metrics."""
    client, Factory = mkt_client
    author = _make_user(Factory)
    creator = _make_user(Factory, email="solo@x.com", key_hash=_OTHER_HASH)

    proven = _publish(Factory, author, title="solo-proven")
    unproven = _publish(Factory, author, title="unproven")
    _set_rating(Factory, proven, 1.0)
    _set_rating(Factory, unproven, 4.9)

    # Exactly one cloner -> below WIN_SCORE_PUBLIC_MIN_COHORT.
    _seed_reel_outcome(
        Factory, creator, proven, {"views": 100, "likes": 60, "retention_pct": 80.0}
    )

    resp = client.get(
        "/api/v1/marketplace", params={"sort": "proven"}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    by_id = {row["id"]: row for row in data}

    # Still ranks ahead (ordering uses the unfloored score)...
    order = [row["id"] for row in data]
    assert order.index(proven) < order.index(unproven)
    # ...but the scalar is withheld (single-cloner cohort).
    assert by_id[proven]["win_score"] is None


def test_default_sort_leaves_win_score_null(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    _publish(Factory, author, title="plain")

    resp = client.get("/api/v1/marketplace", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    # The default (non-proven) browse never computes a win-score: it is null (the
    # controller attaches a score only on 'proven', keeping the default path cheap).
    for row in resp.json()["data"]:
        assert row["win_score"] is None


def test_browse_proven_still_works_with_no_performance_data(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    a = _publish(Factory, author, title="unproven a")
    b = _publish(Factory, author, title="unproven b")
    _set_rating(Factory, a, 4.0)
    _set_rating(Factory, b, 2.0)

    # No clones / reels anywhere: 'proven' must not error and falls back to rating.
    resp = client.get(
        "/api/v1/marketplace", params={"sort": "proven"}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    titles = [row["title"] for row in resp.json()["data"]]
    assert titles == ["unproven a", "unproven b"]  # rating_avg fallback order
    # Listings with no downstream reels carry no win_score (never a 0/NaN entry).
    for row in resp.json()["data"]:
        assert row["win_score"] is None


# =========================================================================== #
# Remix trees: GET /marketplace/{id}/lineage + sort=most_remixed
# =========================================================================== #
def _publish_child(Factory, author_id, parent_id, title):
    """Publish a listing whose ``parent_template_id`` is ``parent_id`` and bump
    the parent's ``remix_count`` (mirrors the forward publish-from-clone path)."""
    with Factory() as s:
        repo = MarketplaceRepository(s)
        row = repo.publish(
            author_user_id=author_id,
            title=title,
            description="",
            prompt="p",
            params={},
            tags=[],
            language="en",
            layout="",
            parent_template_id=parent_id,
        )
        cid = row.id
        repo.increment_remix(parent_id)
        s.commit()
    return cid


def test_listing_shape_includes_remix_fields(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    tid = _publish(Factory, author, title="Original")

    detail = client.get(f"/api/v1/marketplace/{tid}", headers=_HEADERS)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    # Original publish -> no parent, zero remixes.
    assert data["parent_template_id"] is None
    assert data["remix_count"] == 0


def test_lineage_ancestors_and_children(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    a = _publish(Factory, author, title="Root A")
    b = _publish_child(Factory, author, a, "Remix B")
    c = _publish_child(Factory, author, b, "Remix C")

    resp = client.get(f"/api/v1/marketplace/{b}/lineage", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # Ancestors: immediate parent (A) first, walking to the root.
    assert [row["id"] for row in data["ancestors"]] == [a]
    # Children: the direct published remix (C).
    assert [row["id"] for row in data["children"]] == [c]
    # Lineage rows carry the safe remix provenance fields.
    assert data["children"][0]["parent_template_id"] == b


def test_lineage_requires_auth_401(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    tid = _publish(Factory, author)
    resp = client.get(f"/api/v1/marketplace/{tid}/lineage")
    assert resp.status_code == 401, resp.text


def test_lineage_unknown_returns_empty(mkt_client):
    client, Factory = mkt_client
    _make_user(Factory)
    resp = client.get("/api/v1/marketplace/nope/lineage", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == {"ancestors": [], "children": []}


def test_browse_sort_most_remixed(mkt_client):
    client, Factory = mkt_client
    author = _make_user(Factory)
    hot = _publish(Factory, author, title="Hot original")
    cold = _publish(Factory, author, title="Cold original")
    # Give ``hot`` two remixes and ``cold`` none.
    _publish_child(Factory, author, hot, "r1")
    _publish_child(Factory, author, hot, "r2")

    resp = client.get(
        "/api/v1/marketplace", params={"sort": "most_remixed"}, headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    order = [row["id"] for row in resp.json()["data"]]
    # The most-remixed original ranks ahead of the un-remixed one.
    assert order.index(hot) < order.index(cold)
    by_id = {row["id"]: row for row in resp.json()["data"]}
    assert by_id[hot]["remix_count"] == 2
    assert by_id[cold]["remix_count"] == 0
