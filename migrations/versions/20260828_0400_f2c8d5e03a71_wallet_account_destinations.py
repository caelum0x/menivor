"""typed public account destinations for wallet transfers

Revision ID: f2c8d5e03a71
Revises: e1b7c4d92f60
Create Date: 2026-08-28 04:00:00
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2c8d5e03a71"
down_revision: Union[str, None] = "e1b7c4d92f60"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def _add_destination_columns(table: str, *, challenge: bool) -> None:
    with op.batch_alter_table(table) as batch:
        batch.alter_column(
            "recipient_user_id", existing_type=sa.String(32), nullable=True
        )
        batch.alter_column(
            "recipient_handle",
            existing_type=sa.String(64),
            type_=sa.String(128),
            existing_nullable=False,
        )
        batch.add_column(
            sa.Column(
                "recipient_kind",
                sa.String(20),
                server_default=sa.text("'personal'"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "recipient_ref",
                sa.String(128),
                server_default=sa.text("''"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "recipient_label",
                sa.String(200),
                server_default=sa.text("''"),
                nullable=False,
            )
        )
        if challenge:
            # Added with default 1 so pre-existing challenge rows — bound under
            # the v1 scheme (their ``binding_sha256`` excludes the new
            # recipient_kind/ref/label fields) — backfill to v1 and still verify.
            # The column default is advanced to 2 immediately after (see
            # ``_advance_binding_version_default``) so *new* challenges default to
            # the current v2 scheme, matching the ORM model, without rewriting the
            # already-correct v1 rows.
            batch.add_column(
                sa.Column(
                    "binding_version",
                    sa.Integer(),
                    server_default=sa.text("1"),
                    nullable=False,
                )
            )


def _advance_binding_version_default(table: str) -> None:
    """Advance ``binding_version``'s column default from 1 (backfill) to 2.

    Only the stored default changes; existing rows keep their backfilled value
    of 1. New challenges are created explicitly at v2 (``wallet.service``), and
    the ORM model declares ``server_default=text("2")`` — this keeps the live
    schema in agreement so ``alembic check`` stays green.
    """
    with op.batch_alter_table(table) as batch:
        batch.alter_column(
            "binding_version",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text("2"),
        )


def upgrade() -> None:
    _add_destination_columns("wallet_transfer_challenges", challenge=True)
    _add_destination_columns("wallet_transfers", challenge=False)
    _advance_binding_version_default("wallet_transfer_challenges")
    for table in ("wallet_transfer_challenges", "wallet_transfers"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET recipient_ref = recipient_user_id, "
                "recipient_label = recipient_handle "
                "WHERE recipient_ref = '' AND recipient_user_id IS NOT NULL"
            )
        )


def _drop_destination_columns(table: str, *, challenge: bool) -> None:
    # Workspace-address rows cannot be represented by the old non-null user FK.
    op.execute(sa.text(f"DELETE FROM {table} WHERE recipient_user_id IS NULL"))
    with op.batch_alter_table(table) as batch:
        if challenge:
            batch.drop_column("binding_version")
        batch.drop_column("recipient_label")
        batch.drop_column("recipient_ref")
        batch.drop_column("recipient_kind")
        batch.alter_column(
            "recipient_handle",
            existing_type=sa.String(128),
            type_=sa.String(64),
            existing_nullable=False,
        )
        batch.alter_column(
            "recipient_user_id", existing_type=sa.String(32), nullable=False
        )


def downgrade() -> None:
    _drop_destination_columns("wallet_transfers", challenge=False)
    _drop_destination_columns("wallet_transfer_challenges", challenge=True)
