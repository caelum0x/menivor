"""Integrations: ad-account connections, accounts, Brand-space access, common metrics, onboarding grants

Creates ``integration_connections``, ``integration_oauth_states``,
``integration_ad_accounts``, ``integration_ad_account_brands``,
``integration_ad_metrics`` and ``integration_onboarding_grants``, and widens
``ck_store_catalog_imports_provider`` to the new product sources (``medusa``,
``csv``). Additive and idempotent. Tokens are stored only as encrypted blobs.

Revision ID: f4b6d8a0c2e5
Revises: e3a5c7d9f1b2
Create Date: 2026-10-06 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f4b6d8a0c2e5'
down_revision: Union[str, None] = 'e3a5c7d9f1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_PROVIDERS = "provider IN ('shopify', 'woocommerce')"
_NEW_PROVIDERS = "provider IN ('shopify', 'woocommerce', 'medusa', 'csv')"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _now():
    return sa.func.now()


def upgrade() -> None:
    tables = _tables()
    if "integration_connections" not in tables:
        op.create_table(
            "integration_connections",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("owner_scope", sa.String(48), nullable=False),
            sa.Column("workspace_id", sa.String(32), sa.ForeignKey("workspaces.id"), nullable=True),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("provider", sa.String(24), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="connected"),
            sa.Column("access_token_enc", sa.Text(), nullable=False),
            sa.Column("refresh_token_enc", sa.Text(), nullable=True),
            sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
            sa.Column("token_hint", sa.String(16), nullable=False, server_default=""),
            sa.Column("external_id", sa.String(200), nullable=False, server_default=""),
            sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.UniqueConstraint("owner_scope", "provider", name="uq_integration_connections_scope_provider"),
            sa.CheckConstraint("kind IN ('ads', 'slack', 'product_source')", name="ck_integration_connections_kind"),
        )
        op.create_index("ix_integration_connections_owner_scope", "integration_connections", ["owner_scope"])
        op.create_index("ix_integration_connections_workspace_id", "integration_connections", ["workspace_id"])
        op.create_index("ix_integration_connections_user_id", "integration_connections", ["user_id"])
        op.create_index("ix_integration_connections_external_id", "integration_connections", ["external_id"])

    if "integration_oauth_states" not in tables:
        op.create_table(
            "integration_oauth_states",
            sa.Column("state_hash", sa.String(64), primary_key=True),
            sa.Column("owner_scope", sa.String(48), nullable=False),
            sa.Column("workspace_id", sa.String(32), sa.ForeignKey("workspaces.id"), nullable=True),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("provider", sa.String(24), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_integration_oauth_states_user_id", "integration_oauth_states", ["user_id"])
        op.create_index("ix_integration_oauth_states_expires_at", "integration_oauth_states", ["expires_at"])

    if "integration_ad_accounts" not in tables:
        op.create_table(
            "integration_ad_accounts",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("connection_id", sa.String(32),
                      sa.ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_scope", sa.String(48), nullable=False),
            sa.Column("provider", sa.String(24), nullable=False),
            sa.Column("external_id", sa.String(128), nullable=False),
            sa.Column("name", sa.String(300), nullable=False, server_default=""),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("timezone", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("last_pulled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.UniqueConstraint("connection_id", "external_id", name="uq_integration_ad_accounts_conn_ext"),
        )
        op.create_index("ix_integration_ad_accounts_connection_id", "integration_ad_accounts", ["connection_id"])
        op.create_index("ix_integration_ad_accounts_owner_scope", "integration_ad_accounts", ["owner_scope"])

    if "integration_ad_account_brands" not in tables:
        op.create_table(
            "integration_ad_account_brands",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("ad_account_id", sa.String(32),
                      sa.ForeignKey("integration_ad_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("brand_space_id", sa.String(32), sa.ForeignKey("user_presets.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("created_by", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.UniqueConstraint("ad_account_id", "brand_space_id", name="uq_integration_ad_account_brand"),
        )
        op.create_index("ix_integration_ad_account_brands_ad_account_id", "integration_ad_account_brands",
                        ["ad_account_id"])
        op.create_index("ix_integration_ad_account_brands_brand_space_id", "integration_ad_account_brands",
                        ["brand_space_id"])

    if "integration_ad_metrics" not in tables:
        op.create_table(
            "integration_ad_metrics",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("ad_account_id", sa.String(32),
                      sa.ForeignKey("integration_ad_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_scope", sa.String(48), nullable=False),
            sa.Column("provider", sa.String(24), nullable=False),
            sa.Column("day", sa.String(10), nullable=False),
            sa.Column("entity_id", sa.String(160), nullable=False),
            sa.Column("entity_name", sa.String(300), nullable=False, server_default=""),
            sa.Column("campaign_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("group_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("spend_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("impressions", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("clicks", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("conversions", sa.Float(), nullable=True),
            sa.Column("conversion_value_minor", sa.BigInteger(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.UniqueConstraint("ad_account_id", "day", "entity_id", name="uq_integration_ad_metrics_row"),
        )
        op.create_index("ix_integration_ad_metrics_ad_account_id", "integration_ad_metrics", ["ad_account_id"])
        op.create_index("ix_integration_ad_metrics_owner_scope", "integration_ad_metrics", ["owner_scope"])
        op.create_index("ix_integration_ad_metrics_day", "integration_ad_metrics", ["day"])

    if "integration_onboarding_grants" not in tables:
        op.create_table(
            "integration_onboarding_grants",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("owner_scope", sa.String(48), nullable=False),
            sa.Column("step", sa.String(32), nullable=False),
            sa.Column("credits", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.UniqueConstraint("owner_scope", "step", name="uq_integration_onboarding_scope_step"),
        )
        op.create_index("ix_integration_onboarding_grants_owner_scope", "integration_onboarding_grants",
                        ["owner_scope"])

    _set_catalog_providers(_NEW_PROVIDERS)


def _set_catalog_providers(expression: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql" or "store_catalog_imports" not in _tables():
        return  # SQLite cannot alter a check constraint in place; the ORM never relied on it
    op.execute("ALTER TABLE store_catalog_imports DROP CONSTRAINT IF EXISTS ck_store_catalog_imports_provider")
    op.create_check_constraint("ck_store_catalog_imports_provider", "store_catalog_imports", expression)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and "store_catalog_imports" in _tables():
        op.execute("DELETE FROM store_catalog_products WHERE import_id IN "
                   "(SELECT id FROM store_catalog_imports WHERE provider IN ('medusa', 'csv'))")
        op.execute("DELETE FROM store_catalog_imports WHERE provider IN ('medusa', 'csv')")
        _set_catalog_providers(_OLD_PROVIDERS)
    tables = _tables()
    for name in ("integration_onboarding_grants", "integration_ad_metrics", "integration_ad_account_brands",
                 "integration_ad_accounts", "integration_oauth_states", "integration_connections"):
        if name in tables:
            op.drop_table(name)
