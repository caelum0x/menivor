"""Design Studio persistence (tables created by migration ``a7d3e9c1f2b4``).

* :class:`DesignDoc` - one editable design owned by a user (optionally shared
  to a workspace): its size preset, canvas JSON, the brand kit it was filled
  from, and the storage key of the last PNG export.
* :class:`DesignTemplate` - a JSON layout a design can start from. System
  templates have ``user_id`` NULL; creators can save their own.

``canvas_json`` shape (owned by the editor, stored opaque)::

    {"version": 1, "pages": [{"background": "#ffffff", "layers": [
        {"id": "...", "type": "text|image|rect|ellipse|line", "x": 0, "y": 0,
         "width": 0, "height": 0, "rotation": 0, "props": {...}}]}]}

Every read and write must be owner-scoped by ``user_id`` (or workspace
membership when ``workspace_id`` is set).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces/user_presets)
from app.models.db.base import Base

# Size presets -> (width, height) in pixels. "carousel" pages are square.
SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "square": (1080, 1080),
    "portrait": (1080, 1350),
    "story": (1080, 1920),
    "landscape": (1200, 628),
    "carousel": (1080, 1080),
    "banner": (1500, 500),
    # App Store 6.7" iPhone screenshot (portrait); Play accepts the same ratio.
    "app_store": (1290, 2796),
}

STATUS_DRAFT = "draft"
STATUS_EXPORTED = "exported"
STATUS_SCHEDULED = "scheduled"
DESIGN_STATUSES = frozenset({STATUS_DRAFT, STATUS_EXPORTED, STATUS_SCHEDULED})

# Hard cap on stored canvas pages (carousel slides).
MAX_PAGES = 10


def _uuid() -> str:
    return uuid.uuid4().hex


class DesignDoc(Base):
    __tablename__ = "design_docs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    size_preset: Mapped[str] = mapped_column(
        String(20), default="square", server_default=sql_text("'square'"), nullable=False
    )
    width: Mapped[int] = mapped_column(Integer, default=1080, server_default=sql_text("1080"), nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=1080, server_default=sql_text("1080"), nullable=False)
    canvas_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("design_templates.id", ondelete="SET NULL"), nullable=True
    )
    brand_kit_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_presets.id", ondelete="SET NULL"), nullable=True
    )
    prompt: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_DRAFT, server_default=sql_text("'draft'"), nullable=False
    )
    thumb_key: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    # R2 object keys of the last export, one per page (carousel = many).
    exported_asset_key: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    exported_keys: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # True once an AI-generated image was placed (the only metered path).
    used_ai_image: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sql_text("false"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DesignTemplate(Base):
    __tablename__ = "design_templates"
    __table_args__ = (UniqueConstraint("slug", name="uq_design_templates_slug"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # NULL for built-in system templates; set for a creator's saved template.
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    size_preset: Mapped[str] = mapped_column(
        String(20), default="square", server_default=sql_text("'square'"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(40), default="post", server_default=sql_text("'post'"), nullable=False)
    layout_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
