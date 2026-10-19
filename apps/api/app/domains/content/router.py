from fastapi import APIRouter
from app.controllers.v1 import catalog, covers, ideas
router = APIRouter()
for _adapter in (catalog.router, ideas.router, covers.router):
    router.include_router(_adapter)
