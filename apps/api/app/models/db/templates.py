"""Shot-template instantiation persistence (P6/P10).

The system genre templates are code-defined (``app.domains.templates.presets``);
this table records each **instantiation** — which template version a creator ran,
with what inputs, producing which reel — for reproducibility and genre analytics
(which formats convert). Custom user templates reuse the same ``ShotTemplateDef``
shape later; this is the durable audit + analytics substrate.

Registered on ``Base.metadata`` via ``migrations/env.py``. Nullability follows the
repo rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class TemplateInstance(Base):
    """A compiled instantiation of a genre template into a reel draft/job."""

    __tablename__ = "template_instances"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    template_slug: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    template_version: Mapped[str] = mapped_column(
        String(20), default="", server_default=text("''"), nullable=False
    )
    # The validated inputs used (opaque, grows without a migration).
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_s: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    # The reel job this instantiation produced (empty until dispatched).
    reel_job_id: Mapped[str] = mapped_column(
        String(64), default="", server_default=text("''"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
