"""Menivor Growth: SEO persistence for one workspace's OpenSEO account.

A customer connects their own OpenSEO account (an API key from
openseo.so/settings, same bring-your-own-credential pattern as
``app.domains.integrations``) so Menivor can show them a basic site audit,
keyword research for their niche, and rank tracking for a handful of target
keywords in the Menivor dashboard. OpenSEO research/audit/rank-tracking calls
cost OpenSEO credits that belong to the customer's own account; Menivor never
spends them without an explicit customer action (see ``service.py``).

* :class:`SeoConnection` - one OpenSEO API key per scope (a workspace, or one
  user without a workspace), plus the OpenSEO project it researches.
* :class:`SeoAuditRun` - one site-audit request and its cached summary.
* :class:`SeoKeywordResearch` - cached keyword-research rows (volume,
  difficulty, CPC, intent) so re-opening the page never re-spends credits.
* :class:`SeoRankKeyword` / :class:`SeoRankSnapshot` - the handful of tracked
  keywords and their daily position history.

``owner_scope`` is ``ws:<workspace id>`` or ``user:<user id>``, matching
``app.domains.integrations.scope.Scope.owner_scope`` exactly (reused as-is).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base

STATUS_CONNECTED = "connected"
STATUS_REAUTH = "needs_reauth"

AUDIT_QUEUED = "queued"
AUDIT_RUNNING = "running"
AUDIT_COMPLETED = "completed"
AUDIT_FAILED = "failed"


def _uuid() -> str:
    return uuid.uuid4().hex


class SeoConnection(Base):
    __tablename__ = "seo_connections"
    __table_args__ = (UniqueConstraint("owner_scope", name="uq_seo_connections_scope"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_scope: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_CONNECTED,
                                        server_default=sql_text("'connected'"), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    token_hint: Mapped[str] = mapped_column(String(16), default="", server_default=sql_text("''"), nullable=False)
    # The OpenSEO project this workspace researches (``list_projects``/``create_project``).
    project_id: Mapped[str] = mapped_column(String(64), default="", server_default=sql_text("''"), nullable=False)
    domain: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                   nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)


class SeoAuditRun(Base):
    __tablename__ = "seo_audit_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(ForeignKey("seo_connections.id", ondelete="CASCADE"), index=True,
                                               nullable=False)
    owner_scope: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    external_audit_id: Mapped[str] = mapped_column(String(128), default="", server_default=sql_text("''"),
                                                    nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=AUDIT_QUEUED, server_default=sql_text("'queued'"),
                                        nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issues_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SeoKeywordResearch(Base):
    __tablename__ = "seo_keyword_research"
    __table_args__ = (UniqueConstraint("connection_id", "keyword", name="uq_seo_keyword_research_conn_kw"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(ForeignKey("seo_connections.id", ondelete="CASCADE"), index=True,
                                               nullable=False)
    owner_scope: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    seed: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpc_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intent: Mapped[str] = mapped_column(String(32), default="", server_default=sql_text("''"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default=sql_text("'USD'"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
                                                 nullable=False)


class SeoRankKeyword(Base):
    __tablename__ = "seo_rank_keywords"
    __table_args__ = (UniqueConstraint("connection_id", "keyword", "country", name="uq_seo_rank_keyword"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(ForeignKey("seo_connections.id", ondelete="CASCADE"), index=True,
                                               nullable=False)
    owner_scope: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(8), default="us", server_default=sql_text("'us'"), nullable=False)
    external_tracker_id: Mapped[str] = mapped_column(String(128), default="", server_default=sql_text("''"),
                                                      nullable=False)
    current_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_7d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SeoRankSnapshot(Base):
    __tablename__ = "seo_rank_snapshots"
    __table_args__ = (UniqueConstraint("rank_keyword_id", "day", name="uq_seo_rank_snapshot_day"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    rank_keyword_id: Mapped[str] = mapped_column(ForeignKey("seo_rank_keywords.id", ondelete="CASCADE"), index=True,
                                                 nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # YYYY-MM-DD
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


__all__ = [
    "AUDIT_COMPLETED", "AUDIT_FAILED", "AUDIT_QUEUED", "AUDIT_RUNNING", "STATUS_CONNECTED", "STATUS_REAUTH",
    "SeoAuditRun", "SeoConnection", "SeoKeywordResearch", "SeoRankKeyword", "SeoRankSnapshot",
]
