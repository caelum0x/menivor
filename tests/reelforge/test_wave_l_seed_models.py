"""Wave L seed: the new models import, match migration ``a7d3e9c1f2b4`` and round-trip.

Runs the migration's ``upgrade()``/``downgrade()`` against in-memory SQLite (no
live database is touched) and asserts Alembic autogenerate sees zero drift
between the migration and the SQLAlchemy models.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.ads.allocation_models import AdAllocationProposal
from app.domains.adstudio.catalog_models import StoreCatalogImport, StoreCatalogProduct
from app.domains.approvals.models import ApprovalItem, STATUS_PENDING
from app.domains.capture.models import CaptureJob, SOURCE_KINDS
from app.domains.design.models import SIZE_PRESETS, DesignDoc, DesignTemplate
from app.domains.publishing.extended.channel_models import CHANNEL_KINDS, SocialChannelCredential
from app.models.db.base import Base
from app.models.db.models import User

NEW_TABLES = {
    "design_docs",
    "design_templates",
    "approval_items",
    "ad_allocation_proposals",
    "capture_jobs",
    "store_catalog_imports",
    "store_catalog_products",
    "social_channel_credentials",
}
PREREQS = ("users", "workspaces", "user_presets")
MIGRATION = next(
    (Path(__file__).resolve().parents[2] / "migrations" / "versions").glob("*_a7d3e9c1f2b4_*.py")
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("wave_l_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def migrated_conn():
    engine = sa.create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _record):  # the migration's server defaults are Postgres now()
        dbapi_conn.create_function("now", 0, lambda: "2026-09-25 00:00:00")

    Base.metadata.create_all(engine, tables=[Base.metadata.tables[t] for t in PREREQS])
    migration = _load_migration()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        yield conn, migration


def test_migration_chains_to_previous_head():
    migration = _load_migration()
    assert migration.revision == "a7d3e9c1f2b4"
    assert migration.down_revision == "6e135be697a8"


def test_models_match_migration(migrated_conn):
    conn, _ = migrated_conn
    md = sa.MetaData()
    for name in NEW_TABLES | set(PREREQS):
        Base.metadata.tables[name].to_metadata(md)
    diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), md)
    assert diff == []


def test_downgrade_drops_only_new_tables(migrated_conn):
    conn, migration = migrated_conn
    with Operations.context(MigrationContext.configure(conn)):
        migration.downgrade()
    assert set(sa.inspect(conn).get_table_names()) == set(PREREQS)


def test_orm_roundtrip_and_idempotency_keys(migrated_conn):
    conn, _ = migrated_conn
    session = Session(bind=conn)
    user = User(email="seed@example.com")
    session.add(user)
    session.flush()

    template = DesignTemplate(slug="square-quote", name="Quote card", layout_json={"version": 1, "pages": []})
    session.add(template)
    session.flush()
    width, height = SIZE_PRESETS["story"]
    doc = DesignDoc(user_id=user.id, size_preset="story", width=width, height=height,
                    template_id=template.id, canvas_json={"version": 1, "pages": [{"layers": []}]})
    item = ApprovalItem(user_id=user.id, source="ad_budget", external_ref="p1", title="Shift budget")
    job = CaptureJob(user_id=user.id, source_url="https://example.com", source_kind="website",
                     meta={"title": "Example"})
    imp = StoreCatalogImport(user_id=user.id, provider="shopify", store_url="https://shop.example.com")
    chan = SocialChannelCredential(user_id=user.id, kind="telegram", credentials_enc="enc", target_id="@chan")
    session.add_all([doc, item, job, imp, chan])
    session.flush()
    session.add(StoreCatalogProduct(import_id=imp.id, user_id=user.id, external_id="42", title="Mug"))
    session.add(AdAllocationProposal(user_id=user.id, run_date=date(2026, 9, 25), approval_item_id=item.id,
                                     proposed_split={"meta": 0.6, "tiktok": 0.4}))
    session.flush()

    assert item.status == STATUS_PENDING
    assert job.status == "queued" and job.screenshots == []
    stored_meta = conn.execute(sa.text("SELECT metadata FROM capture_jobs")).scalar_one()
    assert "Example" in stored_meta
    assert "website" in SOURCE_KINDS and "mastodon" in CHANNEL_KINDS

    # Enqueueing the same approval twice is rejected by the unique key.
    nested = session.begin_nested()
    session.add(ApprovalItem(user_id=user.id, source="ad_budget", external_ref="p1"))
    with pytest.raises(IntegrityError):
        session.flush()
    nested.rollback()

    # Unknown capture source kinds are rejected by the CHECK constraint.
    nested = session.begin_nested()
    session.add(CaptureJob(user_id=user.id, source_url="https://x", source_kind="ftp"))
    with pytest.raises(IntegrityError):
        session.flush()
    nested.rollback()
