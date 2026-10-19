"""Gateway (API-resale) persistence (P11) — provisioning keys + usage.

A reseller/customer holds a :class:`ProvisioningKey` with a midnight-UTC daily
spend cap; every charged call records a :class:`GatewayUsage` row so the pure
``gateway.provisioning.check_spend`` can gate against the current window's spend.
Only the SHA-256 hash of the key secret is stored (write-once, never returned).

Registered on ``Base.metadata`` via ``migrations/env.py``. Nullability follows the
repo rule: ``Mapped[str]`` default="" is NOT NULL; timestamps NOT NULL + default.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class ProvisioningKey(Base):
    """A reseller/customer API key with a daily (UTC) spend cap."""

    __tablename__ = "provisioning_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # SHA-256 hex of the plaintext secret (shown once at creation, never stored raw).
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="", server_default=text("''"), nullable=False)
    daily_cap_micros: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    # markup applied to base cost for this key's customer (basis points + floor).
    markup_bps: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    min_fee_micros: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    disabled: Mapped[bool] = mapped_column(
        String(1), default="0", server_default=text("'0'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


class GatewayUsage(Base):
    """One charged call against a provisioning key (drives the daily-cap sum)."""

    __tablename__ = "gateway_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key_id: Mapped[str] = mapped_column(ForeignKey("provisioning_keys.id"), index=True, nullable=False)
    charge_micros: Mapped[int] = mapped_column(Integer, nullable=False)
    base_cost_micros: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    model_key: Mapped[str] = mapped_column(String(80), default="", server_default=text("''"), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
