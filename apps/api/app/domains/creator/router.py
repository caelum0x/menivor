from fastapi import APIRouter
from app.controllers.v1 import brand, creators, notifications, performance, voices
router = APIRouter()
for _adapter in (creators.router, brand.router, voices.router, notifications.router, performance.router):
    router.include_router(_adapter)
