"""wallet transfers: separately persisted verified Mint attestation

Revision ID: c5e9b7d24f81
Revises: f4d9a6c13b72
Create Date: 2026-08-28 00:00:00+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5e9b7d24f81"
down_revision: Union[str, None] = "f4d9a6c13b72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wallet_transfer_attestations",
        sa.Column("transfer_id", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=64), nullable=False),
        sa.Column("signer_key_id", sa.String(length=128), nullable=False),
        sa.Column("payload_base64url", sa.Text(), nullable=False),
        sa.Column("digest_sha256", sa.String(length=64), nullable=False),
        sa.Column("signature_hex", sa.String(length=128), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"], ["wallet_transfers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("transfer_id"),
    )
def downgrade() -> None:
    op.drop_table("wallet_transfer_attestations")
