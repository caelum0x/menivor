"""Brand Agent: brand spaces, versioned brand memory, sessions, messages, approval actions,
routines, inspirations, skills, folders and library items.

Additive and idempotent (each table is created only when missing).

Merge note: branched from head ``e3a5c7d9f1b2``; linearized onto the integrations
revision ``f4b6d8a0c2e5`` in the menivor-wave merge. If another branch lands a
revision on the same head first, point ``down_revision`` at that branch's head
so the graph keeps exactly one head.

Revision ID: f7b9d1e3a5c8
Revises: f4b6d8a0c2e5
Create Date: 2026-10-06 09:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f7b9d1e3a5c8'
down_revision: Union[str, None] = 'f4b6d8a0c2e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _now():
    return sa.func.now()


def _id():
    return sa.Column("id", sa.String(32), primary_key=True)


def _user():
    return sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False)


def _space():
    return sa.Column("space_id", sa.String(32), sa.ForeignKey("agent_brand_spaces.id"), nullable=False)


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now())


def upgrade() -> None:
    tables = _tables()
    if "agent_brand_spaces" not in tables:
        op.create_table(
            "agent_brand_spaces",
            _id(), _user(),
            sa.Column("workspace_id", sa.String(32), sa.ForeignKey("workspaces.id"), nullable=True),
            sa.Column("name", sa.String(200), nullable=False, server_default=""),
            sa.Column("website_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("brain_seen_version", sa.Integer(), nullable=False, server_default="0"),
            _created(),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        )
        op.create_index("ix_agent_brand_spaces_user_id", "agent_brand_spaces", ["user_id"])
        op.create_index("ix_agent_brand_spaces_workspace_id", "agent_brand_spaces", ["workspace_id"])
    if "agent_brand_memory" not in tables:
        op.create_table(
            "agent_brand_memory",
            _id(), _space(), _user(),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("section", sa.String(32), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(16), nullable=False, server_default="agent"),
            _created(),
            sa.UniqueConstraint("space_id", "version", name="uq_agent_brand_memory_space_version"),
        )
        op.create_index("ix_agent_brand_memory_user_id", "agent_brand_memory", ["user_id"])
        op.create_index("ix_agent_brand_memory_space_section", "agent_brand_memory", ["space_id", "section"])
    if "agent_sessions" not in tables:
        op.create_table(
            "agent_sessions",
            _id(), _user(), _space(),
            sa.Column("title", sa.String(200), nullable=False, server_default=""),
            sa.Column("state", sa.JSON(), nullable=False),
            _created(),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        )
        op.create_index("ix_agent_sessions_space_id", "agent_sessions", ["space_id"])
        op.create_index("ix_agent_sessions_user_updated", "agent_sessions", ["user_id", "updated_at"])
    if "agent_messages" not in tables:
        op.create_table(
            "agent_messages",
            _id(),
            sa.Column("session_id", sa.String(32), sa.ForeignKey("agent_sessions.id"), nullable=False),
            _user(),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("card", sa.JSON(), nullable=True),
            sa.Column("chips", sa.JSON(), nullable=False),
            sa.Column("action_id", sa.String(32), nullable=True),
            _created(),
            sa.UniqueConstraint("session_id", "seq", name="uq_agent_messages_session_seq"),
        )
        op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"])
    if "agent_actions" not in tables:
        op.create_table(
            "agent_actions",
            _id(), _user(), _space(),
            sa.Column("session_id", sa.String(32), nullable=True),
            sa.Column("routine_id", sa.String(32), nullable=True),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("title", sa.String(300), nullable=False, server_default=""),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("credits_estimate", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            _created(),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_agent_actions_space_id", "agent_actions", ["space_id"])
        op.create_index("ix_agent_actions_user_status", "agent_actions", ["user_id", "status"])
    if "agent_routines" not in tables:
        op.create_table(
            "agent_routines",
            _id(), _user(), _space(),
            sa.Column("name", sa.String(200), nullable=False, server_default=""),
            sa.Column("skill", sa.String(64), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("weekday", sa.Integer(), nullable=True),
            sa.Column("hour", sa.Integer(), nullable=False, server_default="9"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            _created(),
        )
        op.create_index("ix_agent_routines_user_id", "agent_routines", ["user_id"])
        op.create_index("ix_agent_routines_due", "agent_routines", ["enabled", "next_run_at"])
    if "agent_inspirations" not in tables:
        op.create_table(
            "agent_inspirations",
            _id(), _user(), _space(),
            sa.Column("kind", sa.String(16), nullable=False, server_default="link"),
            sa.Column("source", sa.String(16), nullable=False, server_default="user"),
            sa.Column("url", sa.String(2048), nullable=False),
            sa.Column("title", sa.String(300), nullable=False, server_default=""),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("thumbnail_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("metrics", sa.JSON(), nullable=False),
            _created(),
            sa.UniqueConstraint("space_id", "url", name="uq_agent_inspirations_space_url"),
        )
        op.create_index("ix_agent_inspirations_user_id", "agent_inspirations", ["user_id"])
    if "agent_skills" not in tables:
        op.create_table(
            "agent_skills",
            _id(), _user(),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
            _created(),
        )
        op.create_index("ix_agent_skills_user_id", "agent_skills", ["user_id"])
    if "agent_folders" not in tables:
        op.create_table(
            "agent_folders",
            _id(), _user(), _space(),
            sa.Column("name", sa.String(120), nullable=False),
            _created(),
        )
        op.create_index("ix_agent_folders_user_id", "agent_folders", ["user_id"])
    if "agent_library_items" not in tables:
        op.create_table(
            "agent_library_items",
            _id(), _user(), _space(),
            sa.Column("folder_id", sa.String(32), sa.ForeignKey("agent_folders.id"), nullable=True),
            sa.Column("action_id", sa.String(32), nullable=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("ref", sa.String(200), nullable=False, server_default=""),
            sa.Column("url", sa.Text(), nullable=False, server_default=""),
            sa.Column("title", sa.String(300), nullable=False, server_default=""),
            _created(),
        )
        op.create_index("ix_agent_library_items_user_id", "agent_library_items", ["user_id"])


def downgrade() -> None:
    tables = _tables()
    for name in ("agent_library_items", "agent_folders", "agent_skills", "agent_inspirations", "agent_routines",
                 "agent_actions", "agent_messages", "agent_sessions", "agent_brand_memory", "agent_brand_spaces"):
        if name in tables:
            op.drop_table(name)
