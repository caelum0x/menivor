"""provider marketplace catalog (providers, models, prices, profiles)

Creates the reviewed model-catalog tables from
``docs/reelforge/PROVIDER_MARKETPLACE_PLAN.md`` §4.2: ``provider_catalogs``,
``model_catalog_entries``, ``price_versions`` and ``generation_profiles``.
Money columns are integer microdollars. The wallet tables land in the following
revision so each migration stays focused and independently reviewable.

Revision ID: a1c4d7e02f10
Revises: e6c4f9a12b73
Create Date: 2026-08-17 12:00:00.000000+00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c4d7e02f10"
down_revision: Union[str, None] = "e6c4f9a12b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _micros() -> sa.types.TypeEngine:
    """BigInteger on Postgres/Neon; INTEGER on SQLite (matches the ORM variant)."""
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "provider_catalogs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("region", sa.String(length=80), nullable=False),
        sa.Column("data_policy", sa.String(length=200), nullable=False),
        sa.Column(
            "health_state",
            sa.String(length=20),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column(
            "credential_state",
            sa.String(length=20),
            server_default=sa.text("'unconfigured'"),
            nullable=False,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.false(), nullable=False
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_catalogs_provider_key"),
        "provider_catalogs",
        ["provider_key"],
        unique=True,
    )

    op.create_table(
        "model_catalog_entries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "description", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("metering_unit", sa.String(length=40), nullable=False),
        sa.Column("supported_inputs", sa.JSON(), nullable=False),
        sa.Column("output_limits", sa.JSON(), nullable=False),
        sa.Column("region", sa.String(length=80), nullable=False),
        sa.Column("data_policy", sa.String(length=200), nullable=False),
        sa.Column("latency_band", sa.String(length=20), nullable=False),
        sa.Column(
            "availability_state",
            sa.String(length=20),
            server_default=sa.text("'available'"),
            nullable=False,
        ),
        sa.Column(
            "release_status",
            sa.String(length=20),
            server_default=sa.text("'shadow'"),
            nullable=False,
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
        sa.ForeignKeyConstraint(["provider_id"], ["provider_catalogs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_catalog_entries_model_id"),
        "model_catalog_entries",
        ["model_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_model_catalog_entries_provider_id"),
        "model_catalog_entries",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_catalog_entries_capability"),
        "model_catalog_entries",
        ["capability"],
        unique=False,
    )
    op.create_index(
        "ix_model_catalog_capability_release",
        "model_catalog_entries",
        ["capability", "release_status"],
        unique=False,
    )

    op.create_table(
        "price_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("model_entry_id", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=8),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("unit_price_micros", _micros(), nullable=False),
        sa.Column(
            "min_charge_micros",
            _micros(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "flat_fee_micros", _micros(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("quote_rules", sa.JSON(), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "source",
            sa.String(length=40),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["model_entry_id"], ["model_catalog_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_id", "version", name="uq_price_versions_model_version"
        ),
    )
    op.create_index(
        op.f("ix_price_versions_model_entry_id"),
        "price_versions",
        ["model_entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_price_versions_model_id"),
        "price_versions",
        ["model_id"],
        unique=False,
    )
    op.create_index(
        "ix_price_versions_model_effective",
        "price_versions",
        ["model_id", "effective_from"],
        unique=False,
    )

    op.create_table(
        "generation_profiles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=True),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "description", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("routing", sa.JSON(), nullable=False),
        sa.Column(
            "max_cost_micros",
            _micros(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "is_curated", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.true(), nullable=False
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
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_generation_profiles_slug"),
        "generation_profiles",
        ["slug"],
        unique=True,
    )
    op.create_index(
        op.f("ix_generation_profiles_owner_user_id"),
        "generation_profiles",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_profiles_workspace_id"),
        "generation_profiles",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_generation_profiles_workspace_id"), table_name="generation_profiles"
    )
    op.drop_index(
        op.f("ix_generation_profiles_owner_user_id"), table_name="generation_profiles"
    )
    op.drop_index(op.f("ix_generation_profiles_slug"), table_name="generation_profiles")
    op.drop_table("generation_profiles")

    op.drop_index(
        "ix_price_versions_model_effective", table_name="price_versions"
    )
    op.drop_index(op.f("ix_price_versions_model_id"), table_name="price_versions")
    op.drop_index(op.f("ix_price_versions_model_entry_id"), table_name="price_versions")
    op.drop_table("price_versions")

    op.drop_index(
        "ix_model_catalog_capability_release", table_name="model_catalog_entries"
    )
    op.drop_index(
        op.f("ix_model_catalog_entries_capability"),
        table_name="model_catalog_entries",
    )
    op.drop_index(
        op.f("ix_model_catalog_entries_provider_id"),
        table_name="model_catalog_entries",
    )
    op.drop_index(
        op.f("ix_model_catalog_entries_model_id"), table_name="model_catalog_entries"
    )
    op.drop_table("model_catalog_entries")

    op.drop_index(
        op.f("ix_provider_catalogs_provider_key"), table_name="provider_catalogs"
    )
    op.drop_table("provider_catalogs")
