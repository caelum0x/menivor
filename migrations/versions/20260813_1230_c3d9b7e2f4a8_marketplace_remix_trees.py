"""marketplace remix trees (parent_template_id + remix_count)

Revision ID: c3d9b7e2f4a8
Revises: a1f4d8e6c3b9
Create Date: 2026-08-13 12:30:00.000000+00:00

"""
from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d9b7e2f4a8'
down_revision: Union[str, None] = 'a1f4d8e6c3b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Marketplace Remix Trees: two additive columns on ``marketplace_templates``.
    #
    # ``parent_template_id`` (nullable, indexed, self-FK -> marketplace_templates.id):
    # when a listing was published from a private preset that was itself CLONED
    # from another marketplace listing, this records the PARENT listing it descends
    # from, forming a remix tree. NULL for an original (non-cloned) publish. No
    # cycles are possible — a parent is always an already-published, strictly-older
    # row. ``remix_count`` (NOT NULL, server_default 0) counts how many published
    # listings directly descend from a listing, backing the ``most_remixed`` sort.
    #
    # ``batch_alter_table`` (named self-FK) is used so the ADD COLUMN + self-FK +
    # index apply on Postgres/Neon *and* on the SQLite verify/test engine (which
    # cannot ADD a FOREIGN KEY in place). Both columns are additive with safe
    # defaults so the migration is safe on an already-populated table and existing
    # rows / prior tests are unaffected; ``server_default`` keeps the row shape
    # self-describing so Alembic autogenerate reports no drift.
    with op.batch_alter_table("marketplace_templates", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("parent_template_id", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "remix_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_marketplace_templates_parent_template_id"),
            ["parent_template_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_marketplace_templates_parent_template_id_self",
            "marketplace_templates",
            ["parent_template_id"],
            ["id"],
        )

    _backfill_parent_links()


def _backfill_parent_links() -> None:
    """Best-effort backfill of ``parent_template_id`` for pre-existing clones.

    A listing carries no stored pointer to the preset it was published from, so we
    reconstruct the link heuristically: a listing published from a preset shares
    that preset's owner (``author_user_id == user_presets.user_id``) and name
    (``title == user_presets.name``, the ``seed_title`` copied at publish time). If
    such a preset's opaque ``config`` carries a ``source_marketplace_id`` that
    names an existing, still-``published`` listing, that source is this listing's
    remix parent.

    Fully best-effort and safe: an unresolvable / ambiguous / unpublished /
    self-referential match is simply left NULL. ``remix_count`` is intentionally
    left at its 0 default here (the forward publish path maintains it going
    forward); the backfill only reconstructs the parent pointer.
    """
    bind = op.get_bind()

    listings = bind.execute(
        sa.text(
            "SELECT id, author_user_id, title, published, created_at "
            "FROM marketplace_templates"
        )
    ).mappings().all()
    if not listings:
        return
    published_ids = {row["id"] for row in listings if row["published"]}
    created_at_by_id = {row["id"]: row["created_at"] for row in listings}

    presets = bind.execute(
        sa.text("SELECT user_id, name, config FROM user_presets")
    ).mappings().all()

    # Map (owner, preset_name) -> source_marketplace_id carried in the config.
    # A later preset with the same (owner, name) overwrites an earlier one; this is
    # best-effort provenance, so the most recent matching config wins.
    source_by_owner_name: dict[tuple, str] = {}
    for preset in presets:
        config = _as_dict(preset["config"])
        source_id = config.get("source_marketplace_id")
        if isinstance(source_id, str) and source_id.strip():
            source_by_owner_name[(preset["user_id"], preset["name"])] = (
                source_id.strip()
            )
    if not source_by_owner_name:
        return

    for row in listings:
        source_id = source_by_owner_name.get((row["author_user_id"], row["title"]))
        if not source_id:
            continue
        if source_id not in published_ids:
            continue  # parent must exist + be published
        if source_id == row["id"]:
            continue  # never self-reference
        # Strictly-older invariant: a remix parent is always a row that existed
        # BEFORE its child, which the whole design relies on for cycle-freedom
        # (models.py). Never link a row to a source that was created strictly
        # AFTER it — a forward-in-time ref, which across authors could otherwise
        # chain into a persisted cycle. (Equal timestamps are permitted so a
        # legitimate parent/child published in the same clock-second still links;
        # the runtime lineage walk keeps its visited-set + depth cap as a final
        # backstop.) ISO/`datetime` created_at values compare chronologically.
        source_created = created_at_by_id.get(source_id)
        row_created = row["created_at"]
        if (
            source_created is not None
            and row_created is not None
            and source_created > row_created
        ):
            continue
        bind.execute(
            sa.text(
                "UPDATE marketplace_templates SET parent_template_id = :pid "
                "WHERE id = :id"
            ),
            {"pid": source_id, "id": row["id"]},
        )


def _as_dict(value: object) -> dict:
    """Coerce a JSON column value (dict on Postgres, str on SQLite) to a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def downgrade() -> None:
    with op.batch_alter_table("marketplace_templates", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_marketplace_templates_parent_template_id_self", type_="foreignkey"
        )
        batch_op.drop_index(
            batch_op.f("ix_marketplace_templates_parent_template_id")
        )
        batch_op.drop_column("remix_count")
        batch_op.drop_column("parent_template_id")
