"""Store catalog use cases: record an import, list/read/delete, seed Ad Studio projects.

Network work (feed fetch, product images, angle drafting) happens with no DB
session open; the controller persists in short transactions afterwards.
Errors are :class:`~app.domains.adstudio.service.AdStudioError`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.domains.adstudio import service as adstudio_service
from app.domains.adstudio.catalog_models import (
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    StoreCatalogImport,
    StoreCatalogProduct,
)
from app.domains.adstudio.fetch import FetchError
from app.domains.adstudio.service import AdStudioError
from app.domains.adstudio.store_catalog import parsing
from app.domains.adstudio.store_catalog.fetching import StoreFeed, fetch_store

MAX_IMPORTS_LISTED = 50
MAX_PROJECTS_PER_CALL = 5


# ------------------------------------------------------------------- views
def import_view(row: StoreCatalogImport, created_projects: int | None = None) -> dict:
    return {
        "id": row.id, "provider": row.provider, "store_url": row.store_url, "store_name": row.store_name,
        "provider_requested": (row.options or {}).get("provider_requested", row.provider),
        "currency": (row.options or {}).get("currency", ""),
        "status": row.status, "requested_limit": row.requested_limit, "product_count": row.product_count,
        "error": row.error or None, "created_projects": created_projects,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def product_view(p: StoreCatalogProduct) -> dict:
    return {
        "id": p.id, "external_id": p.external_id, "title": p.title, "description": p.description,
        "price_minor": p.price_minor, "compare_at_minor": p.compare_at_minor, "currency": p.currency, "url": p.url,
        "image_urls": list(p.image_urls or []), "tags": list(p.tags or []),
        "adstudio_project_id": p.adstudio_project_id,
    }


# ------------------------------------------------------------------ import
def fetch_feed(store_url: str, provider: str, limit: int) -> tuple[StoreFeed | None, str, int]:
    """Network phase. Returns (feed, error, status) - never raises for fetch failures."""
    try:
        feed = fetch_store(store_url, provider, limit)
    except FetchError as exc:
        return None, exc.message, exc.status_code
    if not feed.products:
        return feed, "the store feed has no published products", 422
    return feed, "", 200


def record_import(session: Any, *, user_id: str, store_url: str, provider: str, limit: int,
                  feed: StoreFeed | None, error: str, now: datetime | None = None) -> StoreCatalogImport:
    now = now or datetime.now(timezone.utc)
    row = StoreCatalogImport(
        user_id=user_id, provider=feed.provider if feed else (provider if provider != "auto" else "shopify"),
        store_url=(feed.origin if feed else store_url)[:2000], store_name=(feed.store_name if feed else "")[:200],
        status=STATUS_FAILED if error else STATUS_SUCCEEDED, requested_limit=limit,
        options={"provider_requested": provider, "currency": feed.currency if feed else ""},
        error=error[:2000], started_at=now, finished_at=now,
    )
    session.add(row)
    session.flush()
    if feed and not error:
        seen: set[str] = set()
        for product in feed.products:
            if product["external_id"] in seen:
                continue
            seen.add(product["external_id"])
            fields = {**product, "raw": {**(product.get("raw") or {}), "position": len(seen)}}
            session.add(StoreCatalogProduct(import_id=row.id, user_id=user_id, **fields))
        row.product_count = len(seen)
        session.flush()
    return row


def list_imports(session: Any, user_id: str) -> list[dict]:
    rows = session.execute(select(StoreCatalogImport).where(StoreCatalogImport.user_id == user_id)
                           .order_by(StoreCatalogImport.created_at.desc()).limit(MAX_IMPORTS_LISTED)).scalars().all()
    ids = [r.id for r in rows]
    created: dict[str, int] = {}
    if ids:
        stmt = (select(StoreCatalogProduct.import_id, func.count())
                .where(StoreCatalogProduct.import_id.in_(ids), StoreCatalogProduct.adstudio_project_id.is_not(None))
                .group_by(StoreCatalogProduct.import_id))
        created = {k: int(v) for k, v in session.execute(stmt).all()}
    return [import_view(r, created.get(r.id, 0)) for r in rows]


def get_owned_import(session: Any, user_id: str, import_id: str) -> StoreCatalogImport:
    row = session.execute(select(StoreCatalogImport).where(
        StoreCatalogImport.id == import_id, StoreCatalogImport.user_id == user_id,
    )).scalar_one_or_none()
    if row is None:
        raise AdStudioError(404, "import not found")
    return row


def import_detail(session: Any, user_id: str, import_id: str) -> dict:
    row = get_owned_import(session, user_id, import_id)
    products = sorted(
        session.execute(select(StoreCatalogProduct).where(StoreCatalogProduct.import_id == row.id)).scalars().all(),
        key=lambda p: int((p.raw or {}).get("position") or 0),
    )
    created = sum(1 for p in products if p.adstudio_project_id)
    return {**import_view(row, created), "products": [product_view(p) for p in products]}


def delete_import(session: Any, user_id: str, import_id: str) -> None:
    row = get_owned_import(session, user_id, import_id)
    session.query(StoreCatalogProduct).filter(StoreCatalogProduct.import_id == row.id).delete(
        synchronize_session=False)
    session.delete(row)
    session.flush()


# ------------------------------------------------------- Ad Studio projects
def products_for_projects(session: Any, user_id: str, import_id: str, product_ids: list[str]) -> tuple[str, list[dict]]:
    """Snapshot the picked products (no network). Already-seeded ones are rejected."""
    row = get_owned_import(session, user_id, import_id)
    wanted = list(dict.fromkeys(product_ids))
    if not 1 <= len(wanted) <= MAX_PROJECTS_PER_CALL:
        raise AdStudioError(422, f"pick between 1 and {MAX_PROJECTS_PER_CALL} products at a time")
    rows = session.execute(select(StoreCatalogProduct).where(
        StoreCatalogProduct.import_id == row.id, StoreCatalogProduct.id.in_(wanted),
    )).scalars().all()
    by_id = {p.id: p for p in rows}
    missing = [pid for pid in wanted if pid not in by_id]
    if missing:
        raise AdStudioError(404, "one of the selected products is not in this import")
    done = [by_id[pid].title for pid in wanted if by_id[pid].adstudio_project_id]
    if done:
        raise AdStudioError(409, f"already in Ad Studio: {', '.join(done)[:300]}")
    return row.provider, [{**product_view(by_id[pid]), "raw": dict(by_id[pid].raw or {})} for pid in wanted]


def prepare_projects(provider: str, products: list[dict], *, language: str | None, use_llm: bool,
                     angle_count: int = 5) -> list[tuple[str, dict | None, str]]:
    """Network phase: (catalog product id, prepared project or None, error) per product."""
    out: list[tuple[str, dict | None, str]] = []
    for product in products:
        try:
            prepared = adstudio_service.prepare_project(
                url=product.get("url") or None, manual=parsing.to_manual_product(product, provider),
                language=language, angles=None, count=angle_count, use_llm=use_llm,
            )
            out.append((product["id"], prepared, ""))
        except AdStudioError as exc:
            out.append((product["id"], None, exc.message))
    return out


def persist_projects(session: Any, user_id: str, prepared: list[tuple[str, dict | None, str]]) -> list[dict]:
    results = []
    for product_id, item, error in prepared:
        if item is None:
            results.append({"product_id": product_id, "project_id": None, "error": error})
            continue
        product = session.get(StoreCatalogProduct, product_id)
        if product is None or product.user_id != user_id:
            results.append({"product_id": product_id, "project_id": None, "error": "product was removed"})
            continue
        if product.adstudio_project_id:
            results.append({"product_id": product_id, "project_id": product.adstudio_project_id, "error": ""})
            continue
        project = adstudio_service.persist_project(session, user_id=user_id, prepared=item, title="", image_keys=[])
        product.adstudio_project_id = project.id
        session.flush()
        results.append({"product_id": product_id, "project_id": project.id, "error": ""})
    return results


__all__ = ["MAX_PROJECTS_PER_CALL", "delete_import", "fetch_feed", "get_owned_import", "import_detail",
           "import_view", "list_imports", "persist_projects", "prepare_projects", "product_view",
           "products_for_projects", "record_import"]
