"""Menivor wave 2: creative reviews, competitor tracker, AI actors, studio renders,
workflow canvas, hosted MCP tokens, and ``reach`` on the ad metrics table.

Additive and idempotent (each table / column is created only when missing).

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-10-06 18:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c0e1'
down_revision: Union[str, None] = 'a1c3e5f7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("creative_reviews", "competitor_brands", "competitor_ads", "ai_actors", "studio_renders",
          "agent_workflows", "workflow_runs", "mcp_tokens")


def _now() -> sa.sql.elements.ClauseElement:
    return sa.func.now()


def _id() -> sa.Column:
    return sa.Column("id", sa.String(32), primary_key=True)


def _created(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=_now())


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _creative_reviews() -> None:
    op.create_table(
        "creative_reviews", _id(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("library_item_id", sa.String(32), nullable=False),
        sa.Column("space_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(32), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("regenerate_action_id", sa.String(32), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        sa.UniqueConstraint("library_item_id", name="uq_creative_reviews_item"),
    )
    op.create_index("ix_creative_reviews_user_id", "creative_reviews", ["user_id"])
    op.create_index("ix_creative_reviews_space_id", "creative_reviews", ["space_id"])


def _competitor_brands() -> None:
    op.create_table(
        "competitor_brands", _id(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(32), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("meta_page_ids", sa.JSON(), nullable=False),
        sa.Column("tiktok_advertiser_ids", sa.JSON(), nullable=False),
        sa.Column("search_terms", sa.String(200), nullable=False, server_default=""),
        sa.Column("countries", sa.JSON(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        _created(),
    )
    op.create_index("ix_competitor_brands_user_id", "competitor_brands", ["user_id"])
    op.create_index("ix_competitor_brands_workspace_id", "competitor_brands", ["workspace_id"])


def _competitor_ads() -> None:
    op.create_table(
        "competitor_ads", _id(),
        sa.Column("brand_id", sa.String(32), sa.ForeignKey("competitor_brands.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("advertiser", sa.String(300), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("page_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("thumbnail_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("platforms", sa.JSON(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw", sa.JSON(), nullable=False),
        _created("first_seen_at"),
        _created("last_seen_at"),
        sa.UniqueConstraint("brand_id", "source", "external_id", name="uq_competitor_ads_brand_source_ext"),
    )
    op.create_index("ix_competitor_ads_brand_id", "competitor_ads", ["brand_id"])
    op.create_index("ix_competitor_ads_user_new", "competitor_ads", ["user_id", "is_new"])


def _actors() -> None:
    op.create_table(
        "ai_actors", _id(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(32), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("persona", sa.Text(), nullable=False, server_default=""),
        sa.Column("look_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("voice_design_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("voice_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("product_shot_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("face_image_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("consent", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        _created(),
    )
    op.create_index("ix_ai_actors_user_id", "ai_actors", ["user_id"])
    op.create_index("ix_ai_actors_workspace_id", "ai_actors", ["workspace_id"])


def _studio_renders() -> None:
    op.create_table(
        "studio_renders", _id(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("quote_usd", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("credits", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("approval_item_id", sa.String(32), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        _created(),
        _created("updated_at"),
    )
    op.create_index("ix_studio_renders_user_id", "studio_renders", ["user_id"])


def _agent_workflows() -> None:
    op.create_table(
        "agent_workflows", _id(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("space_id", sa.String(32), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("hour", sa.Integer(), nullable=False, server_default=sa.text("9")),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        _created("updated_at"),
    )
    op.create_index("ix_agent_workflows_user_id", "agent_workflows", ["user_id"])
    op.create_index("ix_agent_workflows_due", "agent_workflows", ["schedule_enabled", "next_run_at"])


def _workflow_runs() -> None:
    op.create_table(
        "workflow_runs", _id(),
        sa.Column("workflow_id", sa.String(32), sa.ForeignKey("agent_workflows.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        _created(),
    )
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])


def _mcp_tokens() -> None:
    op.create_table(
        "mcp_tokens", _id(),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(32), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        _created(),
    )
    op.create_index("ix_mcp_tokens_user_id", "mcp_tokens", ["user_id"])
    op.create_index("ix_mcp_tokens_workspace_id", "mcp_tokens", ["workspace_id"])


# One creator per table (parents before children), so a partly-applied schema is completed.
_CREATORS = (
    ("creative_reviews", _creative_reviews),
    ("competitor_brands", _competitor_brands),
    ("competitor_ads", _competitor_ads),
    ("ai_actors", _actors),
    ("studio_renders", _studio_renders),
    ("agent_workflows", _agent_workflows),
    ("workflow_runs", _workflow_runs),
    ("mcp_tokens", _mcp_tokens),
)


def upgrade() -> None:
    existing = _tables()
    for table, create in _CREATORS:
        if table not in existing:
            create()
    if "integration_ad_metrics" in existing:
        cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("integration_ad_metrics")}
        if "reach" not in cols:
            with op.batch_alter_table("integration_ad_metrics") as batch:
                batch.add_column(sa.Column("reach", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    existing = _tables()
    if "integration_ad_metrics" in existing:
        cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("integration_ad_metrics")}
        if "reach" in cols:
            with op.batch_alter_table("integration_ad_metrics") as batch:
                batch.drop_column("reach")
    for table in ("workflow_runs", "agent_workflows", "competitor_ads", "competitor_brands", "creative_reviews",
                  "ai_actors", "studio_renders", "mcp_tokens"):
        if table in existing:
            op.drop_table(table)
