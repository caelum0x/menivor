"""Per-user Buffer and Typefully API keys (migration ``f8b0d2e4a6c1``).

The raw key is write-only. ``encrypted_secret`` is a Fernet blob from
:mod:`app.services.crypto_tokens` (``SOCIAL_TOKEN_KEY``). ``key_hint`` is a
non-secret suffix so the owner can tell which key they saved.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users)
from app.models.db.base import Base

PROVIDERS = ("buffer", "typefully")


def _uuid() -> str:
    return uuid.uuid4().hex


class SchedulerConnection(Base):
    __tablename__ = "scheduler_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_scheduler_connection_user_provider"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # buffer | typefully
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    # Non-secret display hint, e.g. "••••abcd". Never the key.
    key_hint: Mapped[str] = mapped_column(String(16), nullable=False, server_default=sql_text("('')"))
    # Fernet ciphertext. Never returned by an endpoint.
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
