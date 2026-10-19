# ruff: noqa: F811 - pytest fixtures are imported from test_user_entitlements
"""MG12: a paying workspace seat gets the clean MP4; a non-member does not.

Real SQLite rows; RevenueCat is faked to deny so only the seat source can grant.
"""

from __future__ import annotations

import pytest

from app.models.db.models import Subscription, User, Workspace, WorkspaceMember
from app.models.db.repositories import CreditRepository
from app.services import user_entitlements as ue
from tests.reelforge.test_user_entitlements import db, rc_denies  # noqa: F401


def _team(factory, owner_id: str, *, member_ids=(), status=None, plan_key="starter", pool=0) -> str:
    with factory() as s:
        ws = Workspace(name="Team", owner_id=owner_id)
        s.add(ws)
        s.flush()
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=owner_id, role="owner"))
        for uid in member_ids:
            s.add(WorkspaceMember(workspace_id=ws.id, user_id=uid, role="member"))
        if status:
            s.add(Subscription(workspace_id=ws.id, plan_key=plan_key, provider="dodo",
                               provider_ref=f"sub_{ws.id}", status=status))
        s.flush()
        if pool:
            CreditRepository(s).workspace_grant(ws.id, pool, "purchase:dodo:pool")
        s.commit()
        return ws.id


def _user(factory, email: str) -> str:
    with factory() as s:
        user = User(email=email, display_name=email, api_key_hash=email)
        s.add(user)
        s.commit()
        return user.id


@pytest.mark.parametrize("status,pool", [("active", 0), ("trialing", 0), (None, 5)])
def test_member_of_paying_workspace_gets_clean_mp4(db, rc_denies, status, pool):
    factory, owner_id = db
    member_id = _user(factory, "seat@example.com")
    ws_id = _team(factory, owner_id, member_ids=[member_id], status=status, pool=pool)
    for uid in (owner_id, member_id):
        result = ue.user_entitlements(uid)
        assert result.clean_download and result.publish and result.source == ue.SOURCE_WORKSPACE
        assert ue.can_access_clean_result(uid, workspace_id=ws_id) is True
    assert not rc_denies  # the local seat answered; RevenueCat was never asked


def test_non_member_gets_preview_even_when_naming_the_workspace(db, rc_denies):
    factory, owner_id = db
    stranger = _user(factory, "stranger@example.com")
    ws_id = _team(factory, owner_id, status="active", pool=50)
    assert ue.can_access_clean_result(stranger) is False
    assert ue.can_access_clean_result(stranger, workspace_id=ws_id) is False  # IDOR
    with pytest.raises(ue.PaidAccessDenied):
        ue.require_paid_access(stranger, workspace_id=ws_id)


@pytest.mark.parametrize("status,plan_key", [("canceled", "starter"), ("past_due", "starter"),
                                             ("active", "free")])
def test_unpaid_workspace_without_pool_grants_nothing(db, rc_denies, status, plan_key):
    factory, owner_id = db
    member_id = _user(factory, "seat2@example.com")
    _team(factory, owner_id, member_ids=[member_id], status=status, plan_key=plan_key)
    assert ue.user_entitlements(member_id).clean_download is False


def test_narrowing_to_another_workspace_does_not_borrow_a_paid_one(db, rc_denies):
    factory, owner_id = db
    member_id = _user(factory, "seat3@example.com")
    _team(factory, owner_id, member_ids=[member_id], status="active")
    other_owner = _user(factory, "other@example.com")
    unpaid = _team(factory, other_owner, member_ids=[member_id])
    assert ue.can_access_clean_result(member_id) is True
    assert ue.can_access_clean_result(member_id, workspace_id=unpaid) is False
