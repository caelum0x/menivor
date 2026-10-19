"""Migration ``a1c7e3f9b5d2``: additive tracked_posts + post_snapshots, matching the ORM."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.db.base import Base

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _load():
    path = next(VERSIONS.glob("*_a1c7e3f9b5d2_*.py"))
    spec = importlib.util.spec_from_file_location("mig_a1c7e3f9b5d2", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_upgrade_matches_models_and_downgrade_is_clean():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["users"]])
    mig = _load()
    assert mig.down_revision == "e5f9b3c7d1a2"
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        mig.op = ops  # alembic's proxy is bound per run; bind it to this connection
        mig.upgrade()
        inspector = sa.inspect(conn)
        for table in ("tracked_posts", "post_snapshots"):
            migrated = {c["name"] for c in inspector.get_columns(table)}
            modeled = {c.name for c in Base.metadata.tables[table].columns}
            assert migrated == modeled, table
            migrated_ix = {i["name"] for i in inspector.get_indexes(table)}
            modeled_ix = {i.name for i in Base.metadata.tables[table].indexes}
            assert modeled_ix <= migrated_ix, table
        mig.downgrade()
        assert "tracked_posts" not in sa.inspect(conn).get_table_names()
