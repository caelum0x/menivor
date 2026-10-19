"""Brand Agent migration ``f7b9d1e3a5c8``: idempotent, reversible, and matches the models."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domains.brand_agent import models as agent_models
from app.models.db import models as core_models  # noqa: F401  (users/workspaces)
from app.models.db.base import Base

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "migrations" / "versions" / "20261006_0900_f7b9d1e3a5c8_brand_agent.py"
TABLES = sorted(cls.__tablename__ for cls in (getattr(agent_models, n) for n in agent_models.__all__))


def _load():
    spec = importlib.util.spec_from_file_location("brand_agent_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_creates_every_model_table_with_the_model_columns():
    migration = _load()
    assert migration.down_revision == "f4b6d8a0c2e5"
    engine = sa.create_engine("sqlite://")
    Base.metadata.tables["users"].create(engine)
    Base.metadata.tables["workspaces"].create(engine)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()  # idempotent
        inspector = sa.inspect(conn)
        assert sorted(t for t in inspector.get_table_names() if t.startswith("agent_")) == TABLES
        for name in TABLES:
            migrated = {c["name"] for c in inspector.get_columns(name)}
            modeled = {c.name for c in Base.metadata.tables[name].columns}
            assert migrated == modeled, name
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        assert not [t for t in sa.inspect(conn).get_table_names() if t.startswith("agent_")]
