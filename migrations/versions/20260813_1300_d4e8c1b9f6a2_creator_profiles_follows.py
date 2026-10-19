"""creator profiles + follow graph (creator_follows + users.handle/bio)

Revision ID: d4e8c1b9f6a2
Revises: c3d9b7e2f4a8
Create Date: 2026-08-13 13:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8c1b9f6a2'
down_revision: Union[str, None] = 'c3d9b7e2f4a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Explicit names so the (otherwise nameless) constraints are addressable in
# ``downgrade`` and portable across SQLite (tests) and Postgres/Neon (prod).
_UQ_USERS_HANDLE = "uq_users_handle"
_UQ_CREATOR_FOLLOWS = "uq_creator_follows_follower_followee"


def upgrade() -> None:
    # Creator Profiles + Follow Graph + Leaderboards.
    #
    # 1) PUBLIC PROFILE identity on ``users``: ``handle`` (nullable, UNIQUE — a
    #    creator's public vanity slug; multiple NULLs are allowed on both SQLite
    #    and Postgres so unclaimed handles stay NULL while a claimed one resolves
    #    to exactly one owner, mirroring ``referral_code``) and ``bio`` (nullable
    #    free-text blurb). Both are additive + nullable so the ADD COLUMN is safe
    #    on an already-populated ``users`` table and existing rows / prior tests
    #    are unaffected. Neither is a private/financial field. SQLite cannot ALTER
    #    TABLE ADD CONSTRAINT, so the columns + the handle UNIQUE constraint are
    #    added via batch mode (copy-and-move on SQLite, plain ALTERs on Postgres);
    #    the constraint is named so downgrade can drop it deterministically.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("handle", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("bio", sa.Text(), nullable=True))
        batch_op.create_unique_constraint(_UQ_USERS_HANDLE, ["handle"])

    # 2) FOLLOW GRAPH: a brand-new ``creator_follows`` table holding directed
    #    ``follower_user_id -> followee_user_id`` edges. A composite UNIQUE
    #    constraint guarantees a given directed edge exists AT MOST ONCE, so a
    #    double-follow can never create a second row (idempotent follow). Both
    #    foreign keys are indexed so "who follows X?" (followers) and "who does X
    #    follow?" (following) are O(index) lookups / aggregates. A brand-new table,
    #    so the CREATE is safe on an already-populated database and existing rows /
    #    prior tests are unaffected.
    op.create_table(
        "creator_follows",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("follower_user_id", sa.String(length=32), nullable=False),
        sa.Column("followee_user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["follower_user_id"], ["users.id"], ),
        sa.ForeignKeyConstraint(["followee_user_id"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "follower_user_id", "followee_user_id", name=_UQ_CREATOR_FOLLOWS
        ),
    )
    op.create_index(
        op.f("ix_creator_follows_follower_user_id"),
        "creator_follows",
        ["follower_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_creator_follows_followee_user_id"),
        "creator_follows",
        ["followee_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_creator_follows_followee_user_id"),
        table_name="creator_follows",
    )
    op.drop_index(
        op.f("ix_creator_follows_follower_user_id"),
        table_name="creator_follows",
    )
    op.drop_table("creator_follows")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(_UQ_USERS_HANDLE, type_="unique")
        batch_op.drop_column("bio")
        batch_op.drop_column("handle")
