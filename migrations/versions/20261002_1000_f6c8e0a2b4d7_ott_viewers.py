"""OTT viewers and usage: ``ott_viewers``, ``ott_watch_progress``, ``ott_usage_hours`` (Wave P PM3.1, MV6/MV7)

Additive and idempotent. No password or token is stored: viewers sign in on
Scribase Auth and only the auth subject and email are kept.

Revision ID: f6c8e0a2b4d7
Revises: e5b7d9f1a3c6
Create Date: 2026-10-02 10:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f6c8e0a2b4d7'
down_revision: Union[str, None] = 'e5b7d9f1a3c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "ott_viewers" not in tables:
        op.create_table(
            "ott_viewers",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("auth_subject", sa.String(64), nullable=False),
            sa.Column("email", sa.String(254), nullable=False, server_default=""),
            sa.Column("display_name", sa.String(60), nullable=False, server_default=""),
            sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("channel_id", "auth_subject", name="uq_ott_viewers_channel_subject"),
        )
        op.create_index("ix_ott_viewers_channel", "ott_viewers", ["channel_id"])
    if "ott_watch_progress" not in tables:
        op.create_table(
            "ott_watch_progress",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("viewer_id", sa.String(32), nullable=False),
            sa.Column("title_id", sa.String(32), nullable=False),
            sa.Column("position_s", sa.Float(), nullable=False, server_default="0"),
            sa.Column("duration_s", sa.Float(), nullable=False, server_default="0"),
            sa.Column("device", sa.String(16), nullable=False, server_default="web"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("viewer_id", "title_id", name="uq_ott_watch_progress_viewer_title"),
        )
    if "ott_usage_hours" not in tables:
        op.create_table(
            "ott_usage_hours",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("hour", sa.String(13), nullable=False),
            sa.Column("meter", sa.String(40), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
            sa.Column("billable", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "hour", "meter", name="uq_ott_usage_hours_user_hour_meter"),
        )
        op.create_index("ix_ott_usage_hours_user_hour", "ott_usage_hours", ["user_id", "hour"])


def downgrade() -> None:
    tables = _tables()
    for table in ("ott_usage_hours", "ott_watch_progress", "ott_viewers"):
        if table in tables:
            op.drop_table(table)
