"""extended publish platforms + engagement autopilot

Additive: six new tables, nothing existing is altered.

Publishing (Facebook Pages, LinkedIn, X, Threads, Pinterest, Bluesky):

* ``publishing_platform_connections`` - one connected account per (owner,
  platform): encrypted tokens, chosen posting target, available targets.
* ``publishing_oauth_states`` - single-use OAuth states bound to the creator
  (sha256 of the state; PKCE verifier encrypted).
* ``publishing_platform_posts`` - scheduled / in-progress / finished posts of a
  rendered reel to one platform.

Social inbox engagement autopilot:

* ``social_engagement_settings`` - per-platform autopilot rules + daily cap.
* ``social_engagement_actions`` - approval queue + audit log.
* ``social_engagement_leads`` - buying-intent conversations routed to Leads.

Revision ID: 6e135be697a8
Revises: d0e1f2a3b4c5
Create Date: 2026-09-25 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e135be697a8'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "publishing_platform_connections",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'connected'"), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("external_account_id", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("account_name", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("target_kind", sa.String(length=20), server_default=sa.text("'self'"), nullable=False),
        sa.Column("target_id", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("target_name", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("target_token_enc", sa.Text(), nullable=True),
        sa.Column("targets", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("status_note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "platform", name="uq_publishing_platform_connections_owner"),
    )
    op.create_index(op.f("ix_publishing_platform_connections_user_id"), "publishing_platform_connections",
                    ["user_id"], unique=False)

    op.create_table(
        "publishing_oauth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("code_verifier_enc", sa.Text(), nullable=True),
        sa.Column("scopes", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_index(op.f("ix_publishing_oauth_states_user_id"), "publishing_oauth_states", ["user_id"], unique=False)
    op.create_index(op.f("ix_publishing_oauth_states_expires_at"), "publishing_oauth_states", ["expires_at"],
                    unique=False)

    op.create_table(
        "publishing_platform_posts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'scheduled'"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("title", sa.String(length=300), server_default=sa.text("''"), nullable=False),
        sa.Column("text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("hashtags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("target_id", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("progress", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("external_id", sa.String(length=300), server_default=sa.text("''"), nullable=False),
        sa.Column("url", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("error", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_publishing_platform_posts_user_id"), "publishing_platform_posts", ["user_id"],
                    unique=False)
    op.create_index(op.f("ix_publishing_platform_posts_job_id"), "publishing_platform_posts", ["job_id"], unique=False)
    op.create_index(op.f("ix_publishing_platform_posts_next_attempt_at"), "publishing_platform_posts",
                    ["next_attempt_at"], unique=False)

    op.create_table(
        "social_engagement_settings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_like", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("reply_mode", sa.String(length=12), server_default=sa.text("'approve'"), nullable=False),
        sa.Column("reply_to_questions", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("hide_spam", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("hide_abuse", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("route_leads", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("daily_cap", sa.Integer(), server_default=sa.text("50"), nullable=False),
        sa.Column("blocked_words", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "platform", name="uq_social_engagement_settings_owner"),
    )
    op.create_index(op.f("ix_social_engagement_settings_user_id"), "social_engagement_settings", ["user_id"],
                    unique=False)

    op.create_table(
        "social_engagement_actions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("thread_id", sa.String(length=32), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("actor", sa.String(length=12), server_default=sa.text("'autopilot'"), nullable=False),
        sa.Column("message_key", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("label", sa.String(length=20), server_default=sa.text("''"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("text_source", sa.String(length=12), server_default=sa.text("''"), nullable=False),
        sa.Column("excerpt", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("author_name", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("external_id", sa.String(length=300), server_default=sa.text("''"), nullable=False),
        sa.Column("error", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("detail", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["social_inbox_threads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "thread_id", "kind", "message_key", name="uq_social_engagement_actions_once"),
    )
    op.create_index(op.f("ix_social_engagement_actions_user_id"), "social_engagement_actions", ["user_id"],
                    unique=False)
    op.create_index(op.f("ix_social_engagement_actions_thread_id"), "social_engagement_actions", ["thread_id"],
                    unique=False)
    op.create_index(op.f("ix_social_engagement_actions_created_at"), "social_engagement_actions", ["created_at"],
                    unique=False)
    op.create_index("ix_social_engagement_actions_owner_status", "social_engagement_actions",
                    ["user_id", "status", "created_at"], unique=False)

    op.create_table(
        "social_engagement_leads",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("thread_id", sa.String(length=32), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=12), server_default=sa.text("'dm'"), nullable=False),
        sa.Column("author_name", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("author_external_id", sa.String(length=128), server_default=sa.text("''"), nullable=False),
        sa.Column("excerpt", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("signals", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("score", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=12), server_default=sa.text("'new'"), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("permalink", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["social_inbox_threads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "thread_id", name="uq_social_engagement_leads_thread"),
    )
    op.create_index(op.f("ix_social_engagement_leads_user_id"), "social_engagement_leads", ["user_id"], unique=False)
    op.create_index(op.f("ix_social_engagement_leads_thread_id"), "social_engagement_leads", ["thread_id"],
                    unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_social_engagement_leads_thread_id"), table_name="social_engagement_leads")
    op.drop_index(op.f("ix_social_engagement_leads_user_id"), table_name="social_engagement_leads")
    op.drop_table("social_engagement_leads")
    op.drop_index("ix_social_engagement_actions_owner_status", table_name="social_engagement_actions")
    op.drop_index(op.f("ix_social_engagement_actions_created_at"), table_name="social_engagement_actions")
    op.drop_index(op.f("ix_social_engagement_actions_thread_id"), table_name="social_engagement_actions")
    op.drop_index(op.f("ix_social_engagement_actions_user_id"), table_name="social_engagement_actions")
    op.drop_table("social_engagement_actions")
    op.drop_index(op.f("ix_social_engagement_settings_user_id"), table_name="social_engagement_settings")
    op.drop_table("social_engagement_settings")
    op.drop_index(op.f("ix_publishing_platform_posts_next_attempt_at"), table_name="publishing_platform_posts")
    op.drop_index(op.f("ix_publishing_platform_posts_job_id"), table_name="publishing_platform_posts")
    op.drop_index(op.f("ix_publishing_platform_posts_user_id"), table_name="publishing_platform_posts")
    op.drop_table("publishing_platform_posts")
    op.drop_index(op.f("ix_publishing_oauth_states_expires_at"), table_name="publishing_oauth_states")
    op.drop_index(op.f("ix_publishing_oauth_states_user_id"), table_name="publishing_oauth_states")
    op.drop_table("publishing_oauth_states")
    op.drop_index(op.f("ix_publishing_platform_connections_user_id"), table_name="publishing_platform_connections")
    op.drop_table("publishing_platform_connections")
