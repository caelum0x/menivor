"""Content Month: website -> a month of post ideas (content_plans, content_ideas).

Additive and idempotent (each table is created only when missing).

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1
Create Date: 2026-10-09 15:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3e5a7b9d1f2'
down_revision: Union[str, None] = 'b2d4f6a8c0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _now() -> sa.sql.elements.ClauseElement:
    return sa.func.now()


def upgrade() -> None:
    existing = _tables()
    if "content_plans" not in existing:
        op.create_table(
            "content_plans",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("name", sa.String(120), nullable=False, server_default=""),
            sa.Column("brief_json", sa.JSON(), nullable=False),
            sa.Column("style_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        )
        op.create_index("ix_content_plans_user_id", "content_plans", ["user_id"])
    if "content_ideas" not in existing:
        op.create_table(
            "content_ideas",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("plan_id", sa.String(32), sa.ForeignKey("content_plans.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("format", sa.String(40), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("hook", sa.Text(), nullable=False, server_default=""),
            sa.Column("slides", sa.JSON(), nullable=False),
            sa.Column("script", sa.Text(), nullable=False, server_default=""),
            sa.Column("caption", sa.Text(), nullable=False, server_default=""),
            sa.Column("source", sa.String(16), nullable=False, server_default="rules"),
            sa.Column("decision", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("render_status", sa.String(16), nullable=False, server_default="none"),
            sa.Column("outputs", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        )
        op.create_index("ix_content_ideas_plan_id", "content_ideas", ["plan_id"])
        op.create_index("ix_content_ideas_user_id", "content_ideas", ["user_id"])


def downgrade() -> None:
    existing = _tables()
    if "content_ideas" in existing:
        op.drop_index("ix_content_ideas_user_id", table_name="content_ideas")
        op.drop_index("ix_content_ideas_plan_id", table_name="content_ideas")
        op.drop_table("content_ideas")
    if "content_plans" in existing:
        op.drop_index("ix_content_plans_user_id", table_name="content_plans")
        op.drop_table("content_plans")
