"""Wave L seed: design studio, approvals feed, ad allocation, capture, store catalog, social channels

Additive: eight new tables, nothing existing is altered.

* ``design_templates`` / ``design_docs`` - Design Studio JSON canvas docs
  (size preset, brand kit ref -> ``user_presets``, exported asset keys).
* ``approval_items`` - unified approvals feed (idempotent per
  ``(user_id, source, external_ref)``).
* ``ad_allocation_proposals`` - daily cross-network budget split proposals
  (one per ``(user_id, run_date)``), gated by an approval item.
* ``capture_jobs`` - website / web game / App Store / Play Store capture to
  promo video + screenshots + listing metadata.
* ``store_catalog_imports`` / ``store_catalog_products`` - Shopify /
  WooCommerce bulk product imports.
* ``social_channel_credentials`` - Telegram / Discord / Mastodon posting
  targets with encrypted credentials, personal or shared to a workspace.

Revision ID: a7d3e9c1f2b4
Revises: 6e135be697a8
Create Date: 2026-09-25 14:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3e9c1f2b4'
down_revision: Union[str, None] = '6e135be697a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _owner_cols() -> list[sa.Column]:
    return [
        sa.Column("user_id", sa.String(length=32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), sa.ForeignKey("workspaces.id"), nullable=True),
    ]


def _owner_indexes(table: str) -> None:
    op.create_index(op.f(f"ix_{table}_user_id"), table, ["user_id"], unique=False)
    op.create_index(op.f(f"ix_{table}_workspace_id"), table, ["workspace_id"], unique=False)


def _empty(default: str) -> sa.TextClause:
    return sa.text(default)


def upgrade() -> None:
    # ---------------------------------------------------------------- design
    op.create_table(
        "design_templates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("size_preset", sa.String(length=20), server_default=_empty("'square'"), nullable=False),
        sa.Column("category", sa.String(length=40), server_default=_empty("'post'"), nullable=False),
        sa.Column("layout_json", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_design_templates_slug"),
    )
    op.create_index(op.f("ix_design_templates_user_id"), "design_templates", ["user_id"], unique=False)

    op.create_table(
        "design_docs",
        sa.Column("id", sa.String(length=32), nullable=False),
        *_owner_cols(),
        sa.Column("title", sa.String(length=200), server_default=_empty("''"), nullable=False),
        sa.Column("size_preset", sa.String(length=20), server_default=_empty("'square'"), nullable=False),
        sa.Column("width", sa.Integer(), server_default=sa.text("1080"), nullable=False),
        sa.Column("height", sa.Integer(), server_default=sa.text("1080"), nullable=False),
        sa.Column("canvas_json", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("template_id", sa.String(length=32),
                  sa.ForeignKey("design_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("brand_kit_id", sa.String(length=32),
                  sa.ForeignKey("user_presets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=_empty("'draft'"), nullable=False),
        sa.Column("thumb_key", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("exported_asset_key", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("exported_keys", sa.JSON(), server_default=_empty("'[]'"), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_ai_image", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    _owner_indexes("design_docs")

    # ------------------------------------------------------------- approvals
    op.create_table(
        "approval_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        *_owner_cols(),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_ref", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=300), server_default=_empty("''"), nullable=False),
        sa.Column("summary", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("risk", sa.String(length=12), server_default=_empty("'medium'"), nullable=False),
        sa.Column("payload", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("edited_payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=_empty("'pending'"), nullable=False),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("decided_via", sa.String(length=16), server_default=_empty("''"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("result", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("error", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source", "external_ref", name="uq_approval_items_owner_source_ref"),
    )
    _owner_indexes("approval_items")
    op.create_index(op.f("ix_approval_items_status"), "approval_items", ["status"], unique=False)

    # --------------------------------------------------------- ad allocation
    op.create_table(
        "ad_allocation_proposals",
        sa.Column("id", sa.String(length=32), nullable=False),
        *_owner_cols(),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("window_days", sa.Integer(), server_default=sa.text("7"), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=_empty("'USD'"), nullable=False),
        sa.Column("total_daily_budget_micros", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("network_stats", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("current_split", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("proposed_split", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("max_delta", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("method", sa.String(length=16), server_default=_empty("'thompson'"), nullable=False),
        sa.Column("reason", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=_empty("'proposed'"), nullable=False),
        sa.Column("approval_item_id", sa.String(length=32),
                  sa.ForeignKey("approval_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), server_default=_empty("''"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "run_date", name="uq_ad_allocation_proposals_owner_day"),
    )
    _owner_indexes("ad_allocation_proposals")

    # --------------------------------------------------------------- capture
    op.create_table(
        "capture_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        *_owner_cols(),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=_empty("'queued'"), nullable=False),
        sa.Column("progress", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("options", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("output_video_key", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("screenshots", sa.JSON(), server_default=_empty("'[]'"), nullable=False),
        sa.Column("metadata", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("error", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("task_id", sa.String(length=64), server_default=_empty("''"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "source_kind IN ('website', 'web_game', 'app_store', 'play_store')",
            name="ck_capture_jobs_source_kind",
        ),
    )
    _owner_indexes("capture_jobs")
    op.create_index(op.f("ix_capture_jobs_status"), "capture_jobs", ["status"], unique=False)

    # --------------------------------------------------------- store catalog
    op.create_table(
        "store_catalog_imports",
        sa.Column("id", sa.String(length=32), nullable=False),
        *_owner_cols(),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("store_url", sa.Text(), nullable=False),
        sa.Column("store_name", sa.String(length=200), server_default=_empty("''"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=_empty("'queued'"), nullable=False),
        sa.Column("requested_limit", sa.Integer(), server_default=sa.text("50"), nullable=False),
        sa.Column("product_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("options", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("error", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("provider IN ('shopify', 'woocommerce')", name="ck_store_catalog_imports_provider"),
    )
    _owner_indexes("store_catalog_imports")

    op.create_table(
        "store_catalog_products",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("import_id", sa.String(length=32),
                  sa.ForeignKey("store_catalog_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=500), server_default=_empty("''"), nullable=False),
        sa.Column("description", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=True),
        sa.Column("compare_at_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=_empty("''"), nullable=False),
        sa.Column("url", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("image_urls", sa.JSON(), server_default=_empty("'[]'"), nullable=False),
        sa.Column("tags", sa.JSON(), server_default=_empty("'[]'"), nullable=False),
        sa.Column("raw", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("adstudio_project_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", "external_id", name="uq_store_catalog_products_import_ext"),
    )
    op.create_index(op.f("ix_store_catalog_products_import_id"), "store_catalog_products",
                    ["import_id"], unique=False)
    op.create_index(op.f("ix_store_catalog_products_user_id"), "store_catalog_products",
                    ["user_id"], unique=False)

    # ------------------------------------------------------- social channels
    op.create_table(
        "social_channel_credentials",
        sa.Column("id", sa.String(length=32), nullable=False),
        *_owner_cols(),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=200), server_default=_empty("''"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=_empty("'connected'"), nullable=False),
        sa.Column("credentials_enc", sa.Text(), nullable=False),
        sa.Column("instance_url", sa.Text(), server_default=_empty("''"), nullable=False),
        sa.Column("target_id", sa.String(length=200), server_default=_empty("''"), nullable=False),
        sa.Column("target_name", sa.String(length=200), server_default=_empty("''"), nullable=False),
        sa.Column("meta", sa.JSON(), server_default=_empty("'{}'"), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), server_default=_empty("''"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", "target_id", name="uq_social_channel_credentials_owner_target"),
        sa.CheckConstraint("kind IN ('telegram', 'discord', 'mastodon')", name="ck_social_channel_credentials_kind"),
    )
    _owner_indexes("social_channel_credentials")


def downgrade() -> None:
    for table, indexes in (
        ("social_channel_credentials", ["user_id", "workspace_id"]),
        ("store_catalog_products", ["import_id", "user_id"]),
        ("store_catalog_imports", ["user_id", "workspace_id"]),
        ("capture_jobs", ["status", "user_id", "workspace_id"]),
        ("ad_allocation_proposals", ["user_id", "workspace_id"]),
        ("approval_items", ["status", "user_id", "workspace_id"]),
        ("design_docs", ["user_id", "workspace_id"]),
        ("design_templates", ["user_id"]),
    ):
        for col in indexes:
            op.drop_index(op.f(f"ix_{table}_{col}"), table_name=table)
        op.drop_table(table)
