"""Persistence for the extended publish platforms (tables from migration ``6e135be697a8``).

* :class:`PlatformConnection` - one connected account per (owner, platform):
  encrypted credentials, the chosen posting target (Page / company / board)
  and the targets the account can post to.
* :class:`PlatformOAuthState` - single-use OAuth ``state`` rows bound to the
  creator who started the connect (with the PKCE verifier, encrypted).
* :class:`PlatformPost` - one post of a rendered reel to one platform: its
  schedule, lifecycle status, multi-step progress and the resulting post id/URL.

Tokens are only ever stored as :mod:`app.services.crypto_tokens` blobs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users for the FKs)
from app.models.db.base import Base

# Connection statuses.
CONN_CONNECTED = "connected"
CONN_NEEDS_TARGET = "needs_target"      # connected, but no Page/board chosen yet
CONN_REAUTH = "needs_reauth"            # token expired/revoked; reconnect
CONNECTION_STATUSES = frozenset({CONN_CONNECTED, CONN_NEEDS_TARGET, CONN_REAUTH})

# Post statuses.
POST_SCHEDULED = "scheduled"
POST_PUBLISHING = "publishing"
POST_PROCESSING = "processing"
POST_PUBLISHED = "published"
POST_FAILED = "failed"
POST_CANCELED = "canceled"
POST_HELD = "held"                      # the content gate held it for review
POST_STATUSES = frozenset({
    POST_SCHEDULED, POST_PUBLISHING, POST_PROCESSING, POST_PUBLISHED, POST_FAILED, POST_CANCELED, POST_HELD,
})
ACTIVE_POST_STATUSES = frozenset({POST_SCHEDULED, POST_PUBLISHING, POST_PROCESSING})


def _uuid() -> str:
    return uuid.uuid4().hex


class PlatformConnection(Base):
    __tablename__ = "publishing_platform_connections"
    __table_args__ = (UniqueConstraint("user_id", "platform", name="uq_publishing_platform_connections_owner"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=CONN_CONNECTED, server_default=sql_text("'connected'"),
                                        nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"),
                                                     nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(20), default="self", server_default=sql_text("'self'"),
                                             nullable=False)
    target_id: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    target_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    # Page access token (Facebook) - encrypted; empty for other platforms.
    target_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"id","name","kind"}] the account can post to (no tokens).
    targets: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Non-secret platform detail (e.g. Bluesky PDS host, LinkedIn member urn).
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status_note: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlatformOAuthState(Base):
    __tablename__ = "publishing_oauth_states"

    # sha256 hex of the opaque state; the raw state is never stored.
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    code_verifier_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlatformPost(Base):
    __tablename__ = "publishing_platform_posts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    job_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=POST_SCHEDULED, server_default=sql_text("'scheduled'"),
                                        nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    hashtags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_id: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    # Multi-step publish continuation (container id, media id, upload phase...). No tokens.
    progress: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), default="", server_default=sql_text("''"), nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
