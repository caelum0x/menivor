"""json -> jsonb for the six JSON columns carrying a server_default

PostgreSQL's ``json`` type has no equality operator. Alembic's server-default
drift check compares a column's stored default against the model default by
executing ``SELECT <stored> = <model>`` on the live connection; for any JSON
column with a ``server_default`` that becomes ``SELECT '{}'::json = '{}'``, which
raises ``operator does not exist: json = unknown`` and makes ``alembic check``
exit non-zero (a false-positive drift that is actually an unrunnable comparison).

``jsonb`` has ``=`` (and is the better type — normalised, indexable), so the
comparison runs and returns true. This migration converts exactly the six
columns that declare a ``server_default`` to ``jsonb``; every other JSON column
has no server_default and so never triggers the comparison. The models now
declare these columns via ``base.jsonb_variant()`` (``JSONB`` on PostgreSQL,
generic ``JSON`` elsewhere), matching this schema. Purely a storage-type change:
``{}`` / ``[]`` defaults and all existing values round-trip identically.

SQLite has no ``jsonb`` and stores these as generic ``JSON`` (and builds its
schema from ``Base.metadata`` in tests), so the conversion is skipped there.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-02 05:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, server_default) for every JSON column that carries a
# server_default and therefore trips Alembic's json-equality drift check.
_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("media_jobs", "provider_execution", "'{}'"),
    ("media_jobs", "settlement_intent", "'{}'"),
    ("media_jobs", "settlement_receipt", "'{}'"),
    ("media_jobs", "settlement_attestation", "'{}'"),
    ("webhook_subscriptions", "event_types", "'[]'"),
    ("webhook_deliveries", "payload", "'{}'"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    for table, column, default in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=postgresql.JSONB(),
            postgresql_using=f"{column}::jsonb",
            server_default=sa.text(default),
            existing_type=sa.JSON(),
            existing_nullable=False,
            existing_server_default=sa.text(default),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    for table, column, default in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.JSON(),
            postgresql_using=f"{column}::json",
            server_default=sa.text(default),
            existing_type=postgresql.JSONB(),
            existing_nullable=False,
            existing_server_default=sa.text(default),
        )
