"""Clipping marketplace persistence (P11) — campaigns + clip submissions.

A brand funds a :class:`ClipCampaign` (CPM + budget); clippers post
:class:`ClipSubmission`s that accrue verified views. The payout math + viewbot
fraud gate live in ``app.domains.clipmarket.payout``; these rows are the durable
state (budget spent, submission status, computed payout). Registered on
``Base.metadata`` via ``migrations/env.py`` + ``models/db/__init__`` imports.

Nullability follows the repo rule: ``Mapped[str]`` default="" is NOT NULL;
timestamps NOT NULL with a server default.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class ClipCampaign(Base):
    """A brand campaign paying a CPM up to a budget."""

    __tablename__ = "clip_campaigns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"), nullable=False)
    cpm_micros: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_micros: Mapped[int] = mapped_column(Integer, nullable=False)
    spent_micros: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    min_views: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    # active | paused | exhausted | ended
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default=text("'active'"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ClipSubmission(Base):
    """A clipper's submission to a campaign, with verified views + payout state."""

    __tablename__ = "clip_submissions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("clip_campaigns.id"), index=True, nullable=False)
    clipper_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    clip_url: Mapped[str] = mapped_column(String(500), default="", server_default=text("''"), nullable=False)
    verified_views: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    payable_micros: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    # pending | approved | held_review | rejected | paid
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'"), index=True, nullable=False
    )
    fraud_score: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)  # 0..100
    fraud_flags: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
