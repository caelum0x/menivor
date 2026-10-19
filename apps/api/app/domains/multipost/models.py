"""Multi-account publishing tables (migration ``d2f4a6c8e0b5``).

* :class:`MultipostAccount` - one connected TikTok / Instagram / YouTube account.
  Many per provider per owner (unique on owner + provider + platform account id),
  optionally shared to a workspace. Tokens are only ever stored as
  :mod:`app.services.crypto_tokens` blobs.
* :class:`MultipostOAuthState` - single-use OAuth ``state`` rows (hash only) bound
  to the creator who started the connect, with the encrypted PKCE verifier.
* :class:`MultipostCampaign` - one "post these videos across these accounts" batch
  and the settings the creator chose for it (privacy, interaction toggles,
  commercial-content disclosure, AI-content label).
* :class:`MultipostPost` - one video to one account at one time: the publish queue.
* :class:`MultipostWebhookEvent` - provider webhook deliveries already applied
  (dedupe on a hash of the signed body).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces for the FKs)
from app.models.db.base import Base

TIKTOK = "tiktok"
INSTAGRAM = "instagram"
YOUTUBE = "youtube"
PROVIDERS: tuple[str, ...] = (TIKTOK, INSTAGRAM, YOUTUBE)

# Account statuses.
ACCOUNT_CONNECTED = "connected"
ACCOUNT_REAUTH = "needs_reauth"   # token revoked/expired beyond refresh: reconnect
ACCOUNT_PAUSED = "paused"         # owner paused posting to this account
ACCOUNT_STATUSES = frozenset({ACCOUNT_CONNECTED, ACCOUNT_REAUTH, ACCOUNT_PAUSED})

# Post statuses.
POST_SCHEDULED = "scheduled"
POST_PUBLISHING = "publishing"
POST_PROCESSING = "processing"
POST_PUBLISHED = "published"
POST_FAILED = "failed"
POST_CANCELED = "canceled"
POST_HELD = "held"                # the content gate held it for review
POST_STATUSES = frozenset({
    POST_SCHEDULED, POST_PUBLISHING, POST_PROCESSING, POST_PUBLISHED, POST_FAILED, POST_CANCELED, POST_HELD,
})
OPEN_POST_STATUSES = frozenset({POST_SCHEDULED, POST_PUBLISHING, POST_PROCESSING})
# Statuses that count against a platform's daily posting cap.
COUNTED_POST_STATUSES = frozenset({POST_PUBLISHING, POST_PROCESSING, POST_PUBLISHED})

CAMPAIGN_ACTIVE = "active"
CAMPAIGN_CANCELED = "canceled"


def _uuid() -> str:
    return uuid.uuid4().hex


class MultipostAccount(Base):
    __tablename__ = "multipost_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "external_account_id", name="uq_multipost_accounts_owner_account"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(200), nullable=False)
    handle: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    avatar_url: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ACCOUNT_CONNECTED, server_default=sql_text("'connected'"), nullable=False
    )
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    # Owner-tunable pacing. 0 = the provider default; values are clamped to the
    # provider's safe range (never above the platform cap, never below the gap floor).
    daily_cap: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    min_gap_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    # Local hours (0-23) posts may go out; [] = any hour.
    posting_hours: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default=sql_text("'UTC'"), nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MultipostOAuthState(Base):
    __tablename__ = "multipost_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    code_verifier_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MultipostCampaign(Base):
    __tablename__ = "multipost_campaigns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=CAMPAIGN_ACTIVE, server_default=sql_text("'active'"), nullable=False
    )
    # "spread": each video goes to one account (rotating); "every": each video to every account.
    mode: Mapped[str] = mapped_column(String(16), default="spread", server_default=sql_text("'spread'"),
                                      nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    hashtags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # public | friends | private - chosen explicitly by the creator (never defaulted).
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    tiktok_mode: Mapped[str] = mapped_column(String(8), default="direct", server_default=sql_text("'direct'"),
                                             nullable=False)
    allow_comments: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"),
                                                 nullable=False)
    allow_duet: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"),
                                             nullable=False)
    allow_stitch: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"),
                                               nullable=False)
    brand_content: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"),
                                                nullable=False)
    brand_organic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"),
                                                nullable=False)
    # Menivor videos are AI-generated: always labelled (TikTok is_aigc, YouTube
    # containsSyntheticMedia, Instagram caption line). Stored for the audit trail.
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"),
                                               nullable=False)
    job_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    account_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MultipostPost(Base):
    __tablename__ = "multipost_posts"
    __table_args__ = (
        Index("ix_multipost_posts_status_due", "status", "scheduled_at"),
        Index("ix_multipost_posts_account_status", "account_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("multipost_campaigns.id"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("multipost_accounts.id"), nullable=False)
    job_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=POST_SCHEDULED, server_default=sql_text("'scheduled'"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    # Provider handle for the in-flight publish: TikTok publish_id, Instagram
    # container id, YouTube video id. Indexed for webhook lookups.
    publish_ref: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"),
                                             index=True, nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"),
                                             nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    provider_status: Mapped[str] = mapped_column(String(64), default="", server_default=sql_text("''"),
                                                 nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MultipostWebhookEvent(Base):
    __tablename__ = "multipost_webhook_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the signed body
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    event: Mapped[str] = mapped_column(String(80), default="", server_default=sql_text("''"), nullable=False)
    publish_ref: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"),
                                             nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  nullable=False)
