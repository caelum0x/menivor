"""Launch Kit tables (migration ``e5a7c9f1b3d4``, Menivor Growth phase 3: first-100-users tooling).

* :class:`LaunchPlatformStatus` - one (product, launch directory) a user is
  tracking, e.g. "Oxhan on Product Hunt": not_started / submitted / live,
  with the date it changed. The directory catalog itself
  (:mod:`app.domains.launch_kit.catalog`) is static reference data, not a
  table; this table is only the per-product tracking state.
* :class:`PlaybookStepStatus` - one (product, playbook step) a user is
  tracking from the 10-step distribution playbook (cold outreach, Reddit
  pain-point replies, UGC creators, competitor backlinks, build in public,
  ...). ``get_launch_checklist`` reads this to say done/pending per step.
* :class:`PainPointDraft` - one candidate Reddit thread + a drafted reply for
  a human to review and post by hand. Nothing here is ever auto-posted:
  ``status`` only ever moves between ``drafted`` / ``approved`` / ``dismissed``
  in this service, never ``posted`` (posting is a person, on Reddit, not us).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users)
from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class LaunchPlatformStatus(Base):
    __tablename__ = "launch_platform_status"
    __table_args__ = (
        UniqueConstraint("user_id", "product_name", "platform_id", name="uq_launch_platform_user_product_platform"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Catalog id from app.domains.launch_kit.catalog.PLATFORMS (e.g. "product_hunt").
    platform_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # not_started | submitted | live
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=sql_text("('not_started')"))
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("('')"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlaybookStepStatus(Base):
    __tablename__ = "launch_playbook_step_status"
    __table_args__ = (
        UniqueConstraint("user_id", "product_name", "step_key", name="uq_launch_step_user_product_step"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Key from app.domains.launch_kit.catalog.PLAYBOOK_STEPS (e.g. "reddit_pain_points").
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # pending | done
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=sql_text("('pending')"))
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("('')"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PainPointDraft(Base):
    __tablename__ = "launch_pain_point_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default=sql_text("('')"))
    query: Mapped[str] = mapped_column(String(300), nullable=False)
    subreddit: Mapped[str] = mapped_column(String(100), nullable=False, server_default=sql_text("('')"))
    thread_url: Mapped[str] = mapped_column(Text, nullable=False)
    thread_title: Mapped[str] = mapped_column(String(500), nullable=False, server_default=sql_text("('')"))
    snippet: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("('')"))
    upvotes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    age_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    draft_reply: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("('')"))
    # drafted | approved | dismissed -- never "posted"; a human posts on Reddit, not this service.
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=sql_text("('drafted')"))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ["LaunchPlatformStatus", "PainPointDraft", "PlaybookStepStatus"]
