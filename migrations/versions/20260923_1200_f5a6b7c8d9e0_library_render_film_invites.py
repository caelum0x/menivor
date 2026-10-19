"""library mgmt + render history + film export + workspace invites

Additive schema for the round-2 product gaps:

* ``jobs`` — ``title`` (owner display name), ``archived_at`` (hidden from the
  default library view) and ``deleted_at`` (soft delete; rows kept because
  job_events / assets / credit_ledger / publishes / shares reference jobs.id).
* ``render_jobs`` — ``source`` (``render`` | ``film``) + ``label`` for the
  owner-scoped render history list; ``id`` widened 32 -> 64 because the id is the
  backend spec ``job_id`` (a correlation id or a ``film-...`` shot id) which can
  exceed a bare uuid. Existing film shot renders are backfilled to ``film``.
* ``film_projects`` — ``export_state`` / ``export_error`` / ``final_key`` /
  ``exported_at`` for the stitched final export; the misleading legacy
  ``assembled`` status is renamed ``shots_ready``.
* ``workspace_invites`` — pending invites for people without an account (only a
  SHA-256 of the one-time token is stored).

Every ADD COLUMN is nullable or carries a server default, so the migration is
safe on populated tables.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-23 12:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- jobs: library management -------------------------------------------
    op.add_column(
        "jobs",
        sa.Column("title", sa.String(length=200), server_default=sa.text("''"), nullable=False),
    )
    op.add_column("jobs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_jobs_deleted_at"), "jobs", ["deleted_at"], unique=False)

    # -- render_jobs: history metadata + wider id -----------------------------
    op.alter_column(
        "render_jobs", "id",
        existing_type=sa.String(length=32), type_=sa.String(length=64), existing_nullable=False,
    )
    op.add_column(
        "render_jobs",
        sa.Column("source", sa.String(length=20), server_default=sa.text("'render'"), nullable=False),
    )
    op.add_column(
        "render_jobs",
        sa.Column("label", sa.String(length=200), server_default=sa.text("''"), nullable=False),
    )
    op.create_index(op.f("ix_render_jobs_source"), "render_jobs", ["source"], unique=False)
    op.execute(
        "UPDATE render_jobs SET source = 'film' "
        "WHERE id IN (SELECT render_job_id FROM film_shots WHERE render_job_id <> '')"
    )

    # -- film_projects: final export ------------------------------------------
    op.add_column(
        "film_projects",
        sa.Column("export_state", sa.String(length=20), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "film_projects",
        sa.Column("export_error", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "film_projects",
        sa.Column("final_key", sa.String(length=512), server_default=sa.text("''"), nullable=False),
    )
    op.add_column(
        "film_projects", sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE film_projects SET status = 'shots_ready' WHERE status = 'assembled'")

    # -- workspace_invites -----------------------------------------------------
    op.create_table(
        "workspace_invites",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by", sa.String(length=32), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(length=32), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_workspace_invites_workspace_id"), "workspace_invites", ["workspace_id"], unique=False
    )
    op.create_index(op.f("ix_workspace_invites_email"), "workspace_invites", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workspace_invites_email"), table_name="workspace_invites")
    op.drop_index(op.f("ix_workspace_invites_workspace_id"), table_name="workspace_invites")
    op.drop_table("workspace_invites")

    op.execute("UPDATE film_projects SET status = 'assembled' WHERE status IN ('shots_ready', 'exporting', 'exported')")
    op.drop_column("film_projects", "exported_at")
    op.drop_column("film_projects", "final_key")
    op.drop_column("film_projects", "export_error")
    op.drop_column("film_projects", "export_state")

    op.drop_index(op.f("ix_render_jobs_source"), table_name="render_jobs")
    op.drop_column("render_jobs", "label")
    op.drop_column("render_jobs", "source")
    # Narrowing back is only safe when no id exceeds 32 chars.
    op.execute("DELETE FROM render_jobs WHERE length(id) > 32")
    op.alter_column(
        "render_jobs", "id",
        existing_type=sa.String(length=64), type_=sa.String(length=32), existing_nullable=False,
    )

    op.drop_index(op.f("ix_jobs_deleted_at"), table_name="jobs")
    op.drop_column("jobs", "deleted_at")
    op.drop_column("jobs", "archived_at")
    op.drop_column("jobs", "title")
