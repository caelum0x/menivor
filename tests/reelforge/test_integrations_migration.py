"""Migration ``f4b6d8a0c2e5``: additive integrations tables matching the ORM, clean downgrade."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import app.domains.integrations.models  # noqa: F401 - register tables
from app.models.db.base import Base

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
TABLES = ("integration_connections", "integration_oauth_states", "integration_ad_accounts",
          "integration_ad_account_brands", "integration_ad_metrics", "integration_onboarding_grants")
# Columns added by later migrations (wave 2 ``b2d4f6a8c0e1`` adds ``reach``).
LATER_COLUMNS = {"integration_ad_metrics": {"reach"}}


def _load():
    path = next(VERSIONS.glob("*_f4b6d8a0c2e5_*.py"))
    spec = importlib.util.spec_from_file_location("mig_f4b6d8a0c2e5", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_upgrade_matches_models_and_downgrade_is_clean():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in ("users", "workspaces", "user_presets")])
    mig = _load()
    assert mig.down_revision == "e3a5c7d9f1b2"
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        mig.op = ops
        mig.upgrade()
        mig.upgrade()  # idempotent
        inspector = sa.inspect(conn)
        for table in TABLES:
            migrated = {c["name"] for c in inspector.get_columns(table)}
            modeled = {c.name for c in Base.metadata.tables[table].columns} - LATER_COLUMNS.get(table, set())
            assert migrated == modeled, table
            migrated_ix = {i["name"] for i in inspector.get_indexes(table)}
            modeled_ix = {i.name for i in Base.metadata.tables[table].indexes}
            assert modeled_ix <= migrated_ix, table
        mig.downgrade()
        assert not set(TABLES) & set(sa.inspect(conn).get_table_names())
