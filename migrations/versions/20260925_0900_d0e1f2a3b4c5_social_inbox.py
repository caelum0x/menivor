"""social inbox: tracked posts + comment/DM threads for Menivor-published posts

Additive: two new tables.

* ``social_inbox_posts`` - one row per (owner, platform, platform post id) that
  Menivor published natively. Holds the poll schedule, the inbox availability
  state for that post (ok / not connected / missing permission / not offered by
  the platform) and the engagement counts we actually observed.
* ``social_inbox_threads`` - one row per top-level comment (or DM conversation)
  pulled from the platform, with a bounded message history, reply state and the
  platform id of any reply sent from Menivor.

New tables only; nothing existing is altered.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-25 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "social_inbox_posts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("url", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("title", sa.String(length=300), server_default=sa.text("''"), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        # ok | not_connected | missing_permission | not_offered | error
        sa.Column("inbox_state", sa.String(length=24), server_default=sa.text("'ok'"), nullable=False),
        sa.Column("state_note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("platform_comment_count", sa.Integer(), nullable=True),
        sa.Column("platform_like_count", sa.Integer(), nullable=True),
        sa.Column("platform_view_count", sa.Integer(), nullable=True),
        sa.Column("synced_comment_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("needs_reply_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("replied_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("poll_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "platform", "external_id", name="uq_social_inbox_posts_owner_post"),
    )
    op.create_index(op.f("ix_social_inbox_posts_user_id"), "social_inbox_posts", ["user_id"], unique=False)
    op.create_index(op.f("ix_social_inbox_posts_job_id"), "social_inbox_posts", ["job_id"], unique=False)
    op.create_index(op.f("ix_social_inbox_posts_next_poll_at"), "social_inbox_posts", ["next_poll_at"], unique=False)

    op.create_table(
        "social_inbox_threads",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("post_id", sa.String(length=32), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        # comment | dm
        sa.Column("kind", sa.String(length=12), server_default=sa.text("'comment'"), nullable=False),
        sa.Column("external_thread_id", sa.String(length=160), nullable=False),
        sa.Column("author_name", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("author_external_id", sa.String(length=128), server_default=sa.text("''"), nullable=False),
        sa.Column("text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("permalink", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("like_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("messages", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        # needs_reply | replied | done
        sa.Column("status", sa.String(length=16), server_default=sa.text("'needs_reply'"), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("reply_external_id", sa.String(length=160), server_default=sa.text("''"), nullable=False),
        # api | manual | ''
        sa.Column("reply_via", sa.String(length=12), server_default=sa.text("''"), nullable=False),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["social_inbox_posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "platform", "kind", "external_thread_id", name="uq_social_inbox_threads_owner_thread"
        ),
    )
    op.create_index(op.f("ix_social_inbox_threads_user_id"), "social_inbox_threads", ["user_id"], unique=False)
    op.create_index(op.f("ix_social_inbox_threads_post_id"), "social_inbox_threads", ["post_id"], unique=False)
    op.create_index(
        "ix_social_inbox_threads_owner_status_time",
        "social_inbox_threads",
        ["user_id", "status", "last_message_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_social_inbox_threads_owner_status_time", table_name="social_inbox_threads")
    op.drop_index(op.f("ix_social_inbox_threads_post_id"), table_name="social_inbox_threads")
    op.drop_index(op.f("ix_social_inbox_threads_user_id"), table_name="social_inbox_threads")
    op.drop_table("social_inbox_threads")
    op.drop_index(op.f("ix_social_inbox_posts_next_poll_at"), table_name="social_inbox_posts")
    op.drop_index(op.f("ix_social_inbox_posts_job_id"), table_name="social_inbox_posts")
    op.drop_index(op.f("ix_social_inbox_posts_user_id"), table_name="social_inbox_posts")
    op.drop_table("social_inbox_posts")
