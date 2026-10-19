"""usd wallet: accounts, append-only ledger, payment intents, usage records

Creates the pay-as-you-go wallet tables from
``docs/reelforge/PROVIDER_MARKETPLACE_PLAN.md`` §4.2: ``wallet_accounts``,
``payment_intents``, ``wallet_ledger_entries`` and ``usage_records``. All money
is integer microdollars; ``wallet_ledger_entries`` is append-only with cached
running ``available_after`` / ``reserved_after`` totals.

Revision ID: b2d5e8f13a20
Revises: a1c4d7e02f10
Create Date: 2026-08-17 12:30:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d5e8f13a20"
down_revision: Union[str, None] = "a1c4d7e02f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _micros() -> sa.types.TypeEngine:
    """BigInteger on Postgres/Neon; INTEGER on SQLite (matches the ORM variant)."""
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "wallet_accounts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=8),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column(
            "available_micros", _micros(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "reserved_micros", _micros(), server_default=sa.text("0"), nullable=False
        ),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_wallet_accounts_user"),
        sa.UniqueConstraint("workspace_id", name="uq_wallet_accounts_workspace"),
    )
    op.create_index(
        op.f("ix_wallet_accounts_user_id"),
        "wallet_accounts",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wallet_accounts_workspace_id"),
        "wallet_accounts",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "payment_intents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=8),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column("credit_micros", _micros(), nullable=False),
        sa.Column("fee_micros", _micros(), server_default=sa.text("0"), nullable=False),
        sa.Column("tax_micros", _micros(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "processor_micros", _micros(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("total_charge_micros", _micros(), nullable=False),
        sa.Column(
            "fee_rate_bps", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "fee_schedule_version",
            sa.String(length=40),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("payment_provider", sa.String(length=40), nullable=False),
        sa.Column("provider_ref", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'quoted'"),
            nullable=False,
        ),
        sa.Column("quote_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(["account_id"], ["wallet_accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "idempotency_key", name="uq_payment_intents_account_key"
        ),
    )
    op.create_index(
        op.f("ix_payment_intents_account_id"),
        "payment_intents",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_intents_user_id"),
        "payment_intents",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "wallet_ledger_entries",
        sa.Column("id", _micros(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("entry_type", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("available_delta", _micros(), nullable=False),
        sa.Column("reserved_delta", _micros(), nullable=False),
        sa.Column("available_after", _micros(), nullable=False),
        sa.Column("reserved_after", _micros(), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("payment_intent_id", sa.String(length=32), nullable=True),
        sa.Column("usage_record_id", sa.String(length=32), nullable=True),
        sa.Column("price_version_id", sa.String(length=32), nullable=True),
        sa.Column(
            "correlation_id",
            sa.String(length=64),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["wallet_accounts.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["payment_intent_id"], ["payment_intents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_wallet_ledger_entries_account_id"),
        "wallet_ledger_entries",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wallet_ledger_entries_job_id"),
        "wallet_ledger_entries",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wallet_ledger_entries_payment_intent_id"),
        "wallet_ledger_entries",
        ["payment_intent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wallet_ledger_entries_created_at"),
        "wallet_ledger_entries",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_ledger_account_id_id",
        "wallet_ledger_entries",
        ["account_id", "id"],
        unique=False,
    )

    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("account_id", sa.String(length=32), nullable=True),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("price_version_id", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column(
            "quantity_units", _micros(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "cost_micros", _micros(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "currency",
            sa.String(length=8),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("raw_usage", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["wallet_accounts.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_usage_records_job_id"), "usage_records", ["job_id"], unique=False
    )
    op.create_index(
        op.f("ix_usage_records_account_id"),
        "usage_records",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usage_records_model_id"), "usage_records", ["model_id"], unique=False
    )
    op.create_index(
        op.f("ix_usage_records_created_at"),
        "usage_records",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_records_created_at"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_model_id"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_account_id"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_job_id"), table_name="usage_records")
    op.drop_table("usage_records")

    op.drop_index(
        "ix_wallet_ledger_account_id_id", table_name="wallet_ledger_entries"
    )
    op.drop_index(
        op.f("ix_wallet_ledger_entries_created_at"),
        table_name="wallet_ledger_entries",
    )
    op.drop_index(
        op.f("ix_wallet_ledger_entries_payment_intent_id"),
        table_name="wallet_ledger_entries",
    )
    op.drop_index(
        op.f("ix_wallet_ledger_entries_job_id"), table_name="wallet_ledger_entries"
    )
    op.drop_index(
        op.f("ix_wallet_ledger_entries_account_id"),
        table_name="wallet_ledger_entries",
    )
    op.drop_table("wallet_ledger_entries")

    op.drop_index(op.f("ix_payment_intents_user_id"), table_name="payment_intents")
    op.drop_index(op.f("ix_payment_intents_account_id"), table_name="payment_intents")
    op.drop_table("payment_intents")

    op.drop_index(
        op.f("ix_wallet_accounts_workspace_id"), table_name="wallet_accounts"
    )
    op.drop_index(op.f("ix_wallet_accounts_user_id"), table_name="wallet_accounts")
    op.drop_table("wallet_accounts")
