"""Public Watermarked Share Pages — service + repository unit tests.

Runs entirely against an in-memory SQLite engine (no Postgres/Neon required),
mirroring ``test_hook_performance.py`` / ``test_marketplace.py``. Anchors the hard
security + behavior requirements of the feature:

* **Strictly per-user creation** — a creator can only share THEIR OWN job; sharing
  another user's job raises ``PermissionError`` and writes nothing.
* **Unguessable + unique token** — the token carries >=128 bits of entropy and is
  unique per link.
* **Safe public surface** — ``public_view`` returns ONLY the safe field set and
  NEVER the clean ``result_key``, the owning ``user_id``, or any financials.
* **Revoked == gone** — a revoked link resolves to nothing on the public read path.
* **View counting** — each public view increments ``view_count``.
* **One active link per job** — re-sharing a job returns the same live link.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import Job, ShareLink, User
from app.models.db.repositories import ShareLinkRepository
from app.services import share as svc


# =========================================================================== #
# Fixtures / helpers
# =========================================================================== #
@pytest.fixture()
def session() -> Session:
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
    with Factory() as s:
        yield s


def _user(session: Session, email: str) -> str:
    u = User(email=email, credits=0)
    session.add(u)
    session.flush()
    return u.id


def _job(
    session: Session,
    user_id: str,
    *,
    title: str = "My viral reel",
    result_key: str = "results/clean-master.mp4",
    preview_key: str = "previews/wm-preview.mp4",
    poster_key: str = "posters/frame.jpg",
) -> Job:
    job = Job(
        user_id=user_id,
        kind="avatar_reel",
        state=1,
        params={"title": title, "cost_usd": 4.20},
        stages={},
        result_key=result_key,
        preview_key=preview_key,
        poster_key=poster_key,
    )
    session.add(job)
    session.flush()
    return job


def _fake_presign(key: str) -> str:
    """Hermetic presign seam — no boto3/network; echoes the key it was given."""
    return f"https://cdn.example/signed/{key}?sig=deadbeef"


# =========================================================================== #
# Creation — strictly per-user (ownership)
# =========================================================================== #
def test_create_share_is_owner_scoped(session: Session):
    owner = _user(session, "owner@example.com")
    other = _user(session, "intruder@example.com")
    job = _job(session, owner)

    # Owner can share their own job.
    link = svc.create_share(session, owner, job.id)
    assert link.job_id == job.id
    assert link.user_id == owner
    assert link.revoked is False

    # A different user cannot share the owner's job — and nothing is written.
    with pytest.raises(PermissionError):
        svc.create_share(session, other, job.id)

    all_links = session.query(ShareLink).all()
    assert len(all_links) == 1


def test_create_share_validates_inputs(session: Session):
    owner = _user(session, "owner@example.com")
    _job(session, owner)

    with pytest.raises(ValueError):
        svc.create_share(session, "", "job")
    with pytest.raises(ValueError):
        svc.create_share(session, owner, "")
    # Missing job -> ValueError (not PermissionError).
    with pytest.raises(ValueError):
        svc.create_share(session, owner, "does-not-exist")


# =========================================================================== #
# Token — unguessable + unique
# =========================================================================== #
def test_token_is_unguessable_and_unique(session: Session):
    owner = _user(session, "owner@example.com")
    tokens: set[str] = set()
    for i in range(10):
        job = _job(session, owner, title=f"reel {i}")
        link = svc.create_share(session, owner, job.id)
        # secrets.token_urlsafe(16) == 16 bytes == 128 bits of entropy.
        assert len(link.token) >= 22
        tokens.add(link.token)
    assert len(tokens) == 10  # all distinct


# =========================================================================== #
# Public view — SAFE surface only
# =========================================================================== #
def test_public_view_returns_only_safe_fields(session: Session):
    owner = _user(session, "owner@example.com")
    job = _job(
        session,
        owner,
        title="Stop scrolling",
        result_key="results/CLEAN-DO-NOT-LEAK.mp4",
    )
    link = svc.create_share(session, owner, job.id)

    dto = svc.public_view(session, link.token, presign=_fake_presign)

    # EXACT safe field set — nothing more, nothing less.
    assert set(dto.keys()) == set(svc.SAFE_PUBLIC_FIELDS)
    assert dto["title"] == "Stop scrolling"
    assert dto["watermarked_preview_url"].startswith("https://cdn.example/signed/")

    # The preview is built from the WATERMARKED preview key, never the clean master.
    assert "previews/wm-preview.mp4" in dto["watermarked_preview_url"]
    assert "CLEAN-DO-NOT-LEAK" not in dto["watermarked_preview_url"]

    # Hard security assertions: no clean result key, no owner id, no financials
    # anywhere in the serialized DTO.
    serialized = repr(dto)
    assert job.result_key not in serialized
    assert "result_key" not in dto
    assert owner not in serialized
    assert "user_id" not in dto
    for banned in ("cost_usd", "cost", "credits", "revenue", "4.20"):
        assert banned not in serialized


def test_public_view_falls_back_to_poster_then_cover(session: Session):
    owner = _user(session, "owner@example.com")
    # No preview_key -> falls back to poster_key (still safe, never result_key).
    job = _job(session, owner, preview_key="", poster_key="posters/thumb.jpg")
    link = svc.create_share(session, owner, job.id)

    dto = svc.public_view(session, link.token, presign=_fake_presign)
    assert "posters/thumb.jpg" in dto["watermarked_preview_url"]
    assert job.result_key not in dto["watermarked_preview_url"]


# =========================================================================== #
# Revoked link -> not found
# =========================================================================== #
def test_revoked_link_is_not_found(session: Session):
    owner = _user(session, "owner@example.com")
    job = _job(session, owner)
    link = svc.create_share(session, owner, job.id)
    token = link.token

    # Live link resolves.
    assert ShareLinkRepository(session).get_by_token(token) is not None

    # Revoke it (owner-scoped).
    assert svc.revoke_share(session, owner, token) is True

    # Now it is invisible to the public read path.
    assert ShareLinkRepository(session).get_by_token(token) is None
    with pytest.raises(LookupError):
        svc.public_view(session, token, presign=_fake_presign)

    # The row is retained (soft delete) for audit.
    assert session.query(ShareLink).count() == 1


def test_revoke_is_owner_scoped(session: Session):
    owner = _user(session, "owner@example.com")
    other = _user(session, "intruder@example.com")
    job = _job(session, owner)
    link = svc.create_share(session, owner, job.id)

    # A stranger cannot revoke the owner's link.
    assert svc.revoke_share(session, other, link.token) is False
    assert ShareLinkRepository(session).get_by_token(link.token) is not None

    # A double-revoke by the owner is a harmless no-op.
    assert svc.revoke_share(session, owner, link.token) is True
    assert svc.revoke_share(session, owner, link.token) is False


def test_unknown_token_is_not_found(session: Session):
    assert ShareLinkRepository(session).get_by_token("nope") is None
    with pytest.raises(LookupError):
        svc.public_view(session, "nope", presign=_fake_presign)


# =========================================================================== #
# View counting
# =========================================================================== #
def test_view_count_increments(session: Session):
    owner = _user(session, "owner@example.com")
    job = _job(session, owner)
    link = svc.create_share(session, owner, job.id)
    token = link.token

    assert link.view_count == 0
    for expected in (1, 2, 3):
        svc.public_view(session, token, presign=_fake_presign)
        refreshed = ShareLinkRepository(session).get_by_token(token)
        assert refreshed.view_count == expected


def test_revoked_link_never_counts_a_view(session: Session):
    owner = _user(session, "owner@example.com")
    job = _job(session, owner)
    link = svc.create_share(session, owner, job.id)
    token = link.token

    svc.revoke_share(session, owner, token)
    # increment_view guards on NOT revoked -> no-op.
    ShareLinkRepository(session).increment_view(token)
    row = session.query(ShareLink).filter_by(token=token).one()
    assert row.view_count == 0


# =========================================================================== #
# One active link per job
# =========================================================================== #
def test_one_active_link_per_job(session: Session):
    owner = _user(session, "owner@example.com")
    job = _job(session, owner)

    first = svc.create_share(session, owner, job.id)
    second = svc.create_share(session, owner, job.id)

    # Re-sharing returns the SAME live link (no duplicate).
    assert second.id == first.id
    assert second.token == first.token
    assert session.query(ShareLink).filter_by(job_id=job.id).count() == 1


def test_revoked_link_does_not_block_a_fresh_share(session: Session):
    owner = _user(session, "owner@example.com")
    job = _job(session, owner)

    first = svc.create_share(session, owner, job.id)
    assert svc.revoke_share(session, owner, first.token) is True

    # After revoking, a new share can be minted (the revoked row does not block).
    second = svc.create_share(session, owner, job.id)
    assert second.id != first.id
    assert second.token != first.token
    # Exactly one ACTIVE link exists for the job.
    active = (
        session.query(ShareLink)
        .filter_by(job_id=job.id, revoked=False)
        .count()
    )
    assert active == 1
