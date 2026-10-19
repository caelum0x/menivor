"""Paid-ads route composition (transport adapter lives in controllers/v1)."""

from fastapi import APIRouter

from app.controllers.v1 import ads

router = APIRouter()
router.include_router(ads.router)

# Cross-network budget allocator + "which network pays off" report (M-5).
from app.domains.ads.allocator.routes import router as allocator_router  # noqa: E402

router.include_router(allocator_router)
