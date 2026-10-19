from fastapi import APIRouter
from app.controllers.v1 import audit, rbac, workspaces
router = APIRouter()
for _adapter in (workspaces.router, rbac.router, audit.router):
    router.include_router(_adapter)
