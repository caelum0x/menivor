"""OTT upload content checks and content-key versions (Wave Q QM1.2: P-M5, P-M6, P-M7)

``ott_upload_checks``: one content-check row per uploaded title (decision,
reasons, size and length for the per-user quota, review fields).
``ott_content_keys.version``: bumped on every key rotation so the key server
refuses a stale playlist. Additive and idempotent.

Revision ID: e2b4d6f8a0c3
Revises: d1a3c5e7f9b2
Create Date: 2026-10-03 10:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e2b4d6f8a0c3'
down_revision: Union[str, None] = 'd1a3c5e7f9b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    tables = set(inspector.get_table_names())
    if "ott_upload_checks" not in tables:
        op.create_table(
            "ott_upload_checks",
            sa.Column("title_id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), nullable=False),
            sa.Column("source_key", sa.String(512), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("seconds", sa.Float(), nullable=False, server_default="0"),
            sa.Column("decision", sa.String(8), nullable=False, server_default="pending"),
            sa.Column("reasons", sa.JSON(), nullable=False),
            sa.Column("frames_checked", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("transcript_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(32), nullable=False, server_default=""),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ott_upload_checks_user_id", "ott_upload_checks", ["user_id"])
        op.create_index("ix_ott_upload_checks_decision", "ott_upload_checks", ["decision", "created_at"])
    if "ott_content_keys" in tables:
        columns = {c["name"] for c in inspector.get_columns("ott_content_keys")}
        if "version" not in columns:
            op.add_column("ott_content_keys",
                          sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    inspector = _inspector()
    tables = set(inspector.get_table_names())
    if "ott_content_keys" in tables and "version" in {c["name"] for c in inspector.get_columns("ott_content_keys")}:
        op.drop_column("ott_content_keys", "version")
    if "ott_upload_checks" in tables:
        op.drop_index("ix_ott_upload_checks_decision", table_name="ott_upload_checks")
        op.drop_index("ix_ott_upload_checks_user_id", table_name="ott_upload_checks")
        op.drop_table("ott_upload_checks")
