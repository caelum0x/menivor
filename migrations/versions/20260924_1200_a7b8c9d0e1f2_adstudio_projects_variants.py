"""ad studio: product ad projects + ad variants

Additive schema for the URL-to-product-ad "Ad Studio":

* ``adstudio_projects`` — a product (scraped from a store URL or entered
  manually), its generated ad angles and the product images imported into the
  owner's media library.
* ``adstudio_variants`` — one ad per (angle x format x aspect) with its render
  state, output keys and (for UGC-avatar ads) the linked reel job id.

New tables only; nothing existing is altered, so the migration is safe on a
populated database. JSON columns carry a server default so raw inserts that
omit them stay valid.

Revision ID: a7b8c9d0e1f2
Revises: f5a6b7c8d9e0
Create Date: 2026-09-24 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "adstudio_projects",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("source_url", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("source", sa.String(length=20), server_default=sa.text("'generic'"), nullable=False),
        sa.Column("language", sa.String(length=8), server_default=sa.text("'en'"), nullable=False),
        sa.Column("product", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("angles", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("images", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_adstudio_projects_user_id"), "adstudio_projects", ["user_id"], unique=False)
    op.create_index(op.f("ix_adstudio_projects_created_at"), "adstudio_projects", ["created_at"], unique=False)

    op.create_table(
        "adstudio_variants",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("angle_id", sa.String(length=16), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("aspect", sa.String(length=8), server_default=sa.text("'9:16'"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("script", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("spec", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("output_key", sa.String(length=512), server_default=sa.text("''"), nullable=False),
        sa.Column("poster_key", sa.String(length=512), server_default=sa.text("''"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("job_id", sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column("error", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["adstudio_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_adstudio_variants_project_id"), "adstudio_variants", ["project_id"], unique=False)
    op.create_index(op.f("ix_adstudio_variants_user_id"), "adstudio_variants", ["user_id"], unique=False)
    op.create_index(op.f("ix_adstudio_variants_status"), "adstudio_variants", ["status"], unique=False)
    op.create_index(op.f("ix_adstudio_variants_job_id"), "adstudio_variants", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_adstudio_variants_job_id"), table_name="adstudio_variants")
    op.drop_index(op.f("ix_adstudio_variants_status"), table_name="adstudio_variants")
    op.drop_index(op.f("ix_adstudio_variants_user_id"), table_name="adstudio_variants")
    op.drop_index(op.f("ix_adstudio_variants_project_id"), table_name="adstudio_variants")
    op.drop_table("adstudio_variants")
    op.drop_index(op.f("ix_adstudio_projects_created_at"), table_name="adstudio_projects")
    op.drop_index(op.f("ix_adstudio_projects_user_id"), table_name="adstudio_projects")
    op.drop_table("adstudio_projects")
