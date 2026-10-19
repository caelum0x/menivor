"""media jobs: immutable Identity Lock provenance and Mint evidence

Revision ID: d2b7f904ac61
Revises: a1f4c7e20d83
Create Date: 2026-08-27 17:10:00+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2b7f904ac61"
down_revision: Union[str, None] = "a1f4c7e20d83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = (
        sa.Column(
            "identity_passport_id",
            sa.String(160),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "identity_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "identity_content_digest",
            sa.String(200),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "identity_provider",
            sa.String(80),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "identity_provenance_id",
            sa.String(180),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "identity_status",
            sa.String(20),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
        sa.Column(
            "mint_hold_id",
            sa.String(160),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "settlement_request_id",
            sa.String(128),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "settlement_payer_account",
            sa.String(160),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "settlement_receipt",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "settlement_settled_at_ms",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    for column in columns:
        op.add_column("media_jobs", column)


def downgrade() -> None:
    for name in (
        "settlement_settled_at_ms",
        "settlement_receipt",
        "settlement_payer_account",
        "settlement_request_id",
        "mint_hold_id",
        "identity_status",
        "identity_provenance_id",
        "identity_provider",
        "identity_content_digest",
        "identity_version",
        "identity_passport_id",
    ):
        op.drop_column("media_jobs", name)
