"""Multi-account publishing: accounts, OAuth states, campaigns, publish queue, webhook dedupe

``multipost_accounts``, ``multipost_oauth_states``, ``multipost_campaigns``,
``multipost_posts``, ``multipost_webhook_events``. Additive and idempotent.
Tokens are stored only as encrypted blobs.

Merge note: branched from ``c9f1b3d5e7a0``; Wave Q landed first, so this
revision now follows Wave Q's head ``b5e7a9c1d3f7`` and the graph keeps
exactly one head.

Revision ID: d2f4a6c8e0b5
Revises: b5e7a9c1d3f7
Create Date: 2026-10-05 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd2f4a6c8e0b5'
down_revision: Union[str, None] = 'b5e7a9c1d3f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _now():
    return sa.func.now()


def upgrade() -> None:
    tables = _tables()
    if "multipost_accounts" not in tables:
        op.create_table(
            "multipost_accounts",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("workspace_id", sa.String(32), sa.ForeignKey("workspaces.id"), nullable=True),
            sa.Column("provider", sa.String(16), nullable=False),
            sa.Column("external_account_id", sa.String(200), nullable=False),
            sa.Column("handle", sa.String(200), nullable=False, server_default=""),
            sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("avatar_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="connected"),
            sa.Column("access_token_enc", sa.Text(), nullable=False),
            sa.Column("refresh_token_enc", sa.Text(), nullable=True),
            sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
            sa.Column("daily_cap", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("min_gap_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("posting_hours", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.UniqueConstraint("user_id", "provider", "external_account_id",
                                name="uq_multipost_accounts_owner_account"),
        )
        op.create_index("ix_multipost_accounts_user_id", "multipost_accounts", ["user_id"])
        op.create_index("ix_multipost_accounts_workspace_id", "multipost_accounts", ["workspace_id"])
    if "multipost_oauth_states" not in tables:
        op.create_table(
            "multipost_oauth_states",
            sa.Column("state_hash", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("provider", sa.String(16), nullable=False),
            sa.Column("workspace_id", sa.String(32), nullable=True),
            sa.Column("code_verifier_enc", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        )
        op.create_index("ix_multipost_oauth_states_user_id", "multipost_oauth_states", ["user_id"])
        op.create_index("ix_multipost_oauth_states_expires_at", "multipost_oauth_states", ["expires_at"])
    if "multipost_campaigns" not in tables:
        op.create_table(
            "multipost_campaigns",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("mode", sa.String(16), nullable=False, server_default="spread"),
            sa.Column("caption", sa.Text(), nullable=False, server_default=""),
            sa.Column("hashtags", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("visibility", sa.String(16), nullable=False),
            sa.Column("tiktok_mode", sa.String(8), nullable=False, server_default="direct"),
            sa.Column("allow_comments", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("allow_duet", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("allow_stitch", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("brand_content", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("brand_organic", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("job_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("account_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        )
        op.create_index("ix_multipost_campaigns_user_id", "multipost_campaigns", ["user_id"])
    if "multipost_posts" not in tables:
        op.create_table(
            "multipost_posts",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("campaign_id", sa.String(32), sa.ForeignKey("multipost_campaigns.id"), nullable=False),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("account_id", sa.String(32), sa.ForeignKey("multipost_accounts.id"), nullable=False),
            sa.Column("job_id", sa.String(32), nullable=False),
            sa.Column("provider", sa.String(16), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title", sa.String(300), nullable=False, server_default=""),
            sa.Column("caption", sa.Text(), nullable=False, server_default=""),
            sa.Column("publish_ref", sa.String(300), nullable=False, server_default=""),
            sa.Column("external_id", sa.String(300), nullable=False, server_default=""),
            sa.Column("url", sa.Text(), nullable=False, server_default=""),
            sa.Column("provider_status", sa.String(64), nullable=False, server_default=""),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        )
        op.create_index("ix_multipost_posts_campaign_id", "multipost_posts", ["campaign_id"])
        op.create_index("ix_multipost_posts_user_id", "multipost_posts", ["user_id"])
        op.create_index("ix_multipost_posts_job_id", "multipost_posts", ["job_id"])
        op.create_index("ix_multipost_posts_next_attempt_at", "multipost_posts", ["next_attempt_at"])
        op.create_index("ix_multipost_posts_publish_ref", "multipost_posts", ["publish_ref"])
        op.create_index("ix_multipost_posts_status_due", "multipost_posts", ["status", "scheduled_at"])
        op.create_index("ix_multipost_posts_account_status", "multipost_posts", ["account_id", "status"])
    if "multipost_webhook_events" not in tables:
        op.create_table(
            "multipost_webhook_events",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("provider", sa.String(16), nullable=False),
            sa.Column("event", sa.String(80), nullable=False, server_default=""),
            sa.Column("publish_ref", sa.String(300), nullable=False, server_default=""),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        )


def downgrade() -> None:
    tables = _tables()
    for name in ("multipost_webhook_events", "multipost_posts", "multipost_campaigns",
                 "multipost_oauth_states", "multipost_accounts"):
        if name in tables:
            op.drop_table(name)
