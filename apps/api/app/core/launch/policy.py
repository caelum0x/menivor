"""Fail-closed public-launch gates.

Provider credentials prove that a provider *can* be called; they must never by
themselves make paid checkout or social publishing public.  This policy is
deliberately configuration-only so an operator can close an exposure path
without a schema migration or a deploy.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

from loguru import logger

from app.config import config
from app.models.exception import HttpException

_PUBLIC = "public"
_PILOT = "internal_pilot"


def _enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def launch_mode() -> str:
    """Return the supported launch mode; unknown config fails closed to pilot."""
    configured = os.getenv("REELFORGE_LAUNCH_MODE", config.app.get("reelforge_launch_mode", _PILOT))
    approved = _enabled(
        os.getenv(
            "REELFORGE_PUBLIC_LAUNCH_APPROVED",
            config.app.get("reelforge_public_launch_approved", False),
        )
    )
    return _PUBLIC if str(configured).strip().lower() == _PUBLIC and approved else _PILOT


def _flag(name: str) -> bool:
    env_name = f"REELFORGE_{name.upper()}"
    value = os.getenv(env_name, config.app.get(f"reelforge_{name}", False))
    return _enabled(value)


# --------------------------------------------------------------------------- #
# Pilot staff override
# --------------------------------------------------------------------------- #
# ``REELFORGE_PILOT_STAFF`` (or ``reelforge_pilot_staff`` in config) is a comma
# separated allow-list of user emails and/or user ids. A request authenticated
# as one of those principals may publish and check out while the public gates
# are closed, so the team can exercise the real flows during the pilot. It
# never widens anything for anonymous or non-listed callers.

_request_scope: ContextVar[dict | None] = ContextVar("launch_request_scope", default=None)
_STAFF_STATE_KEY = "launch_pilot_staff"


def pilot_staff() -> frozenset[str]:
    """Normalized allow-list of pilot staff (lower-cased emails and user ids)."""
    raw = os.getenv("REELFORGE_PILOT_STAFF", config.app.get("reelforge_pilot_staff", ""))
    items = raw if isinstance(raw, (list, tuple, set, frozenset)) else str(raw or "").split(",")
    return frozenset(str(item).strip().lower() for item in items if str(item or "").strip())


def principal_is_pilot_staff(user: Any) -> bool:
    """Whether a resolved ``User`` is on the pilot staff allow-list."""
    if user is None:
        return False
    staff = pilot_staff()
    if not staff:
        return False
    email = str(getattr(user, "email", "") or "").strip().lower()
    user_id = str(getattr(user, "id", "") or "").strip().lower()
    return bool((email and email in staff) or (user_id and user_id in staff))


class LaunchRequestScopeMiddleware:
    """Pure ASGI middleware that exposes the current HTTP scope to the gates.

    The ``require_*`` gates are called with only a request id from dozens of
    routes; binding the scope here lets them check the pilot staff allow-list
    without changing every call site. Nothing is resolved unless a gate is
    closed and a staff list is configured.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _request_scope.set(scope)
        try:
            await self.app(scope, receive, send)
        finally:
            _request_scope.reset(token)


def _resolve_scope_user(scope: dict) -> Any:
    """Resolve the authenticated principal for ``scope`` (fails closed to None)."""
    from starlette.requests import Request

    from app.core.auth.principal import resolve_principal
    from app.models.db.base import get_session

    request = Request(scope)
    with get_session() as session:
        user = resolve_principal(request, session, "launch-staff-check")
        return principal_is_pilot_staff(user)


def request_is_pilot_staff() -> bool:
    """Whether the in-flight request is authenticated as pilot staff.

    Cached per request. Any auth/DB failure reads as "not staff" (fail closed).
    """
    scope = _request_scope.get()
    if scope is None or not pilot_staff():
        return False
    state = scope.setdefault("state", {})
    if _STAFF_STATE_KEY in state:
        return bool(state[_STAFF_STATE_KEY])
    try:
        allowed = bool(_resolve_scope_user(scope))
    except Exception as exc:  # noqa: BLE001 - unauthenticated or broken auth is not staff
        logger.debug(f"pilot staff check: not staff ({type(exc).__name__})")
        allowed = False
    state[_STAFF_STATE_KEY] = allowed
    return allowed


# --------------------------------------------------------------------------- #
# Feature gates
# --------------------------------------------------------------------------- #
def public_checkout_enabled() -> bool:
    """Checkout is open to everyone (public mode and the checkout flag on)."""
    return launch_mode() == _PUBLIC and _flag("checkout_enabled")


def public_publishing_enabled() -> bool:
    """Direct publishing is open to everyone (public mode and the flag on)."""
    return launch_mode() == _PUBLIC and _flag("publishing_enabled")


def payments_paused() -> bool:
    """MENIVOR_PAYMENTS_PROVIDER=none / MENIVOR_PAYMENTS_PAUSED=1: no new checkouts."""
    from app.services.billing import payments_mode

    return payments_mode.payments_paused()


def checkout_enabled() -> bool:
    """Checkout is allowed for the current caller (public, or pilot staff).

    Paused payments close checkout for everyone (staff included) but never the
    provider webhooks, so in-flight payments and refunds still settle.
    """
    if payments_paused():
        return False
    return public_checkout_enabled() or request_is_pilot_staff()


def publishing_enabled() -> bool:
    """Direct publishing is allowed for the current caller (public, or pilot staff)."""
    return public_publishing_enabled() or request_is_pilot_staff()


def payment_webhooks_enabled() -> bool:
    """Provider webhooks may grant credit.

    Webhooks are provider-signed and carry no user session, so they cannot be
    matched against the staff list. They only ever confirm an intent that a
    checkout created, and in the pilot only staff can create one, so they open
    whenever checkout is public or a staff list is configured.
    """
    return public_checkout_enabled() or bool(pilot_staff())


def signup_enabled() -> bool:
    return launch_mode() == _PUBLIC and _flag("signup_enabled")


def launch_status() -> dict[str, Any]:
    """Non-sensitive capability document; intentionally contains no secrets.

    ``features`` is evaluated for the calling principal: an authenticated
    pilot staff member sees publishing and checkout as open.
    """
    from app.services.billing import payments_mode

    mode = launch_mode()
    staff = request_is_pilot_staff()
    paused = payments_mode.payments_paused()
    return {
        "mode": mode,
        "public_access": mode == _PUBLIC,
        "staff_override": staff,
        "payments": payments_mode.status(),
        "features": {
            "signup": signup_enabled(),
            "checkout": (public_checkout_enabled() or staff) and not paused,
            "publishing": public_publishing_enabled() or staff,
        },
    }


CHECKOUT_CLOSED_CODE = "checkout_closed"
PUBLISHING_CLOSED_CODE = "publishing_closed"


def _closed_reason(feature: str) -> str:
    if feature == "checkout" and payments_paused():
        return "Paid plans are back soon. Menivor is free while we move to a new payment partner."
    if launch_mode() != _PUBLIC:
        return f"Menivor is in private beta, so {feature} is paused until public launch."
    return f"{feature[0].upper()}{feature[1:]} is switched off right now."


def require_checkout_enabled(request_id: str) -> None:
    if not checkout_enabled():
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: checkout is not enabled for this launch phase",
            data={"code": CHECKOUT_CLOSED_CODE, "reason": _closed_reason("checkout")},
        )


def require_payment_webhooks_enabled(request_id: str) -> None:
    if not payment_webhooks_enabled():
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: checkout is not enabled for this launch phase",
            data={"code": CHECKOUT_CLOSED_CODE, "reason": _closed_reason("checkout")},
        )


def require_publishing_enabled(request_id: str) -> None:
    if not publishing_enabled():
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: direct publishing is not enabled for this launch phase",
            data={"code": PUBLISHING_CLOSED_CODE, "reason": _closed_reason("direct publishing")},
        )


def beta_email_approved(session: Any, verified_email: str) -> bool:
    """Whether ``verified_email`` holds an operator-approved private-beta invite.

    Fails closed on any import/DB problem. The email MUST come from the
    identity provider's verified claim — never from request input.
    """
    if session is None or not str(verified_email or "").strip():
        return False
    try:
        from app.domains.beta.service import is_email_approved

        return bool(is_email_approved(session, verified_email))
    except Exception:  # noqa: BLE001 - fail closed
        return False


def require_signup_enabled(
    request_id: str,
    *,
    session: Any = None,
    verified_email: str = "",
) -> None:
    """Guard public account creation.

    Returning an existing account is a *login*, not a signup, and must stay
    reachable during a pilot; callers apply this gate only on the branch that
    would provision a brand-new user.

    Explicit private-beta path: when public signup is closed, a brand-new
    account is still allowed if the caller passes the DB ``session`` and the
    identity provider's VERIFIED email, and that email was approved by an
    operator via ``POST /api/v1/beta/requests/approve``.
    """
    if signup_enabled():
        return
    if beta_email_approved(session, verified_email):
        return
    raise HttpException(
        task_id=request_id,
        status_code=403,
        message=(
            f"{request_id}: Menivor is in private beta; request access at "
            "POST /api/v1/beta/request and sign in again once approved"
        ),
    )
