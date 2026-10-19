"""wallet_ledger_entries.job_id: drop FK to jobs (cross-table reconciliation pointer)

``wallet_ledger_entries.job_id`` links a ledger event to the job that caused it.
Two product surfaces write it: the classic pipeline sets a ``jobs.id`` while the
media gateway sets a ``media_jobs.id``. The original hard FK to ``jobs.id`` was
therefore wrong for every media-gateway reservation — it passed silently under
SQLite (FKs off by default) but raised ForeignKeyViolation on Postgres, breaking
the real image/video generation → reserve → settle flow end to end.

This drops the single-table FK and keeps ``job_id`` as an indexed nullable
string reconciliation pointer. The supporting index is left intact.

Revision ID: b1c2d3e4f5a6
Revises: a3e7c91fd240
Create Date: 2026-09-02 04:10:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a3e7c91fd240'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "wallet_ledger_entries"
_FK_NAME = "wallet_ledger_entries_job_id_fkey"


def upgrade() -> None:
    bind = op.get_bind()
    # SQLite does not enforce (or name) this FK; nothing to drop there.
    if bind.dialect.name == "sqlite":
        return
    op.drop_constraint(_FK_NAME, _TABLE, type_="foreignkey")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.create_foreign_key(
        _FK_NAME,
        _TABLE,
        "jobs",
        ["job_id"],
        ["id"],
    )
