"""HTTP-facing paid-access guard for paid creator actions.

Delegates to :func:`app.services.user_entitlements.require_paid_access`, so a
web monthly plan (Dodo or Creem), a credit pack or mobile RevenueCat Pro all
unlock the same actions (download, share, publish, editor export, winner loop).
"""

from loguru import logger

from app.models.exception import HttpException
from app.services import user_entitlements


def require_pro_action(user_id: str, request_id: str, *, action: str) -> None:
    """Require paid access, mapping the outcome to API errors.

    Denied access is a payment-required response. When no source grants and a
    source could not be verified the answer is 503, so a temporary billing or
    RevenueCat problem can never expose a paid export or distribution action.
    """
    try:
        user_entitlements.require_paid_access(user_id)
    except user_entitlements.PaidAccessDenied as exc:
        raise HttpException(
            task_id=request_id,
            status_code=402,
            message=f"{request_id}: a paid plan, credit pack or Pro subscription is required",
        ) from exc
    except user_entitlements.PaidAccessUnavailable as exc:
        logger.error(f"paid access for {action} unverifiable, request_id: {request_id}")
        raise HttpException(
            task_id=request_id,
            status_code=503,
            message=f"{request_id}: paid access verification is unavailable",
        ) from exc
