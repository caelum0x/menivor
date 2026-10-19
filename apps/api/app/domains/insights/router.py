from fastapi import APIRouter

from app.controllers.v1 import analytics
from app.domains.insights.winner_loop_router import router as winner_loop_router

router = APIRouter()
for _adapter in (analytics.router, winner_loop_router):
    router.include_router(_adapter)
