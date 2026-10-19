"""Automatic performance tracking: ``tracked_posts`` + ``post_snapshots``

``tracked_posts`` holds one row per (creator, platform, post id) - reels
Menivor published through a connected account and posts the creator pasted a
link to - with the refresh schedule and the latest numbers. ``post_snapshots``
is the append-only time series of every read. Purely additive.

Revision ID: a1c7e3f9b5d2
Revises: e5f9b3c7d1a2
Create Date: 2026-09-27 04:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1c7e3f9b5d2'
down_revision: Union[str, None] = 'e5f9b3c7d1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tracked_posts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=300), nullable=False),
        sa.Column("url", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("title", sa.String(length=300), server_default=sa.text("''"), nullable=False),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'published'"), nullable=False),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'waiting'"), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("saves", sa.Integer(), nullable=True),
        sa.Column("avg_watch_frac", sa.Float(), nullable=True),
        sa.Column("failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "platform", "external_id", name="uq_tracked_posts_owner_post"),
    )
    op.create_index("ix_tracked_posts_user_id", "tracked_posts", ["user_id"], unique=False)
    op.create_index("ix_tracked_posts_job_id", "tracked_posts", ["job_id"], unique=False)
    op.create_index("ix_tracked_posts_next_check_at", "tracked_posts", ["next_check_at"], unique=False)
    op.create_table(
        "post_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("origin", sa.String(length=16), server_default=sa.text("'platform'"), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("saves", sa.Integer(), nullable=True),
        sa.Column("avg_watch_frac", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["post_id"], ["tracked_posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_post_snapshots_user_id", "post_snapshots", ["user_id"], unique=False)
    op.create_index("ix_post_snapshots_post_captured", "post_snapshots", ["post_id", "captured_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_post_snapshots_post_captured", table_name="post_snapshots")
    op.drop_index("ix_post_snapshots_user_id", table_name="post_snapshots")
    op.drop_table("post_snapshots")
    op.drop_index("ix_tracked_posts_next_check_at", table_name="tracked_posts")
    op.drop_index("ix_tracked_posts_job_id", table_name="tracked_posts")
    op.drop_index("ix_tracked_posts_user_id", table_name="tracked_posts")
    op.drop_table("tracked_posts")
