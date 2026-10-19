"""Invoicing + platform revenue summary (Enterprise Billing Platform, Epic 3).

Two audiences, two isolation rules:

* **Workspace-scoped invoices.** :func:`build_invoice` / :func:`list_invoices` /
  :func:`get_invoice` operate strictly within one ``workspace_id`` (the caller is
  gated on ``billing.manage`` at the API layer). No endpoint here returns another
  tenant's invoices — every read filters on the owning workspace.
* **Platform revenue.** :func:`revenue_summary` is the ONLY cross-tenant read, and
  it is HARD-GATED on ``User.is_staff`` (reusing the Epic 1 platform-admin gate
  :func:`app.services.admin._require_staff`) — a non-staff caller is rejected with
  :class:`PermissionError` before any aggregate runs.

All money is integer minor units (cents) end to end — no float ever touches an
amount — so totals are exact.
"""

from __future__ import annotations

from typing import Any

from app.services import metering

# --------------------------------------------------------------------------- #
# Workspace-scoped invoices (billing.manage gated at the API layer)
# --------------------------------------------------------------------------- #
def build_invoice(
    session: Any,
    *,
    workspace_id: str,
    line_items: list[dict] | None = None,
    currency: str = "usd",
    status: str = "draft",
    provider_ref: str = "",
    period_start: Any = None,
    period_end: Any = None,
    amount_cents: int | None = None,
) -> Any:
    """Create a workspace invoice from its line items; return the row.

    Each ``line_items`` entry is ``{description, quantity, amount_cents}`` (the
    line's integer minor-unit total). The invoice header ``amount_cents`` defaults
    to the exact integer SUM of the lines so the total can never drift from its
    lines; pass an explicit ``amount_cents`` to override with a
    provider-authoritative total. Tenant-scoped: the invoice belongs to
    ``workspace_id`` and is only ever readable within it. Raises ``ValueError`` on
    a blank ``workspace_id``.
    """
    from app.models.db.repositories import InvoiceRepository

    return InvoiceRepository(session).create(
        workspace_id=workspace_id,
        line_items=line_items,
        currency=currency,
        status=status,
        provider_ref=provider_ref,
        period_start=period_start,
        period_end=period_end,
        amount_cents=amount_cents,
    )


def build_overage_invoice(
    session: Any,
    *,
    workspace_id: str,
    period_ym: str,
    unit_price_cents: int,
    currency: str = "usd",
    status: str = "open",
) -> Any:
    """Build an invoice for a workspace's metered overage in a billing month.

    Reads the per-metric overage for the period (:func:`app.services.metering.overage_for`)
    and creates one line per metric that exceeded its plan limit, priced at
    ``unit_price_cents`` per over-limit unit. A workspace within its allotment
    produces a zero-total invoice with no lines. Tenant-scoped. Returns the
    created :class:`Invoice`.
    """
    price = max(0, int(unit_price_cents))
    overages = metering.overage_for(session, workspace_id, period_ym)
    line_items = [
        {
            "description": f"{metric} overage ({ov.overage} units @ {price}c)",
            "quantity": ov.overage,
            "amount_cents": ov.overage * price,
        }
        for metric, ov in sorted(overages.items())
        if ov.overage > 0
    ]
    return build_invoice(
        session,
        workspace_id=workspace_id,
        line_items=line_items,
        currency=currency,
        status=status,
    )


def list_invoices(
    session: Any, workspace_id: str, limit: int = 50, offset: int = 0
) -> list[Any]:
    """Return a workspace's invoices, newest first, paginated (tenant-scoped).

    A blank ``workspace_id`` returns ``[]``; the query filters strictly on the
    workspace so a caller can never receive another tenant's invoices.
    """
    from app.models.db.repositories import InvoiceRepository

    return InvoiceRepository(session).list_for_workspace(
        workspace_id, limit=limit, offset=offset
    )


def get_invoice(session: Any, invoice_id: str, workspace_id: str) -> Any:
    """Return an invoice only when it belongs to ``workspace_id`` (tenant-scoped).

    A foreign or missing id returns ``None`` so a caller can never read another
    tenant's invoice by guessing its id.
    """
    from app.models.db.repositories import InvoiceRepository

    return InvoiceRepository(session).get_owned(invoice_id, workspace_id)


def invoice_line_items(session: Any, invoice_id: str, workspace_id: str) -> list[Any]:
    """Return an invoice's line items, tenant-scoped (``[]`` if not owned)."""
    from app.models.db.repositories import InvoiceRepository

    repo = InvoiceRepository(session)
    if repo.get_owned(invoice_id, workspace_id) is None:
        return []
    return repo.list_line_items(invoice_id)


# --------------------------------------------------------------------------- #
# Platform revenue summary (is_staff HARD-GATED, reuses Epic 1)
# --------------------------------------------------------------------------- #
def revenue_summary(
    session: Any,
    admin_user_id: str,
    cutoff: Any = None,
    *,
    status: str = "paid",
) -> dict[str, int]:
    """Return a cross-tenant revenue summary — platform staff ONLY.

    HARD-GATED on ``User.is_staff`` via the Epic 1 platform-admin gate
    (:func:`app.services.admin._require_staff`): a blank/unknown/non-staff caller
    raises :class:`PermissionError` before any aggregate runs. Returns
    ``{revenue_cents, credits_granted, net_cents}`` where ``revenue_cents`` is the
    integer sum of ``status`` invoices since ``cutoff`` (default ``paid`` =
    realized revenue), ``credits_granted`` is the total credits granted since
    ``cutoff`` (the outstanding liability side), and ``net_cents`` mirrors revenue
    for convenience. A falsy ``cutoff`` sums the whole history.
    """
    from app.services.admin import _require_staff

    _require_staff(session, admin_user_id)

    from app.models.db.repositories import InvoiceRepository

    revenue_cents = InvoiceRepository(session).revenue_since(cutoff, status=status)
    credits_granted = _credits_granted_since(session, cutoff)
    return {
        "revenue_cents": int(revenue_cents),
        "credits_granted": int(credits_granted),
        "net_cents": int(revenue_cents),
    }


def _credits_granted_since(session: Any, cutoff: Any) -> int:
    """Total credits GRANTED (positive ledger deltas) across all tenants since cutoff.

    Cross-tenant aggregate reachable only through the staff-gated
    :func:`revenue_summary`. Sums only positive deltas (grants), so debits
    (spend) never net against the liability figure. A falsy ``cutoff`` sums the
    whole ledger history.
    """
    from sqlalchemy import func, select

    from app.models.db.models import CreditLedger

    stmt = select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
        CreditLedger.delta > 0
    )
    if cutoff is not None:
        stmt = stmt.where(CreditLedger.created_at >= cutoff)
    total = session.execute(stmt).scalar_one()
    return int(total or 0)


__all__ = [
    "build_invoice",
    "build_overage_invoice",
    "get_invoice",
    "invoice_line_items",
    "list_invoices",
    "revenue_summary",
]
