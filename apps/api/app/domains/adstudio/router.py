"""Ad Studio route composition (transport adapter lives in controllers/v1)."""

from fastapi import APIRouter

from app.controllers.v1 import adstudio
from app.domains.adstudio.publish_router import router as publish_router

router = APIRouter()
router.include_router(adstudio.router)
router.include_router(publish_router)

# Store catalog import: Shopify / WooCommerce public feeds -> Ad Studio projects (M-6).
from app.domains.adstudio.store_catalog.routes import router as store_catalog_router  # noqa: E402

router.include_router(store_catalog_router)
