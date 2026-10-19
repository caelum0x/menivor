"""Motion-render persistence — a thin audit row per compiled/dispatched move.

Records which motion preset a creator ran, at what intensity, via which provider
(for model/hybrid), and the produced output ref — for reproducibility + history.
The opaque ``plan`` JSON carries the serialized :class:`MotionPlan` view so the
row grows without a migration. Registered on ``Base.metadata`` via the
router → repository import chain. Nullability follows the repo rule (every
additive column carries a ``server_default``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class MotionRender(Base):
    """A recorded motion-preset compilation/dispatch for one creator."""

    __tablename__ = "motion_renders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    preset_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    motion_class: Mapped[str] = mapped_column(
        String(16), default="filter", server_default=text("'filter'"), nullable=False
    )
    intensity: Mapped[int] = mapped_column(
        Integer, default=50, server_default=text("50"), nullable=False
    )
    provider_key: Mapped[str] = mapped_column(
        String(64), default="", server_default=text("''"), nullable=False
    )
    provider_run_id: Mapped[str] = mapped_column(
        String(128), default="", server_default=text("''"), nullable=False
    )
    output_ref: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"), nullable=False
    )
    # Opaque serialized MotionPlan view (grows without a migration).
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
