"""Migration ``a2c4e6f8b0d1``: additive SEO (OpenSEO) tables matching the ORM, clean downgrade."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import app.domains.seo.models  # noqa: F401 - register tables
from app.models.db.base import Base

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
TABLES = ("seo_connections", "seo_audit_runs", "seo_keyword_research", "seo_rank_keywords", "seo_rank_snapshots")


def _load():
    path = next(VERSIONS.glob("*_a2c4e6f8b0d1_*.py"))
    spec = importlib.util.spec_from_file_location("mig_a2c4e6f8b0d1", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_upgrade_matches_models_and_downgrade_is_clean():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in ("users", "workspaces")])
    mig = _load()
    assert mig.down_revision == "e5a7c9f1b3d4"
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        mig.op = ops
        mig.upgrade()
        inspector = sa.inspect(conn)
        for table in TABLES:
            migrated = {c["name"] for c in inspector.get_columns(table)}
            modeled = {c.name for c in Base.metadata.tables[table].columns}
            assert migrated == modeled, table
            migrated_ix = {i["name"] for i in inspector.get_indexes(table)}
            modeled_ix = {i.name for i in Base.metadata.tables[table].indexes}
            assert modeled_ix <= migrated_ix, table
        mig.downgrade()
        assert not set(TABLES) & set(sa.inspect(conn).get_table_names())
