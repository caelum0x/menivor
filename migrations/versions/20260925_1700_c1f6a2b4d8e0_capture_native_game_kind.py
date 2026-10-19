"""Capture: allow the ``native_game`` source kind (simulator/emulator recording)

Our games are native mobile apps, so game captures now record an iOS Simulator
or Android emulator instead of a web page. ``web_game`` stays allowed so old
rows remain valid; the API no longer creates or retries them.

Replaces ``ck_capture_jobs_source_kind``; nothing else changes.

Revision ID: c1f6a2b4d8e0
Revises: b8e4f0a2c3d5
Create Date: 2026-09-25 17:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c1f6a2b4d8e0'
down_revision: Union[str, None] = 'b8e4f0a2c3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CK = "ck_capture_jobs_source_kind"
_NEW = "source_kind IN ('website', 'native_game', 'web_game', 'app_store', 'play_store')"
_OLD = "source_kind IN ('website', 'web_game', 'app_store', 'play_store')"


def upgrade() -> None:
    with op.batch_alter_table("capture_jobs", schema=None) as batch_op:
        batch_op.drop_constraint(_CK, type_="check")
        batch_op.create_check_constraint(_CK, _NEW)


def downgrade() -> None:
    # Fails while native_game rows exist; delete or re-kind them first.
    with op.batch_alter_table("capture_jobs", schema=None) as batch_op:
        batch_op.drop_constraint(_CK, type_="check")
        batch_op.create_check_constraint(_CK, _OLD)
