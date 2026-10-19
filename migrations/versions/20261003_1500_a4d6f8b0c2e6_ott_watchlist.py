"""OTT viewer retention (Wave Q QM1.5): watchlist, ratings, push opt-ins, title credits.

Additive and idempotent: three new tables and one JSON column on ott_titles.

Revision ID: a4d6f8b0c2e6
Revises: f3c5e7a9b1d4
Create Date: 2026-10-03 15:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a4d6f8b0c2e6'
down_revision: Union[str, None] = 'f3c5e7a9b1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "ott_watchlist" not in tables:
        op.create_table(
            "ott_watchlist",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("viewer_id", sa.String(32), nullable=False),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("title_id", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("viewer_id", "title_id", name="uq_ott_watchlist_viewer_title"),
        )
        op.create_index("ix_ott_watchlist_viewer", "ott_watchlist", ["viewer_id"])
    if "ott_ratings" not in tables:
        op.create_table(
            "ott_ratings",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("viewer_id", sa.String(32), nullable=False),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("title_id", sa.String(32), nullable=False),
            sa.Column("stars", sa.SmallInteger(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("viewer_id", "title_id", name="uq_ott_ratings_viewer_title"),
        )
        op.create_index("ix_ott_ratings_title", "ott_ratings", ["title_id"])
    if "ott_viewer_push" not in tables:
        op.create_table(
            "ott_viewer_push",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("viewer_id", sa.String(32), nullable=False),
            sa.Column("channel_id", sa.String(32), nullable=False),
            sa.Column("token", sa.String(200), nullable=False),
            sa.Column("platform", sa.String(16), nullable=False, server_default="ios"),
            sa.Column("topics", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("viewer_id", "token", name="uq_ott_viewer_push_viewer_token"),
        )
        op.create_index("ix_ott_viewer_push_channel", "ott_viewer_push", ["channel_id"])
    if "ott_titles" in tables and "credits" not in _columns("ott_titles"):
        op.add_column("ott_titles", sa.Column("credits", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    tables = _tables()
    if "ott_titles" in tables and "credits" in _columns("ott_titles"):
        with op.batch_alter_table("ott_titles") as batch:
            batch.drop_column("credits")
    for table in ("ott_viewer_push", "ott_ratings", "ott_watchlist"):
        if table in tables:
            op.drop_table(table)
