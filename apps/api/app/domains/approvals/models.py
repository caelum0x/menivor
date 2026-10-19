"""Approvals feed persistence (table created by migration ``a7d3e9c1f2b4``).

:class:`ApprovalItem` is one pending (or decided) action. ``source`` names the
producing subsystem and ``external_ref`` points at that subsystem's own row
(e.g. a ``social_engagement_actions.id`` or ``ad_allocation_proposals.id``);
``UNIQUE(user_id, source, external_ref)`` makes enqueueing idempotent, so an
adapter can re-sync without creating duplicates.

Decisions are applied by delegating to the source's existing service; the
item only records the decision and its outcome. Nothing is executed on
insert.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base

# Producing subsystems.
SOURCE_SOCIAL_REPLY = "social_reply"
SOURCE_PUBLISH_HOLD = "publish_hold"
SOURCE_AD_BUDGET = "ad_budget"
SOURCE_DESIGN_PUBLISH = "design_publish"
SOURCE_CAPTURE_PUBLISH = "capture_publish"
SOURCE_CATALOG_IMPORT = "catalog_import"
# Integrations: pause/resume an ad on a connected ad platform (ads agent proposals).
SOURCE_AD_ACTION = "ad_action"
# Wave 2: generated creatives waiting for a swipe (review queue), and paid studio renders
# (AI actor product shots, lip-sync translations) that spend AI-video credits on approve.
SOURCE_CREATIVE_REVIEW = "creative_review"
SOURCE_STUDIO_RENDER = "studio_render"
APPROVAL_SOURCES = frozenset({
    SOURCE_SOCIAL_REPLY,
    SOURCE_PUBLISH_HOLD,
    SOURCE_AD_BUDGET,
    SOURCE_DESIGN_PUBLISH,
    SOURCE_CAPTURE_PUBLISH,
    SOURCE_CATALOG_IMPORT,
    SOURCE_AD_ACTION,
    SOURCE_CREATIVE_REVIEW,
    SOURCE_STUDIO_RENDER,
})

# Lifecycle. ``pending`` is the only state a decision can be made from.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"     # decision recorded, execution in progress/queued
STATUS_EXECUTED = "executed"     # the source service applied it
STATUS_REJECTED = "rejected"
STATUS_EDITED = "edited"         # approved with an edited payload
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"         # approved but the source service failed
APPROVAL_STATUSES = frozenset({
    STATUS_PENDING,
    STATUS_APPROVED,
    STATUS_EXECUTED,
    STATUS_REJECTED,
    STATUS_EDITED,
    STATUS_EXPIRED,
    STATUS_FAILED,
})
TERMINAL_STATUSES = frozenset({STATUS_EXECUTED, STATUS_REJECTED, STATUS_EXPIRED, STATUS_FAILED})

# Risk hint for UI ordering ("spends money" > "public post" > "reversible").
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_LEVELS = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH})


def _uuid() -> str:
    return uuid.uuid4().hex


class ApprovalItem(Base):
    __tablename__ = "approval_items"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_ref", name="uq_approval_items_owner_source_ref"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    risk: Mapped[str] = mapped_column(String(12), default=RISK_MEDIUM, server_default=sql_text("'medium'"), nullable=False)
    # What will happen on approve (source-specific, shown to the reviewer).
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Reviewer-edited payload when status == edited.
    edited_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_PENDING, server_default=sql_text("'pending'"), index=True, nullable=False
    )
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # user id or "rally-bridge"
    decided_via: Mapped[str] = mapped_column(String(16), default="", server_default=sql_text("''"), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
