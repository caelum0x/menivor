"""Tests for right-to-erasure PII anonymization (GDPR Art. 17 — Compliance, Epic 5).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered:

* PII is anonymized in place (email tombstoned; name/handle/bio blanked/nulled);
* credentials are revoked (API keys, legacy inline key, OAuth social blobs);
* job scripts / prompt params are blanked while the ROW is preserved (no FK break);
* financial (credit ledger) records are retained and the action is audited;
* erasure is idempotent (a second run is a no-op and never raises);
* a DIFFERENT user's data is never touched.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import (
    Asset,
    AuditLog,
    ExternalIdentity,
    Job,
    MarketplaceTemplate,
    Notification,
    SavedIdea,
    ShareLink,
    SocialAccount,
    User,
    UserApiKey,
    UserVoice,
    Workspace,
)
from app.models.db.repositories import (
    CreditRepository,
    JobRepository,
    UserApiKeyRepository,
)
from app.services.compliance import erasure


@pytest.fixture(autouse=True)
def _no_external_services(monkeypatch):
    """No network: R2 and Clerk read as not configured on this server."""
    from app.services.compliance import erasure_followups

    monkeypatch.setattr(erasure_followups, "_r2", lambda: None)
    monkeypatch.setattr(erasure_followups, "_clerk_secret", lambda: "")


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@contextmanager
def _session(factory):
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_user(
    session, email: str, *, display_name="", handle=None, bio=None
) -> str:
    user = User(
        email=email,
        display_name=display_name,
        handle=handle,
        bio=bio,
        api_key_hash="live-hash",
        credits=0,
    )
    session.add(user)
    session.flush()
    return user.id


def _add_api_key(session, user_id: str, key_hash: str) -> None:
    session.add(UserApiKey(user_id=user_id, key_hash=key_hash, prefix="rf_x"))
    session.flush()


def _add_social(session, user_id: str, provider: str = "tiktok") -> None:
    session.add(
        SocialAccount(
            user_id=user_id,
            provider=provider,
            access_token_enc="enc-access",
            refresh_token_enc="enc-refresh",
            external_account_id="ext-123",
            scopes="video.publish",
        )
    )
    session.flush()


# --------------------------------------------------------------------------- #
# anonymization + credential revocation + audit
# --------------------------------------------------------------------------- #
def test_erase_anonymizes_pii_and_revokes_credentials(session_factory):
    with _session(session_factory) as s:
        a = _make_user(
            s, "alice@example.com", display_name="Alice", handle="alice", bio="hi"
        )
        _add_api_key(s, a, "hash-a")
        _add_social(s, a)
        job = JobRepository(s).create(
            user_id=a, kind="avatar_reel", params={"prompt": "secret", "layout": "pip"}
        )
        JobRepository(s).set_script(job.id, "my secret narration")

        req = erasure.erase_user(s, a)

        user = s.get(User, a)
        assert user.email == f"deleted+{a}@tombstone.invalid"
        assert user.display_name == ""
        assert user.handle is None
        assert user.bio is None
        assert user.api_key_hash == ""

        # Personal API keys revoked (rows retained for audit).
        keys = UserApiKeyRepository(s).list_for_user(a)
        assert keys and all(k.revoked for k in keys)

        # OAuth social credential blobs blanked (row preserved).
        acct = s.execute(
            select(SocialAccount).where(SocialAccount.user_id == a)
        ).scalars().first()
        assert acct is not None
        assert acct.access_token_enc == ""
        assert acct.refresh_token_enc is None
        assert acct.external_account_id == ""
        assert acct.scopes == ""

        # Job script / prompt blanked; row + non-PII knob preserved (no FK break).
        job2 = s.get(Job, job.id)
        assert job2 is not None
        assert job2.script == ""
        assert "prompt" not in (job2.params or {})
        assert job2.params.get("layout") == "pip"

        # Request marked completed.
        assert req.status == "completed"
        assert req.completed_at is not None

        # Audited (append-only).
        audits = list(
            s.execute(
                select(AuditLog).where(AuditLog.action == "compliance.user_erased")
            ).scalars().all()
        )
        assert len(audits) == 1
        assert audits[0].target_id == a


def test_erase_preserves_financial_records(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com", display_name="Alice")
        CreditRepository(s).grant(a, 100, "purchase")

        erasure.erase_user(s, a)

        # Financial ledger row preserved (never cascade-deleted); the unused
        # balance is recorded as forfeited on delete (MD26), not removed.
        ledger = CreditRepository(s).list_for_user(a)
        assert [(row.reason, row.delta) for row in ledger] == [
            ("purchase", 100),
            ("forfeited_on_delete", -100),
        ]


def test_erase_is_idempotent(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com", display_name="Alice", handle="al")
        _add_api_key(s, a, "hash-a")

        first = erasure.erase_user(s, a)
        assert first.status == "completed"

        # A second run must not raise and must leave PII anonymized.
        second = erasure.erase_user(s, a)
        assert second.status == "completed"

        user = s.get(User, a)
        assert user.email == f"deleted+{a}@tombstone.invalid"
        assert user.handle is None


def test_erase_rejects_unknown_user(session_factory):
    with _session(session_factory) as s:
        with pytest.raises(ValueError):
            erasure.erase_user(s, "nope")
        with pytest.raises(ValueError):
            erasure.erase_user(s, "  ")


# --------------------------------------------------------------------------- #
# strict scoping — a different user's data is never touched
# --------------------------------------------------------------------------- #
def test_erase_does_not_touch_other_user(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com", display_name="Alice")
        b = _make_user(
            s, "bob@example.com", display_name="Bob", handle="bob", bio="bob-bio"
        )
        _add_api_key(s, b, "hash-b")
        _add_social(s, b)
        job_b = JobRepository(s).create(
            user_id=b, kind="avatar_reel", params={"prompt": "keep-bob"}
        )
        JobRepository(s).set_script(job_b.id, "bob narration")

        erasure.erase_user(s, a)

        user_b = s.get(User, b)
        assert user_b.email == "bob@example.com"
        assert user_b.display_name == "Bob"
        assert user_b.handle == "bob"
        assert user_b.bio == "bob-bio"

        keys_b = UserApiKeyRepository(s).list_for_user(b)
        assert keys_b and all(not k.revoked for k in keys_b)

        acct_b = s.execute(
            select(SocialAccount).where(SocialAccount.user_id == b)
        ).scalars().first()
        assert acct_b.access_token_enc == "enc-access"

        job2 = s.get(Job, job_b.id)
        assert job2.script == "bob narration"
        assert job2.params.get("prompt") == "keep-bob"


# --------------------------------------------------------------------------- #
# extended PII surfaces — voice, SSO identity, marketplace, share, ideas, media
# --------------------------------------------------------------------------- #
def test_erase_wipes_cloned_brand_voice(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        s.add(
            UserVoice(
                user_id=a,
                provider="elevenlabs",
                provider_voice_id="voice-abc",
                name="My Voice",
                sample_key="voices/a/sample.wav",
                consent=True,
                status="ready",
            )
        )
        s.flush()

        erasure.erase_user(s, a)

        v = s.execute(
            select(UserVoice).where(UserVoice.user_id == a)
        ).scalars().first()
        assert v is not None  # row kept (FK integrity)
        assert v.sample_key == ""
        assert v.provider_voice_id == ""
        assert v.name == ""
        assert v.consent is False


def test_erase_tombstones_external_identity(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        ws = Workspace(name="W", owner_id=a)
        s.add(ws)
        s.flush()
        s.add(
            ExternalIdentity(
                user_id=a,
                workspace_id=ws.id,
                idp_subject="alice@corp.example",
                email="alice@corp.example",
                provisioned=True,
            )
        )
        s.flush()

        erasure.erase_user(s, a)

        ident = s.execute(
            select(ExternalIdentity).where(ExternalIdentity.user_id == a)
        ).scalars().first()
        assert ident is not None
        assert ident.email == ""
        assert ident.idp_subject == f"deleted+{a}@tombstone.invalid"
        assert ident.provisioned is False


def test_erase_scrubs_and_hides_marketplace_template(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        s.add(
            MarketplaceTemplate(
                author_user_id=a,
                title="My App Demo",
                description="secret niche desc",
                prompt="secret prompt",
                params={"prompt": "secret", "layout": "pip"},
                tags=["saas"],
                published=True,
            )
        )
        s.flush()

        erasure.erase_user(s, a)

        t = s.execute(
            select(MarketplaceTemplate).where(
                MarketplaceTemplate.author_user_id == a
            )
        ).scalars().first()
        assert t is not None
        assert t.title == ""
        assert t.description == ""
        assert t.prompt == ""
        assert "prompt" not in (t.params or {})
        assert t.tags == []
        assert t.published is False


def test_erase_revokes_share_links_and_blanks_media(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        job = JobRepository(s).create(user_id=a, kind="avatar_reel", params={})
        job.result_key = "r/final.mp4"
        job.poster_key = "r/poster.jpg"
        job.preview_key = "r/prev.mp4"
        job.cover_key = "r/cover.jpg"
        s.flush()
        s.add(Asset(user_id=a, job_id=job.id, kind="upload", r2_key="up/x.png",
                    meta={"orig": "name.png"}))
        s.add(ShareLink(job_id=job.id, user_id=a, token="tok-123", revoked=False))
        s.flush()

        erasure.erase_user(s, a)

        j = s.get(Job, job.id)
        assert j.result_key == "" and j.poster_key == ""
        assert j.preview_key == "" and j.cover_key == ""

        asset = s.execute(select(Asset).where(Asset.user_id == a)).scalars().first()
        assert asset.r2_key == "" and asset.meta == {}

        link = s.execute(
            select(ShareLink).where(ShareLink.user_id == a)
        ).scalars().first()
        assert link is not None and link.revoked is True


def test_erase_scrubs_saved_ideas_and_notifications(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        s.add(SavedIdea(user_id=a, title="Niche idea", hook="a hook",
                        payload={"script_outline": "secret"}))
        s.add(Notification(user_id=a, kind="job_failed", title="Failed",
                           body="error detail", data={"error": "secret"}))
        s.flush()

        erasure.erase_user(s, a)

        idea = s.execute(
            select(SavedIdea).where(SavedIdea.user_id == a)
        ).scalars().first()
        assert idea.title == "" and idea.hook == "" and idea.payload == {}

        note = s.execute(
            select(Notification).where(Notification.user_id == a)
        ).scalars().first()
        assert note.title == "" and note.body == "" and note.data == {}


def test_erase_scrubs_nested_prompt_params(session_factory):
    with _session(session_factory) as s:
        a = _make_user(s, "alice@example.com")
        job = JobRepository(s).create(
            user_id=a,
            kind="avatar_reel",
            params={
                "layout": "pip",
                "variant": {"prompt": "nested secret", "seed": 7},
                "segments": [{"text": "narration one"}, {"text": "narration two"}],
            },
        )
        s.flush()

        erasure.erase_user(s, a)

        j = s.get(Job, job.id)
        assert j.params["layout"] == "pip"
        assert "prompt" not in j.params["variant"]
        assert j.params["variant"]["seed"] == 7
        assert all("text" not in seg for seg in j.params["segments"])
