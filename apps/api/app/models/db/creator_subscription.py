"""Personal monthly-plan subscription (web creators, Creem recurring products).

One row per user (``user_id`` UNIQUE): the plan the user is on, the Creem
subscription/customer ids used to correlate webhooks and open the customer
portal, and the bookkeeping for the current paid period's included reels
(``period_key`` = the granted period's end as unix seconds, the credits granted
for it and the ledger row id of that grant) so unused included reels can be
expired exactly once when the next period starts.

Separate from :class:`app.models.db.models.Subscription` (workspace plans) and
from RevenueCat (mobile store subscriptions). Imported by
:mod:`app.models.db.models` so the table registers on the shared metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class CreatorSubscription(Base):
    """A user's personal monthly plan (Creator / Pro / Agency)."""

    __tablename__ = "creator_subscriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # creator | pro | agency (app.services.billing.creator_plans).
    plan_key: Mapped[str] = mapped_column(String(40), nullable=False)
    # month | year.
    interval: Mapped[str] = mapped_column(
        String(10), default="month", server_default=text("'month'"), nullable=False
    )
    provider: Mapped[str] = mapped_column(
        String(40), default="creem", server_default=text("'creem'"), nullable=False
    )
    # Creem subscription id (sub_...), '' until the provider confirms.
    provider_ref: Mapped[str] = mapped_column(
        String(255), default="", server_default=text("''"), nullable=False, index=True
    )
    # Creem customer id (cust_...) for the customer portal.
    customer_ref: Mapped[str] = mapped_column(
        String(255), default="", server_default=text("''"), nullable=False
    )
    # active | trialing | past_due | canceled.
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default=text("'active'"), nullable=False
    )
    # True once the subscriber turned renewal off (access runs to period end).
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # The paid period whose included reels were granted (unix seconds of its end).
    period_key: Mapped[str] = mapped_column(
        String(40), default="", server_default=text("''"), nullable=False
    )
    period_credits: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    period_grant_ledger_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", name="uq_creator_subscriptions_user"),)


__all__ = ["CreatorSubscription"]
