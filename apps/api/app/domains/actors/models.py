"""AI actor table (migration ``b2d4f6a8c0e1``).

Only synthetic actors exist here. ``provenance`` records how the face was made
(generator, model, prompt, seed, image digest, ``synthetic: true``); ``consent``
records the attestation that no real person's likeness or voice is used. Built-in
presets live in code (:mod:`app.domains.actors.presets`) and are not rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class AiActor(Base):
    __tablename__ = "ai_actors"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    persona: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    look_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    voice_design_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    voice_id: Mapped[str] = mapped_column(String(80), nullable=False, server_default="")
    product_shot_template: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    face_image_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    consent: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ["AiActor"]
