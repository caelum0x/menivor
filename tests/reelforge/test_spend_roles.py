"""Team spend-role tests — pure matrix + service enforcement + bridge/router."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.spend import roles
from app.domains.spend.service import SpendError, SpendPolicyService
from app.models.db.base import Base
from app.models.db.marketplace import PaymentIntent
from app.models.db.models import User
from app.domains.wallet.service import WalletService
from app.services import workspaces as ws_service


# --------------------------------------------------------------------------- #
# Pure matrix
# --------------------------------------------------------------------------- #
def test_role_matrix_defaults():
    # topup / manage require admin+.
    assert roles.can(roles.TOPUP, "owner")
    assert roles.can(roles.TOPUP, "admin")
    assert not roles.can(roles.TOPUP, "member")
    assert roles.can(roles.MANAGE_POLICY, "admin")
    assert not roles.can(roles.MANAGE_POLICY, "member")
    # spend defaults to member+.
    assert roles.can(roles.SPEND, "member")
    assert not roles.can(roles.SPEND, None)


def test_spend_can_be_restricted_to_admins():
    assert not roles.can(roles.SPEND, "member", min_spend_role="admin")
    assert roles.can(roles.SPEND, "admin", min_spend_role="admin")


def test_normalize_min_spend_role():
    assert roles.normalize_min_spend_role("ADMIN") == "admin"
    assert roles.normalize_min_spend_role("garbage") == "member"


# --------------------------------------------------------------------------- #
# Service enforcement over a real workspace
# --------------------------------------------------------------------------- #
@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture()
def team(factory):
    """An owner + an invited member of one workspace; returns ids."""
    with factory() as s:
        owner = User(email="owner@example.com", api_key_hash="o")
        member = User(email="member@example.com", api_key_hash="m")
        s.add_all([owner, member])
        s.flush()
        oid, mid = owner.id, member.id
        ws = ws_service.create_workspace(s, oid, "Acme")
        wid = ws.id
        ws_service.invite_member(s, wid, oid, "member@example.com", role=ws_service.ROLE_MEMBER)
        s.commit()
    return {"owner": oid, "member": mid, "workspace": wid}


def test_manage_policy_requires_admin(factory, team):
    with factory() as s:
        svc = SpendPolicyService(s)
        # Owner can manage.
        svc.assert_can(roles.MANAGE_POLICY, team["workspace"], team["owner"])
        # Plain member cannot.
        with pytest.raises(SpendError) as ei:
            svc.assert_can(roles.MANAGE_POLICY, team["workspace"], team["member"])
        assert ei.value.status_code == 403


def test_spend_restricted_when_min_role_admin(factory, team):
    with factory() as s:
        # Restrict spending to admins.
        SpendPolicyService(s).upsert_workspace_policy(
            team["workspace"], spend_min_role="admin"
        )
        s.commit()
    with factory() as s:
        svc = SpendPolicyService(s)
        svc.assert_can(roles.SPEND, team["workspace"], team["owner"])  # ok
        with pytest.raises(SpendError):
            svc.assert_can(roles.SPEND, team["workspace"], team["member"])


def test_member_cannot_spend_pool_via_bridge(factory, team):
    # Fund the pool + restrict spending to admins.
    with factory() as s:
        svc = WalletService(s)
        acct = svc._repo.get_or_create_workspace_account(team["workspace"])
        intent = PaymentIntent(
            account_id=acct.id, user_id=team["owner"], idempotency_key="g",
            credit_micros=10_000_000, total_charge_micros=10_000_000, status="pending",
        )
        s.add(intent)
        s.flush()
        svc.confirm_intent(intent.id)
        SpendPolicyService(s).upsert_workspace_policy(team["workspace"], spend_min_role="admin")
        s.commit()

    from app.domains.reels.wallet_bridge import WalletBridgeError, WalletIntent, reserve_for_job

    wintent = WalletIntent(
        profile="p", quote={"max_cost_micros": 500_000},
        max_cost_micros=500_000, workspace_id=team["workspace"],
    )
    with factory() as s:
        with pytest.raises(WalletBridgeError) as ei:
            reserve_for_job(s, user_id=team["member"], intent=wintent, job_id="j", request_id="r")
        assert ei.value.status_code == 403  # role, not balance


def test_owner_can_spend_pool_via_bridge(factory, team):
    with factory() as s:
        svc = WalletService(s)
        acct = svc._repo.get_or_create_workspace_account(team["workspace"])
        intent = PaymentIntent(
            account_id=acct.id, user_id=team["owner"], idempotency_key="g",
            credit_micros=10_000_000, total_charge_micros=10_000_000, status="pending",
        )
        s.add(intent)
        s.flush()
        svc.confirm_intent(intent.id)
        SpendPolicyService(s).upsert_workspace_policy(team["workspace"], spend_min_role="admin")
        s.commit()

    from app.domains.reels.wallet_bridge import WalletIntent, reserve_for_job

    wintent = WalletIntent(
        profile="p", quote={"max_cost_micros": 500_000},
        max_cost_micros=500_000, workspace_id=team["workspace"],
    )
    with factory() as s:
        marker = reserve_for_job(
            s, user_id=team["owner"], intent=wintent, job_id="j2", request_id="r"
        )
        s.commit()
    assert marker["_wallet"]["reserved_micros"] == 500_000
