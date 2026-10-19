"""wallet account graph, transfer review challenges, limits and recipients

Revision ID: b8e4f02ad573
Revises: a7d3e91bc462
Create Date: 2026-08-27 26:00:00+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8e4f02ad573"
down_revision: Union[str, None] = "a7d3e91bc462"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _micros() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_index(
        "uq_wallet_accounts_mint_account_id",
        "wallet_accounts",
        ["mint_account_id"],
        unique=True,
    )

    op.create_table(
        "wallet_account_owners",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("principal_kind", sa.String(length=20), nullable=False),
        sa.Column("principal_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["wallet_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_wallet_account_owners_account"),
        sa.UniqueConstraint(
            "principal_kind",
            "principal_ref",
            name="uq_wallet_account_owners_principal",
        ),
    )
    op.create_index(
        "ix_wallet_account_owners_principal",
        "wallet_account_owners",
        ["principal_kind", "principal_ref"],
        unique=False,
    )
    # Existing account ids are already random 32-char values and make stable,
    # collision-free backfill ids for their one-to-one ownership edges.
    op.execute(
        sa.text(
            """
            INSERT INTO wallet_account_owners
                (id, account_id, principal_kind, principal_ref)
            SELECT id, id, 'personal', user_id
            FROM wallet_accounts
            WHERE user_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO wallet_account_owners
                (id, account_id, principal_kind, principal_ref)
            SELECT id, id, 'workspace', workspace_id
            FROM wallet_accounts
            WHERE workspace_id IS NOT NULL
              AND user_id IS NULL
            """
        )
    )

    op.create_table(
        "wallet_transfer_policies",
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column(
            "per_transfer_limit_micros",
            _micros(),
            server_default=sa.text("1000000000"),
            nullable=False,
        ),
        sa.Column(
            "daily_limit_micros",
            _micros(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["wallet_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("account_id"),
    )

    op.create_table(
        "wallet_transfer_challenges",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=32), nullable=False),
        sa.Column("source_account_id", sa.String(length=32), nullable=False),
        sa.Column("recipient_user_id", sa.String(length=32), nullable=False),
        sa.Column("recipient_account_id", sa.String(length=32), nullable=False),
        sa.Column("recipient_handle", sa.String(length=64), nullable=False),
        sa.Column("recipient_display_name", sa.String(length=200), nullable=False),
        sa.Column("amount_micros", _micros(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_transfer_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_account_id"], ["wallet_accounts.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["recipient_account_id"], ["wallet_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_account_id",
            "idempotency_key",
            name="uq_wallet_transfer_challenges_source_key",
        ),
    )
    op.create_index(
        op.f("ix_wallet_transfer_challenges_actor_user_id"),
        "wallet_transfer_challenges",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wallet_transfer_challenges_source_account_id"),
        "wallet_transfer_challenges",
        ["source_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wallet_transfer_challenges_expires_at"),
        "wallet_transfer_challenges",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "wallet_saved_recipients",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column("source_account_id", sa.String(length=32), nullable=False),
        sa.Column("recipient_user_id", sa.String(length=32), nullable=False),
        sa.Column("recipient_account_id", sa.String(length=32), nullable=False),
        sa.Column("recipient_handle", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=100), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_account_id"], ["wallet_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["recipient_account_id"], ["wallet_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "source_account_id",
            "recipient_account_id",
            name="uq_wallet_saved_recipients_owner_source_recipient",
        ),
    )
    op.create_index(
        op.f("ix_wallet_saved_recipients_owner_user_id"),
        "wallet_saved_recipients",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_saved_recipients_owner_source",
        "wallet_saved_recipients",
        ["owner_user_id", "source_account_id", "created_at"],
        unique=False,
    )

    with op.batch_alter_table("wallet_transfers") as batch:
        batch.add_column(
            sa.Column(
                "sender_source_kind",
                sa.String(length=20),
                server_default=sa.text("'personal'"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "sender_source_ref",
                sa.String(length=128),
                server_default=sa.text("''"),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "sender_source_label",
                sa.String(length=200),
                server_default=sa.text("''"),
                nullable=False,
            )
        )
        batch.add_column(sa.Column("challenge_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_wallet_transfers_challenge_id",
            "wallet_transfer_challenges",
            ["challenge_id"],
            ["id"],
        )
        batch.create_unique_constraint(
            "uq_wallet_transfers_challenge", ["challenge_id"]
        )
    op.execute(
        sa.text(
            """
            UPDATE wallet_transfers
            SET sender_source_ref = sender_user_id,
                sender_source_label = sender_handle
            WHERE sender_source_ref = ''
            """
        )
    )
    op.create_index(
        "ix_wallet_transfers_sender_status_created",
        "wallet_transfers",
        ["sender_account_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wallet_transfers_sender_status_created", table_name="wallet_transfers"
    )
    with op.batch_alter_table("wallet_transfers") as batch:
        batch.drop_constraint("uq_wallet_transfers_challenge", type_="unique")
        batch.drop_constraint("fk_wallet_transfers_challenge_id", type_="foreignkey")
        batch.drop_column("challenge_id")
        batch.drop_column("sender_source_label")
        batch.drop_column("sender_source_ref")
        batch.drop_column("sender_source_kind")

    op.drop_index(
        "ix_wallet_saved_recipients_owner_source",
        table_name="wallet_saved_recipients",
    )
    op.drop_index(
        op.f("ix_wallet_saved_recipients_owner_user_id"),
        table_name="wallet_saved_recipients",
    )
    op.drop_table("wallet_saved_recipients")

    op.drop_index(
        op.f("ix_wallet_transfer_challenges_expires_at"),
        table_name="wallet_transfer_challenges",
    )
    op.drop_index(
        op.f("ix_wallet_transfer_challenges_source_account_id"),
        table_name="wallet_transfer_challenges",
    )
    op.drop_index(
        op.f("ix_wallet_transfer_challenges_actor_user_id"),
        table_name="wallet_transfer_challenges",
    )
    op.drop_table("wallet_transfer_challenges")
    op.drop_table("wallet_transfer_policies")
    op.drop_index(
        "ix_wallet_account_owners_principal", table_name="wallet_account_owners"
    )
    op.drop_table("wallet_account_owners")
    op.drop_index("uq_wallet_accounts_mint_account_id", table_name="wallet_accounts")
