"""Unit tests for invoicing + platform revenue summary (Billing, Epic 3).

Runs against an in-memory SQLite DB built from the live ORM metadata. Covered
behaviour:

* :func:`invoicing.build_invoice` totals its line items exactly (integer cents)
  and is workspace-scoped; :func:`invoicing.list_invoices` /
  :func:`invoicing.get_invoice` never return another tenant's invoices;
* :func:`invoicing.build_overage_invoice` prices metered overage per unit;
* :func:`invoicing.revenue_summary` is HARD-GATED on ``User.is_staff`` — a
  non-staff caller is denied, a staff caller gets the cross-tenant revenue vs
  credits figures.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.base import Base
from app.models.db.models import User, Workspace
from app.models.db.repositories import CreditRepository, SubscriptionRepository
from app.services import invoicing, metering

_PERIOD_NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)
_PERIOD_YM = "2026-08"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
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


def _make_user(session, email: str, *, is_staff: bool = False) -> str:
    user = User(email=email, is_staff=is_staff)
    session.add(user)
    session.flush()
    return user.id


def _make_workspace(session, owner_id: str, name: str = "Tenant") -> str:
    ws = Workspace(owner_id=owner_id, name=name)
    session.add(ws)
    session.flush()
    return ws.id


# --------------------------------------------------------------------------- #
# build / list invoices — workspace-scoped, exact integer totals
# --------------------------------------------------------------------------- #
def test_build_invoice_sums_line_items(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "o@example.com")
        ws = _make_workspace(s, owner)

        invoice = invoicing.build_invoice(
            s,
            workspace_id=ws,
            line_items=[
                {"description": "Pro plan", "quantity": 1, "amount_cents": 14900},
                {"description": "Overage", "quantity": 30, "amount_cents": 3000},
            ],
            status="open",
        )
        # Header total is the exact integer sum of the lines.
        assert invoice.amount_cents == 17900
        assert invoice.currency == "usd"
        assert invoice.status == "open"

        lines = invoicing.invoice_line_items(s, invoice.id, ws)
        assert sorted(li.amount_cents for li in lines) == [3000, 14900]
        assert sum(li.amount_cents for li in lines) == 17900


def test_list_invoices_is_tenant_scoped(session_factory):
    with _session(session_factory) as s:
        owner_a = _make_user(s, "a@example.com")
        owner_b = _make_user(s, "b@example.com")
        ws_a = _make_workspace(s, owner_a, "A")
        ws_b = _make_workspace(s, owner_b, "B")

        invoicing.build_invoice(
            s, workspace_id=ws_a,
            line_items=[{"description": "A", "amount_cents": 1000}],
        )
        invoicing.build_invoice(
            s, workspace_id=ws_b,
            line_items=[{"description": "B", "amount_cents": 2000}],
        )

        a_invoices = invoicing.list_invoices(s, ws_a)
        b_invoices = invoicing.list_invoices(s, ws_b)
        assert [i.amount_cents for i in a_invoices] == [1000]
        assert [i.amount_cents for i in b_invoices] == [2000]
        assert all(i.workspace_id == ws_a for i in a_invoices)


def test_get_invoice_cross_tenant_denied(session_factory):
    with _session(session_factory) as s:
        owner_a = _make_user(s, "a@example.com")
        owner_b = _make_user(s, "b@example.com")
        ws_a = _make_workspace(s, owner_a, "A")
        ws_b = _make_workspace(s, owner_b, "B")

        invoice_a = invoicing.build_invoice(
            s, workspace_id=ws_a,
            line_items=[{"description": "A", "amount_cents": 500}],
        )

        # Tenant B cannot resolve A's invoice by guessing its id.
        assert invoicing.get_invoice(s, invoice_a.id, ws_b) is None
        assert invoicing.get_invoice(s, invoice_a.id, ws_a) is not None
        # And its line items are not readable cross-tenant.
        assert invoicing.invoice_line_items(s, invoice_a.id, ws_b) == []


def test_build_overage_invoice_prices_units(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "o@example.com")
        ws = _make_workspace(s, owner)
        SubscriptionRepository(s).upsert(ws, plan_key="pro", status="active")
        # pro monthly_credits == 120; 150 renders -> 30 overage.
        metering.record_usage(s, ws, "render", 150, "render:x", now=_PERIOD_NOW)

        invoice = invoicing.build_overage_invoice(
            s, workspace_id=ws, period_ym=_PERIOD_YM, unit_price_cents=50
        )
        # 30 units @ 50c == 1500c.
        assert invoice.amount_cents == 1500
        lines = invoicing.invoice_line_items(s, invoice.id, ws)
        assert len(lines) == 1
        assert lines[0].quantity == 30
        assert lines[0].amount_cents == 1500


def test_overage_invoice_zero_within_allotment(session_factory):
    with _session(session_factory) as s:
        owner = _make_user(s, "o@example.com")
        ws = _make_workspace(s, owner)
        SubscriptionRepository(s).upsert(ws, plan_key="pro", status="active")
        metering.record_usage(s, ws, "render", 50, "render:ok", now=_PERIOD_NOW)

        invoice = invoicing.build_overage_invoice(
            s, workspace_id=ws, period_ym=_PERIOD_YM, unit_price_cents=50
        )
        assert invoice.amount_cents == 0
        assert invoicing.invoice_line_items(s, invoice.id, ws) == []


# --------------------------------------------------------------------------- #
# revenue_summary — is_staff HARD-GATED, cross-tenant
# --------------------------------------------------------------------------- #
def test_revenue_summary_denies_non_staff(session_factory):
    with _session(session_factory) as s:
        non_staff = _make_user(s, "user@example.com", is_staff=False)
        with pytest.raises(PermissionError):
            invoicing.revenue_summary(s, non_staff)


def test_revenue_summary_denies_unknown_user(session_factory):
    with _session(session_factory) as s:
        with pytest.raises(PermissionError):
            invoicing.revenue_summary(s, "ghost-user")


def test_revenue_summary_staff_aggregates_cross_tenant(session_factory):
    with _session(session_factory) as s:
        staff = _make_user(s, "staff@example.com", is_staff=True)
        owner_a = _make_user(s, "a@example.com")
        owner_b = _make_user(s, "b@example.com")
        ws_a = _make_workspace(s, owner_a, "A")
        ws_b = _make_workspace(s, owner_b, "B")

        # Two PAID invoices across two tenants + one draft (excluded).
        invoicing.build_invoice(
            s, workspace_id=ws_a, status="paid",
            line_items=[{"description": "A", "amount_cents": 14900}],
        )
        invoicing.build_invoice(
            s, workspace_id=ws_b, status="paid",
            line_items=[{"description": "B", "amount_cents": 4900}],
        )
        invoicing.build_invoice(
            s, workspace_id=ws_a, status="draft",
            line_items=[{"description": "draft", "amount_cents": 99999}],
        )
        # Some credits granted (the liability side).
        CreditRepository(s).workspace_grant(ws_a, 120, reason="grant:a")
        CreditRepository(s).grant(owner_b, 30, reason="grant:b")

        summary = invoicing.revenue_summary(s, staff, status="paid")
        assert summary["revenue_cents"] == 14900 + 4900  # draft excluded
        assert summary["net_cents"] == 19800
        assert summary["credits_granted"] == 150  # 120 + 30


def test_revenue_summary_respects_cutoff(session_factory):
    with _session(session_factory) as s:
        staff = _make_user(s, "staff@example.com", is_staff=True)
        owner = _make_user(s, "o@example.com")
        ws = _make_workspace(s, owner)
        invoicing.build_invoice(
            s, workspace_id=ws, status="paid",
            line_items=[{"description": "now", "amount_cents": 5000}],
        )

        # A cutoff in the far future excludes the just-created invoice.
        future = datetime(2999, 1, 1, tzinfo=timezone.utc)
        summary = invoicing.revenue_summary(s, staff, future)
        assert summary["revenue_cents"] == 0
