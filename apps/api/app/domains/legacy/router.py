"""Legacy transport composition; no new product routes belong here."""

from fastapi import APIRouter

from app.controllers.v1 import llm, video
from app.domains.legacy import task_queue

router = APIRouter()
router.include_router(task_queue.router)
router.include_router(video.router)
router.include_router(llm.router)
