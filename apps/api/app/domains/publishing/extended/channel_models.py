"""Credential-based social channels (table created by migration ``a7d3e9c1f2b4``).

:class:`SocialChannelCredential` - one connected Telegram / Discord / Mastodon
posting target. These platforms do not use the OAuth connect flow in
:mod:`.models`; the user pastes a credential instead:

* ``telegram``: bot token (encrypted) + ``target_id`` = channel/chat id where
  the bot is an admin. ``meta.update_offset`` tracks ``getUpdates`` for the inbox.
* ``discord``: channel webhook URL (encrypted); ``target_id`` = webhook id.
* ``mastodon``: access token (encrypted) + ``instance_url``; ``target_id`` =
  account id.

Several channels per kind are allowed (e.g. two Telegram channels). A row is
personal when ``workspace_id`` is NULL, else shared to that workspace.
Secrets are only ever stored as :mod:`app.services.crypto_tokens` blobs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base

KIND_TELEGRAM = "telegram"
KIND_DISCORD = "discord"
KIND_MASTODON = "mastodon"
CHANNEL_KINDS = frozenset({KIND_TELEGRAM, KIND_DISCORD, KIND_MASTODON})

STATUS_CONNECTED = "connected"
STATUS_NEEDS_REAUTH = "needs_reauth"
STATUS_ERROR = "error"
CHANNEL_STATUSES = frozenset({STATUS_CONNECTED, STATUS_NEEDS_REAUTH, STATUS_ERROR})


def _uuid() -> str:
    return uuid.uuid4().hex


class SocialChannelCredential(Base):
    __tablename__ = "social_channel_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "target_id", name="uq_social_channel_credentials_owner_target"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_CONNECTED, server_default=sql_text("'connected'"), nullable=False
    )
    credentials_enc: Mapped[str] = mapped_column(Text, nullable=False)
    instance_url: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    target_id: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    target_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
