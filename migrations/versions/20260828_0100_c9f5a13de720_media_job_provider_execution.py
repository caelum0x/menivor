"""media jobs: versioned provider execution snapshot

Revision ID: c9f5a13de720
Revises: b8e4f02ad573
Create Date: 2026-08-28 01:00:00
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "c9f5a13de720"
down_revision: Union[str, None] = "b8e4f02ad573"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "media_jobs",
        sa.Column(
            "provider_execution",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("media_jobs", "provider_execution")
