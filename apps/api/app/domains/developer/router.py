from fastapi import APIRouter
from app.controllers.v1 import api_keys, developer, webhooks_admin
router = APIRouter()
for _adapter in (api_keys.router, webhooks_admin.router, developer.router):
    router.include_router(_adapter)
