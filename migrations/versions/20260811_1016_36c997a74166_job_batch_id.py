"""job batch_id

Revision ID: 36c997a74166
Revises: e5ae1b861df3
Create Date: 2026-08-11 10:16:30.795767+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36c997a74166'
down_revision: Union[str, None] = 'e5ae1b861df3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase-10 (batch variant review): link the N jobs a single ``variants``
    # request fans out to via a shared ``batch_id``. Nullable (single-variant
    # jobs stay NULL / belong to no batch) so the ADD COLUMN is safe on an
    # already-populated jobs table and existing rows are unaffected. Indexed so
    # ``JobRepository.list_by_batch`` is an O(index) lookup.
    op.add_column('jobs', sa.Column('batch_id', sa.String(length=32), nullable=True))
    op.create_index(op.f('ix_jobs_batch_id'), 'jobs', ['batch_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_jobs_batch_id'), table_name='jobs')
    op.drop_column('jobs', 'batch_id')
