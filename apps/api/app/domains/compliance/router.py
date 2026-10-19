from fastapi import APIRouter
from app.controllers.v1 import admin, admin_compliance, compliance
from app.domains.compliance import content_credentials_router
router = APIRouter()
for _adapter in (compliance.router, admin.router, admin_compliance.router, content_credentials_router.router):
    router.include_router(_adapter)
