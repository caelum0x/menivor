"""Capture job persistence (table created by migration ``a7d3e9c1f2b4``).

:class:`CaptureJob` - one capture of ``source_url``:

* ``source_kind``: ``website`` | ``native_game`` | ``app_store`` | ``play_store``
  (legacy rows may still read ``web_game``; web game capture was removed)
* ``status``: ``queued`` -> ``running`` -> ``succeeded`` | ``failed`` | ``canceled``
* ``output_video_key``: R2 key of the rendered promo video (empty until done)
* ``screenshots``: ``[{"key", "width", "height", "label"}]``
* ``meta`` (DB column ``metadata``): listing/page facts, e.g. title,
  developer, rating, icon, description, page title, palette.

Owner-scoped by ``user_id``. ``options`` carries viewport/device/duration.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base

KIND_WEBSITE = "website"
KIND_NATIVE_GAME = "native_game"
KIND_APP_STORE = "app_store"
KIND_PLAY_STORE = "play_store"
#: Kinds a new capture may use. Our games are native mobile apps only.
SOURCE_KINDS = frozenset({KIND_WEBSITE, KIND_NATIVE_GAME, KIND_APP_STORE, KIND_PLAY_STORE})
#: Removed kinds still readable on old rows (never accepted for new or retried captures).
KIND_WEB_GAME = "web_game"
LEGACY_KINDS = frozenset({KIND_WEB_GAME})

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"
CAPTURE_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELED})
TERMINAL_STATUSES = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELED})


def _uuid() -> str:
    return uuid.uuid4().hex


class CaptureJob(Base):
    __tablename__ = "capture_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_QUEUED, server_default=sql_text("'queued'"), index=True, nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_video_key: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    screenshots: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), default="", server_default=sql_text("''"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
