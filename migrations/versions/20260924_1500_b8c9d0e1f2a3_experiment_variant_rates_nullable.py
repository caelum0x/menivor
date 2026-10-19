"""experiment variants: completion/rewatch rate nullable (NULL = not measured)

``experiment_variants.completion_rate`` and ``rewatch_rate`` were NOT NULL with
a ``0`` server default, so a variant no platform had reported for looked like a
measured 0% and was scored as the worst performer. Most platforms never report
rewatch per post, and completion only arrives for some.

This migration only relaxes constraints on existing columns:

* ``ALTER COLUMN ... DROP NOT NULL`` so "not measured" can be stored as NULL;
* ``ALTER COLUMN ... DROP DEFAULT`` so a freshly created variant starts as NULL
  (not measured) instead of being silently filled with 0.

No data is rewritten and no column/table is dropped, so it is safe on a
populated database. Existing zeros stay as they are.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-24 15:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "experiment_variants"
_COLUMNS = ("completion_rate", "rewatch_rate")


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        for column in _COLUMNS:
            batch.alter_column(
                column,
                existing_type=sa.Float(),
                nullable=True,
                server_default=None,
                existing_server_default=sa.text("0"),
            )


def downgrade() -> None:
    # NOT NULL cannot be restored while NULLs exist; "not measured" collapses
    # back to the old 0 representation first.
    for column in _COLUMNS:
        op.execute(sa.text(f"UPDATE {_TABLE} SET {column} = 0 WHERE {column} IS NULL"))
    with op.batch_alter_table(_TABLE) as batch:
        for column in _COLUMNS:
            batch.alter_column(
                column,
                existing_type=sa.Float(),
                nullable=False,
                server_default=sa.text("0"),
            )
