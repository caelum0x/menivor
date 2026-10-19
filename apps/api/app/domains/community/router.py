from fastapi import APIRouter
from app.controllers.v1 import marketplace, share
router = APIRouter()
for _adapter in (marketplace.router, share.router):
    router.include_router(_adapter)
