"""team spend roles: spend_policies.spend_min_role

Adds the minimum workspace role allowed to spend the shared pool (owner|admin|
member) so a team can restrict who may draw the wallet.

Revision ID: f6b9c3d75e84
Revises: e5a8b2c64d73
Create Date: 2026-08-17 14:30:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6b9c3d75e84"
down_revision: Union[str, None] = "e5a8b2c64d73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "spend_policies",
        sa.Column(
            "spend_min_role",
            sa.String(length=20),
            server_default=sa.text("'member'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("spend_policies", "spend_min_role")
