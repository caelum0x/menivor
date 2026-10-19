"""Migration ``a1c3e5f7b9d2``: the Brand Agent's product presets table matches the model, reversibly."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domains.adclone.preset_store import AdClonePreset
from app.models.db.base import Base

PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "20261006_1500_a1c3e5f7b9d2_adclone_presets.py"


def _load():
    spec = importlib.util.spec_from_file_location("mig_a1c3e5f7b9d2", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_creates_the_model_table_idempotently_and_downgrades():
    mig = _load()
    assert mig.down_revision == "f7b9d1e3a5c8"
    engine = sa.create_engine("sqlite://")
    Base.metadata.tables["users"].create(engine)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()  # idempotent
    cols = {c["name"] for c in sa.inspect(engine).get_columns("adclone_presets")}
    assert cols == {c.name for c in AdClonePreset.__table__.columns}
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
    assert "adclone_presets" not in sa.inspect(engine).get_table_names()
