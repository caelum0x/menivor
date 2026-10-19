from fastapi import APIRouter
from app.controllers.v1 import device_auth, me, scim, security_policy, sso
router = APIRouter()
for _adapter in (device_auth.router, me.router, sso.router, scim.router, security_policy.router):
    router.include_router(_adapter)
