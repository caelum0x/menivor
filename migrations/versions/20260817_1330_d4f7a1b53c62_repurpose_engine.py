"""repurposing engine: long video -> ranked highlight clips

Creates ``repurpose_jobs`` (source + transcribe/rank lifecycle) and
``repurpose_clips`` (scored, promotable short-form cuts).

Revision ID: d4f7a1b53c62
Revises: c3e6f9a24b31
Create Date: 2026-08-17 13:30:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f7a1b53c62"
down_revision: Union[str, None] = "c3e6f9a24b31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repurpose_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "source_kind",
            sa.String(length=20),
            server_default=sa.text("'upload'"),
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(length=1024), nullable=False),
        sa.Column(
            "language",
            sa.String(length=16),
            server_default=sa.text("'auto'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'created'"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "duration_s", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "clip_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("error", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_repurpose_jobs_user_id"), "repurpose_jobs", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_repurpose_jobs_created_at"),
        "repurpose_jobs",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "repurpose_clips",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("repurpose_job_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("start_s", sa.Integer(), nullable=False),
        sa.Column("end_s", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("hook", sa.String(length=300), nullable=False),
        sa.Column(
            "transcript", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "virality_score", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("reason", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'suggested'"),
            nullable=False,
        ),
        sa.Column("reel_job_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repurpose_job_id"], ["repurpose_jobs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_repurpose_clips_repurpose_job_id"),
        "repurpose_clips",
        ["repurpose_job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repurpose_clips_user_id"),
        "repurpose_clips",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_repurpose_clips_job_score",
        "repurpose_clips",
        ["repurpose_job_id", "virality_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_repurpose_clips_job_score", table_name="repurpose_clips")
    op.drop_index(op.f("ix_repurpose_clips_user_id"), table_name="repurpose_clips")
    op.drop_index(
        op.f("ix_repurpose_clips_repurpose_job_id"), table_name="repurpose_clips"
    )
    op.drop_table("repurpose_clips")
    op.drop_index(op.f("ix_repurpose_jobs_created_at"), table_name="repurpose_jobs")
    op.drop_index(op.f("ix_repurpose_jobs_user_id"), table_name="repurpose_jobs")
    op.drop_table("repurpose_jobs")
