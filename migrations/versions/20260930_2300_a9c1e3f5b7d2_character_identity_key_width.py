"""Widen ``characters.identity_key`` to 80 characters (Wave P P2, found closing P-M3)

A character with reference images carries a ``v2|`` prefixed key (67
characters), which Postgres refused in the old ``varchar(64)``, so creating a
real-face character failed on Postgres (SQLite does not enforce the length).
Widening only: no data changes, the index is kept, and a second run is a no-op.
The downgrade leaves the wider column in place (narrowing could truncate keys).

Revision ID: a9c1e3f5b7d2
Revises: a4c6e8f0b2d3
Create Date: 2026-09-30 23:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a9c1e3f5b7d2'
down_revision: Union[str, None] = 'a4c6e8f0b2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WIDTH = 80


def _current_length() -> int | None:
    bind = op.get_bind()
    if "characters" not in sa.inspect(bind).get_table_names():
        return None
    for column in sa.inspect(bind).get_columns("characters"):
        if column["name"] == "identity_key":
            return getattr(column["type"], "length", None)
    return None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return  # SQLite does not enforce varchar lengths
    length = _current_length()
    if length is not None and length < WIDTH:
        op.alter_column("characters", "identity_key", existing_type=sa.String(length=length),
                        type_=sa.String(length=WIDTH), existing_nullable=False)


def downgrade() -> None:
    # Narrowing back to 64 could truncate v2 keys; the wider column is harmless.
    pass
