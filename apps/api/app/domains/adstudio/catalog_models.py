"""Store catalog import persistence (tables created by migration ``a7d3e9c1f2b4``).

* :class:`StoreCatalogImport` - one bulk import from a Shopify store
  (public ``/products.json``) or WooCommerce store (public Store API
  ``/wp-json/wc/store/v1/products``): status, counts, error.
* :class:`StoreCatalogProduct` - one imported product (title, price, images,
  url) ready to seed an Ad Studio project or a Design Studio layout.

Named ``store_catalog_*`` so it never collides with the model catalog in
:mod:`app.domains.catalog`. Prices are integer minor units (cents).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users/workspaces)
from app.models.db.base import Base

PROVIDER_SHOPIFY = "shopify"
PROVIDER_WOOCOMMERCE = "woocommerce"
PROVIDERS = frozenset({PROVIDER_SHOPIFY, PROVIDER_WOOCOMMERCE})

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
IMPORT_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED})

# Upper bound on products kept per import (keeps a huge store from flooding).
MAX_PRODUCTS_PER_IMPORT = 250


def _uuid() -> str:
    return uuid.uuid4().hex


class StoreCatalogImport(Base):
    __tablename__ = "store_catalog_imports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    store_url: Mapped[str] = mapped_column(Text, nullable=False)
    store_name: Mapped[str] = mapped_column(String(200), default="", server_default=sql_text("''"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_QUEUED, server_default=sql_text("'queued'"), nullable=False
    )
    requested_limit: Mapped[int] = mapped_column(Integer, default=50, server_default=sql_text("50"), nullable=False)
    product_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"), nullable=False)
    options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StoreCatalogProduct(Base):
    __tablename__ = "store_catalog_products"
    __table_args__ = (
        UniqueConstraint("import_id", "external_id", name="uq_store_catalog_products_import_ext"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    import_id: Mapped[str] = mapped_column(
        ForeignKey("store_catalog_imports.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="", server_default=sql_text("''"), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    price_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    compare_at_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="", server_default=sql_text("''"), nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", server_default=sql_text("''"), nullable=False)
    image_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Set once the product seeded an Ad Studio project.
    adstudio_project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
