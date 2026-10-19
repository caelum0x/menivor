"""Cross-network budget allocation log (table created by migration ``a7d3e9c1f2b4``).

:class:`AdAllocationProposal` is one daily proposal to split a total daily
budget across networks (``meta``, ``tiktok``, ``organic_boost``, later
``google``/``linkedin``). It snapshots the per-network stats it was computed
from, the current and proposed split, and links to the approval item that
gates it. Proposals are NEVER applied automatically above the configured
delta; ``UNIQUE(user_id, run_date)`` keeps the daily job idempotent.

Money is stored as integer micros (1 USD = 1_000_000) to match the wallet.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.domains.approvals import models as _approval_models  # noqa: F401  (registers approval_items for the FK)
from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base

NETWORKS = frozenset({"meta", "tiktok", "organic_boost", "google", "linkedin"})

STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_SUPERSEDED = "superseded"
STATUS_FAILED = "failed"
ALLOCATION_STATUSES = frozenset({
    STATUS_PROPOSED, STATUS_APPROVED, STATUS_APPLIED, STATUS_REJECTED, STATUS_SUPERSEDED, STATUS_FAILED,
})

METHODS = frozenset({"thompson", "ucb", "rules"})


def _uuid() -> str:
    return uuid.uuid4().hex


class AdAllocationProposal(Base):
    __tablename__ = "ad_allocation_proposals"
    __table_args__ = (UniqueConstraint("user_id", "run_date", name="uq_ad_allocation_proposals_owner_day"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(default=7, server_default=sql_text("7"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default=sql_text("'USD'"), nullable=False)
    total_daily_budget_micros: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=sql_text("0"), nullable=False
    )
    # {"meta": {"spend_micros", "results", "impressions", "cost_per_result_micros", "samples"}, ...}
    network_stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # {"meta": 0.6, "tiktok": 0.4} fractions summing to 1.
    current_split: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    proposed_split: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Largest absolute per-network change, as a fraction of total (0.15 = 15 points).
    max_delta: Mapped[float] = mapped_column(Float, default=0.0, server_default=sql_text("0"), nullable=False)
    method: Mapped[str] = mapped_column(String(16), default="thompson", server_default=sql_text("'thompson'"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_PROPOSED, server_default=sql_text("'proposed'"), nullable=False
    )
    approval_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("approval_items.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
