"""CRUD variants — delete character, revoke gateway key, campaign lifecycle."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.characters.consistency import CharacterProfile
from app.domains.characters.repository import CharacterRepository
from app.domains.clipmarket import service as clip
from app.domains.gateway import service as gw
from app.models.db import characters, clipmarket, gateway, models  # noqa: F401 - register
from app.models.db.base import Base
from app.models.db.models import User


def _fund_wallet(session, user_id: str, micros: int) -> None:
    """Grant wallet balance so campaign budgets can be escrowed."""
    from app.domains.wallet.repository import ENTRY_GRANT, WalletRepository

    repo = WalletRepository(session)
    account = repo.get_or_create_personal_account(user_id)
    repo.append_entry(account.id, entry_type=ENTRY_GRANT, reason="test_topup",
                      available_delta=micros)
    session.flush()


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for uid in ("u1", "u2"):
        s.add(User(id=uid, email=f"{uid}@x.com"))
    s.flush()
    # Campaign budgets are escrowed from the brand's wallet.
    _fund_wallet(s, "u1", 100_000_000)
    yield s
    s.close()


# --------------------------------------------------------------------------- #
# Character delete (owner-scoped)
# --------------------------------------------------------------------------- #
def test_delete_character_owner_scoped(session):
    repo = CharacterRepository(session)
    row = repo.create(user_id="u1", profile=CharacterProfile("", "Nova", descriptors=("x",)))
    # A different user cannot delete it.
    assert repo.delete_owned(row.id, "u2") is False
    assert repo.get(row.id) is not None
    # The owner can.
    assert repo.delete_owned(row.id, "u1") is True
    assert repo.get(row.id) is None


def test_rename_character(session):
    repo = CharacterRepository(session)
    row = repo.create(user_id="u1", profile=CharacterProfile("", "Nova", descriptors=("x",)))
    key_before = row.identity_key
    renamed = repo.rename_owned(row.id, "u1", name="Zed")
    assert renamed.name == "Zed"
    # Identity lock is unchanged by a rename.
    assert renamed.identity_key == key_before


# --------------------------------------------------------------------------- #
# Gateway key revoke
# --------------------------------------------------------------------------- #
def test_revoke_key_disables_charges(session):
    key, _ = gw.create_key(session, owner_id="u1", daily_cap_micros=1_000_000)
    from datetime import datetime, timezone

    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    assert gw.authorize_and_record(session, key, 10_000, now=now).allowed
    # Revoke -> further charges denied.
    gw.set_key_disabled(session, key_id=key.id, owner_id="u1", disabled=True)
    session.refresh(key)
    assert not gw.authorize_and_record(session, key, 10_000, now=now).allowed


def test_revoke_key_owner_scoped(session):
    key, _ = gw.create_key(session, owner_id="u1", daily_cap_micros=0)
    with pytest.raises(gw.GatewayServiceError):
        gw.set_key_disabled(session, key_id=key.id, owner_id="u2", disabled=True)


# --------------------------------------------------------------------------- #
# Campaign lifecycle
# --------------------------------------------------------------------------- #
def test_campaign_pause_resume_end(session):
    camp = clip.create_campaign(session, brand_id="u1", cpm_micros=1_000_000, budget_micros=10_000_000)
    assert camp.status == "active"
    assert clip.set_campaign_status(session, campaign_id=camp.id, brand_id="u1", status="paused").status == "paused"
    assert clip.set_campaign_status(session, campaign_id=camp.id, brand_id="u1", status="active").status == "active"
    ended = clip.set_campaign_status(session, campaign_id=camp.id, brand_id="u1", status="ended")
    assert ended.status == "ended"
    # Ended is terminal — cannot reactivate.
    with pytest.raises(clip.ClipmarketError):
        clip.set_campaign_status(session, campaign_id=camp.id, brand_id="u1", status="active")


def test_campaign_status_owner_scoped_and_validated(session):
    camp = clip.create_campaign(session, brand_id="u1", cpm_micros=1_000_000, budget_micros=10_000_000)
    with pytest.raises(clip.ClipmarketError):
        clip.set_campaign_status(session, campaign_id=camp.id, brand_id="u2", status="paused")
    with pytest.raises(clip.ClipmarketError):
        clip.set_campaign_status(session, campaign_id=camp.id, brand_id="u1", status="bogus")
