"""media jobs: durable generic settlement lifecycle

Revision ID: d7a4b91ce820
Revises: c9f5a13de720
Create Date: 2026-08-28 02:00:00
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "d7a4b91ce820"
down_revision: Union[str, None] = "c9f5a13de720"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "media_jobs",
        sa.Column(
            "settlement_rail",
            sa.String(12),
            server_default=sa.text("'local'"),
            nullable=False,
        ),
    )
    op.add_column(
        "media_jobs",
        sa.Column(
            "settlement_attestation",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "media_jobs",
        sa.Column(
            "settlement_verified_at_ms",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "media_jobs",
        sa.Column(
            "settlement_outcome",
            sa.String(20),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column(
        "media_jobs",
        sa.Column(
            "settlement_intent",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )

    # Existing Mint rows are identified by their durable hold, never by today's
    # rollout flag. Their old flat receipts lack the new pinned-key attestation,
    # so they deliberately remain nonterminal money evidence until reconciled.
    op.execute(
        "UPDATE media_jobs SET settlement_rail = 'mint', "
        "settlement_outcome = 'held' WHERE mint_hold_id <> ''"
    )
    # Local terminal state is durable in the same database transaction. These
    # outcomes carry no signed receipt and therefore cannot become Mint evidence.
    op.execute(
        "UPDATE media_jobs SET settlement_outcome = 'captured' "
        "WHERE settlement_rail = 'local' AND status = 'completed'"
    )
    op.execute(
        "UPDATE media_jobs SET settlement_outcome = 'released' "
        "WHERE settlement_rail = 'local' AND status = 'failed'"
    )
    op.execute(
        "UPDATE media_jobs SET settlement_outcome = 'held' "
        "WHERE settlement_rail = 'local' AND settlement_outcome = '' "
        "AND held_cost_micros > 0"
    )


def downgrade() -> None:
    op.drop_column("media_jobs", "settlement_verified_at_ms")
    op.drop_column("media_jobs", "settlement_attestation")
    op.drop_column("media_jobs", "settlement_intent")
    op.drop_column("media_jobs", "settlement_outcome")
    op.drop_column("media_jobs", "settlement_rail")
