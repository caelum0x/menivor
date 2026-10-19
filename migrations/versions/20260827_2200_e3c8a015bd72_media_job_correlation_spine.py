"""media jobs: durable cross-service request correlation spine

Revision ID: e3c8a015bd72
Revises: d2b7f904ac61
Create Date: 2026-08-27 22:00:00+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3c8a015bd72"
down_revision: Union[str, None] = "d2b7f904ac61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_jobs",
        sa.Column(
            "correlation_id",
            sa.String(128),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE media_jobs SET correlation_id = 'gateway_' || id "
        "WHERE correlation_id = ''"
    )
    # Non-unique on purpose: ``correlation_id`` is the *shared* cross-service
    # business request id (Prism / Mint / Passport / Abacus), NOT a per-row key.
    # The ORM model declares it ``index=True`` (non-unique); a UNIQUE index would
    # reject any legitimate second media_jobs row that reuses a correlation id
    # (e.g. a client-supplied idempotency correlation via
    # ``gateway.service`` ``correlation_id=...``), so it is a plain index.
    op.create_index(
        "ix_media_jobs_correlation_id",
        "media_jobs",
        ["correlation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_media_jobs_correlation_id", table_name="media_jobs")
    op.drop_column("media_jobs", "correlation_id")
