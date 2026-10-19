"""Creator-as-merchant commerce (MV13) and ads (MV14) tables; migration a7d9f1b3c5e8.

Nothing here holds money: an offer is a product on the **creator's own**
payment account (through Mint seller-own payments), and an entitlement is the
right to watch that the creator's processor granted. No amount, balance,
payout or buyer payment detail is stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base

KIND_SVOD = "svod"
KIND_TVOD = "tvod"
KIND_RENTAL = "rental"
OFFER_KINDS = (KIND_SVOD, KIND_TVOD, KIND_RENTAL)
ACTIVE, REVOKED = "active", "revoked"


def _id() -> str:
    return uuid.uuid4().hex


class OttCoupon(Base):
    """A code reference for a discount that lives on the creator's own processor.

    Wave Q QM1.3. Mint's seller contract (Wave P 5.5) has no discount type, so
    the amount, percent and currency stay on the processor. This row stores
    only the code the checkout may name, plus when the creator said it ends.

    ``processor_discount_id`` (migration e3a5c7d9f1b2) is the processor's id for
    the discount, so stopping ends it there and switching it back on reuses it
    (Dodo refuses a second discount with the same code). NULL on rows made
    before it existed.
    """

    __tablename__ = "ott_coupons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    processor_discount_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("channel_id", "code", name="uq_ott_coupons_channel_code"),)


class OttOffer(Base):
    """What a channel sells: a subscription (SVOD), a purchase (TVOD) or a rental of one title."""

    __tablename__ = "ott_offers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    title_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    interval: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    rental_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("channel_id", "sku", name="uq_ott_offers_channel_sku"),)


class OttEntitlement(Base):
    """A viewer's right to watch, granted or revoked by the creator's processor (through Mint)."""

    __tablename__ = "ott_entitlements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    viewer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    offer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    title_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=ACTIVE)
    granted_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # The offer's list price and currency when the grant landed, so a later price
    # change never rewrites past gross sales. A label, not funds: the buyer paid the
    # creator's own processor and nothing here is held or forwarded by Menivor.
    list_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    list_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    __table_args__ = (
        UniqueConstraint("granted_event_id", name="uq_ott_entitlements_granted_event"),
        Index("ix_ott_entitlements_viewer", "viewer_id", "status"),
    )


class OttMintEvent(Base):
    """Every Mint entitlement event applied once (its ``ent_...`` id)."""

    __tablename__ = "ott_mint_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OttAd(Base):
    """A house ad (ours, ``channel_id`` NULL) or a sponsor slot the creator sold, made from a packaged title."""

    __tablename__ = "ott_ads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # house | sponsor
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sponsor: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title_id: Mapped[str] = mapped_column(String(32), nullable=False)
    click_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skips: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OttAdEvent(Base):
    """One counted ad event per (play, ad, event) (Wave Q QM1.0, P-M12); migration d1a3c5e7f9b2.

    A tracking URL is signed for one play and expires in 15 minutes, so a row
    is only needed while its URL can still verify; the daily sweep removes the
    rest.
    """

    __tablename__ = "ott_ad_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    ad_id: Mapped[str] = mapped_column(String(32), nullable=False)
    play_id: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("play_id", "ad_id", "event", name="uq_ott_ad_events_play_ad_event"),
        Index("ix_ott_ad_events_created", "created_at"),
    )


class OttAdSettings(Base):
    """Per-channel ad rules: ads on free titles (default on), on paid tiers (default off), house ads."""

    __tablename__ = "ott_ad_settings"

    channel_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ads_on_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ads_on_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    house_ads: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


__all__ = ["ACTIVE", "KIND_RENTAL", "KIND_SVOD", "KIND_TVOD", "OFFER_KINDS", "OttAd", "OttAdEvent", "OttAdSettings",
           "OttCoupon", "OttEntitlement", "OttMintEvent", "OttOffer", "REVOKED"]
