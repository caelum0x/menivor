"""series/clipfarm: channel_runs + channel_clips (unattended runner persistence)

The channel runner (``app.domains.series.runner``) and its HTTP surface
(``/api/v1/series/channels/{id}/run`` etc.) read/write two tables — ``channel_runs``
(one row per unattended pass) and ``channel_clips`` (one row per rendered clip,
carrying the cross-run dedupe ``spec_hash``). The models are declared in
``app.models.db.series_runs`` and registered on ``Base.metadata`` (imported by
``migrations/env.py``), but no migration ever created the tables. On a fresh
Postgres this made the entire series/clipfarm flow fail with
``UndefinedTable: relation "channel_clips" does not exist``. (SQLite test setups
that build the schema from ``Base.metadata.create_all`` had the tables and so
never caught the missing migration.)

This is a straight, additive create matching the model definitions.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-02 04:20:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def _jsonb_variant() -> sa.types.TypeEngine:
    """JSON that materialises as JSONB on PostgreSQL (JSON elsewhere).

    Mirrors ``app.models.db.base.jsonb_variant`` without importing app code into
    the migration. JSONB has ``=`` so Alembic's server-default drift check can
    compare ``channel_runs.params``'s ``'{}'`` default instead of raising
    ``operator does not exist: json = unknown``.
    """
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column(
            "params",
            _jsonb_variant(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_channel_runs_user_id"), "channel_runs", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_channel_runs_channel_id"), "channel_runs", ["channel_id"], unique=False
    )
    op.create_index(
        op.f("ix_channel_runs_created_at"), "channel_runs", ["created_at"], unique=False
    )

    op.create_table(
        "channel_clips",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("spec_hash", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column(
            "account",
            sa.String(length=64),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "platform",
            sa.String(length=32),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("scheduled_publish_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # NOTE: ``run_id`` is the runner-generated grouping id, not a
        # ``channel_runs`` primary key (clips are written during the pass; the
        # ``channel_runs`` bookkeeping row is written afterwards with its own
        # uuid, and the worker path writes none at all). It therefore carries no
        # FK to ``channel_runs`` — only an index (created below).
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_channel_clips_channel_id"), "channel_clips", ["channel_id"], unique=False
    )
    op.create_index(
        op.f("ix_channel_clips_run_id"), "channel_clips", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_channel_clips_spec_hash"), "channel_clips", ["spec_hash"], unique=False
    )
    op.create_index(
        op.f("ix_channel_clips_job_id"), "channel_clips", ["job_id"], unique=False
    )
    op.create_index(
        op.f("ix_channel_clips_status"), "channel_clips", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_channel_clips_created_at"), "channel_clips", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_table("channel_clips")
    op.drop_table("channel_runs")
