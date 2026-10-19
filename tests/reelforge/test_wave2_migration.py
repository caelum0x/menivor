"""Migration ``b2d4f6a8c0e1`` (Menivor wave 2): tables match the models, reach column, idempotent, reversible."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domains.actors import models as _actors  # noqa: F401
from app.domains.competitors import models as _competitors  # noqa: F401
from app.domains.creative_review import models as _reviews  # noqa: F401
from app.domains.integrations import models as _integrations  # noqa: F401
from app.domains.mcp_hosted import models as _mcp  # noqa: F401
from app.domains.studio_render import models as _renders  # noqa: F401
from app.domains.workflows import models as _workflows  # noqa: F401
from app.models.db.base import Base

PATH = next((Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*_b2d4f6a8c0e1_*.py"))


def _load():
    spec = importlib.util.spec_from_file_location("mig_b2d4f6a8c0e1", PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_upgrade_matches_models_adds_reach_and_downgrades():
    mig = _load()
    assert mig.down_revision == "a1c3e5f7b9d2"
    engine = sa.create_engine("sqlite://")
    base_tables = ("users", "workspaces", "user_presets", "integration_connections", "integration_ad_accounts")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in base_tables])
    metrics = Base.metadata.tables["integration_ad_metrics"]
    old_metrics = sa.Table("integration_ad_metrics", sa.MetaData(),
                           *[sa.Column(c.name, c.type) for c in metrics.columns if c.name != "reach"])
    old_metrics.create(engine)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()  # idempotent
        inspector = sa.inspect(conn)
        for table in mig.TABLES:
            migrated = {c["name"] for c in inspector.get_columns(table)}
            modeled = {c.name for c in Base.metadata.tables[table].columns}
            assert migrated == modeled, table
            modeled_ix = {i.name for i in Base.metadata.tables[table].indexes}
            assert modeled_ix <= {i["name"] for i in inspector.get_indexes(table)}, table
        assert "reach" in {c["name"] for c in inspector.get_columns("integration_ad_metrics")}
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
        inspector = sa.inspect(conn)
        assert not set(mig.TABLES) & set(inspector.get_table_names())
        assert "reach" not in {c["name"] for c in inspector.get_columns("integration_ad_metrics")}


def test_partly_applied_schema_is_completed():
    mig = _load()
    engine = sa.create_engine("sqlite://")
    base_tables = ("users", "workspaces", "user_presets", "integration_connections", "integration_ad_accounts",
                   "integration_ad_metrics", "competitor_brands", "agent_workflows")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in base_tables])
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
        names = set(sa.inspect(conn).get_table_names())
    assert {"competitor_ads", "workflow_runs"} <= names
