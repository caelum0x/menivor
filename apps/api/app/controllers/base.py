from fastapi import Request

from app.config import config
from app.core.observability import request_correlation_id
from app.models.exception import HttpException


def get_task_id(request: Request):
    """Compatibility name for the canonical request correlation id."""
    return request_correlation_id(request)


def get_api_key(request: Request):
    api_key = request.headers.get("x-api-key")
    return api_key


def _verify_clerk_bearer(request: Request) -> bool:
    """Return ``True`` when the request carries a valid Clerk ``Bearer`` JWT.

    Import-safe and fully inert when Clerk is not configured (or PyJWT is
    absent): any failure to import, configure, or verify simply yields ``False``
    so the caller falls back to the existing ``x-api-key`` gate with unchanged
    behavior. Never raises — a malformed/invalid token is treated as "no bearer".
    """
    try:
        from app.core import clerk
    except Exception:  # pragma: no cover - defensive: never break auth on import
        return False
    if not clerk.is_configured():
        return False
    token = clerk.extract_bearer_token(request)
    if not token:
        return False
    try:
        clerk.verify_clerk_jwt(token)
        return True
    except Exception:  # noqa: BLE001 - invalid token -> fall back to x-api-key
        return False


def verify_token(request: Request):
    token = get_api_key(request)
    if token == config.app.get("api_key", ""):
        return
    # Clerk JWT bridge (CTO §4): accept a valid ``Authorization: Bearer`` token
    # alongside the existing ``x-api-key`` gate. When Clerk is not configured
    # this is a no-op and behavior is unchanged (x-api-key only).
    if _verify_clerk_bearer(request):
        return
    request_id = get_task_id(request)
    request_url = request.url
    user_agent = request.headers.get("user-agent")
    raise HttpException(
        task_id=request_id,
        status_code=401,
        message=f"invalid token: {request_url}, {user_agent}",
    )
