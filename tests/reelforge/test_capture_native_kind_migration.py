"""Migration ``c1f6a2b4d8e0``: capture_jobs accepts ``native_game`` and keeps legacy ``web_game`` rows valid.

Runs the Wave L migration, then this one, against in-memory SQLite (batch mode
recreates the table there; Postgres gets a plain constraint swap).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domains.capture.models import SOURCE_KINDS
from app.models.db.base import Base

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
PREREQS = ("users", "workspaces", "user_presets")


def _load(revision: str):
    path = next(VERSIONS.glob(f"*_{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _insert(conn, row_id: str, kind: str) -> None:
    conn.execute(sa.text(
        "INSERT INTO capture_jobs (id, user_id, source_url, source_kind, status, progress, options, "
        "output_video_key, screenshots, metadata, error, task_id) VALUES "
        "(:id, 'u1', 'x', :kind, 'queued', 0, '{}', '', '[]', '{}', '', '')"
    ), {"id": row_id, "kind": kind})


@pytest.fixture()
def conn():
    engine = sa.create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _record):
        dbapi_conn.create_function("now", 0, lambda: "2026-09-25 00:00:00")

    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in PREREQS])
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            _load("a7d3e9c1f2b4").upgrade()
            _insert(connection, "legacy", "web_game")
            _load("c1f6a2b4d8e0").upgrade()
        yield connection


def test_chain_and_kinds():
    migration = _load("c1f6a2b4d8e0")
    assert migration.down_revision == "b8e4f0a2c3d5"
    assert "native_game" in SOURCE_KINDS and "web_game" not in SOURCE_KINDS


def test_native_game_allowed_and_legacy_rows_kept(conn):
    _insert(conn, "native", "native_game")
    kinds = dict(conn.execute(sa.text("SELECT id, source_kind FROM capture_jobs")).all())
    assert kinds == {"legacy": "web_game", "native": "native_game"}
    with pytest.raises(sa.exc.IntegrityError):
        with conn.begin_nested():
            _insert(conn, "bad", "tiktok")
