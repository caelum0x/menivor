"""Integrations persistence (tables created by migration ``f4b6d8a0c2e5``).

* :class:`IntegrationConnection` - one connected provider per scope (a workspace,
  or one user without a workspace): ad platforms, Slack, store credentials.
  Tokens and keys are stored only as :mod:`app.services.crypto_tokens` blobs.
* :class:`IntegrationOAuthState` - single-use CSRF state for a connect, stored as
  a SHA-256 hash, bound to the user who started it, 15-minute lifetime.
* :class:`IntegrationAdAccount` - an ad account the connection can read.
* :class:`IntegrationAdAccountBrand` - which Brand spaces (brand kits) see an account.
* :class:`IntegrationAdMetric` - the common daily per-creative metrics table every
  provider is normalized into (money in account-currency minor units).
* :class:`IntegrationOnboardingGrant` - one row per (scope, step) so each
  onboarding credit is granted at most once.

``owner_scope`` is ``ws:<workspace id>`` or ``user:<user id>``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base

KIND_ADS = "ads"
KIND_SLACK = "slack"
KIND_PRODUCT_SOURCE = "product_source"
KINDS = frozenset({KIND_ADS, KIND_SLACK, KIND_PRODUCT_SOURCE})

STATUS_CONNECTED = "connected"
STATUS_REAUTH = "needs_reauth"
CONNECTION_STATUSES = frozenset({STATUS_CONNECTED, STATUS_REAUTH})


def _uuid() -> str:
    return uuid.uuid4().hex


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("owner_scope", "provider", name="uq_integration_connections_scope_provider"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_scope: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    # Who connected it (acts for Slack-originated decisions).
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_CONNECTED,
                                        server_default=sql_text("'connected'"), nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    token_hint: Mapped[str] = mapped_column(String(16), default="", server_default=sql_text("''"), nullable=False)
    # Provider-side id: Slack team id, Shopify shop domain, OpenAI ad account id.
    external_id: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"),
                                             index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    # Non-secret settings (Slack approvers, Medusa base URL, ...).
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)


class IntegrationOAuthState(Base):
    __tablename__ = "integration_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_scope: Mapped[str] = mapped_column(String(48), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class IntegrationAdAccount(Base):
    __tablename__ = "integration_ad_accounts"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_integration_ad_accounts_conn_ext"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id", ondelete="CASCADE"),
                                               index=True, nullable=False)
    owner_scope: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default=sql_text("'USD'"), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="", server_default=sql_text("''"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default=sql_text("'active'"),
                                        nullable=False)
    last_pulled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IntegrationAdAccountBrand(Base):
    __tablename__ = "integration_ad_account_brands"
    __table_args__ = (UniqueConstraint("ad_account_id", "brand_space_id", name="uq_integration_ad_account_brand"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    ad_account_id: Mapped[str] = mapped_column(ForeignKey("integration_ad_accounts.id", ondelete="CASCADE"),
                                               index=True, nullable=False)
    # A Brand space is a brand kit (``user_presets.id``).
    brand_space_id: Mapped[str] = mapped_column(ForeignKey("user_presets.id", ondelete="CASCADE"), index=True,
                                                nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IntegrationAdMetric(Base):
    __tablename__ = "integration_ad_metrics"
    __table_args__ = (UniqueConstraint("ad_account_id", "day", "entity_id", name="uq_integration_ad_metrics_row"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    ad_account_id: Mapped[str] = mapped_column(ForeignKey("integration_ad_accounts.id", ondelete="CASCADE"),
                                               index=True, nullable=False)
    owner_scope: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # YYYY-MM-DD
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(128), default="", server_default=sql_text("''"), nullable=False)
    group_id: Mapped[str] = mapped_column(String(128), default="", server_default=sql_text("''"), nullable=False)
    spend_minor: Mapped[int] = mapped_column(BigInteger, default=0, server_default=sql_text("0"), nullable=False)
    impressions: Mapped[int] = mapped_column(BigInteger, default=0, server_default=sql_text("0"), nullable=False)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0, server_default=sql_text("0"), nullable=False)
    # Unique people reached that day (Meta reports it; others leave it NULL). Added by ``b2d4f6a8c0e1``.
    reach: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    conversions: Mapped[float | None] = mapped_column(Float, nullable=True)
    conversion_value_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default=sql_text("'USD'"), nullable=False)
    pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                onupdate=func.now(), nullable=False)


class IntegrationOnboardingGrant(Base):
    __tablename__ = "integration_onboarding_grants"
    __table_args__ = (UniqueConstraint("owner_scope", "step", name="uq_integration_onboarding_scope_step"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_scope: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


__all__ = [
    "CONNECTION_STATUSES", "IntegrationAdAccount", "IntegrationAdAccountBrand", "IntegrationAdMetric",
    "IntegrationConnection", "IntegrationOAuthState", "IntegrationOnboardingGrant", "KINDS", "KIND_ADS",
    "KIND_PRODUCT_SOURCE", "KIND_SLACK", "STATUS_CONNECTED", "STATUS_REAUTH",
]
