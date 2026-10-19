"""Internal-pilot access controls for credit-spending generation.

The pilot is deliberately configured outside the database so it can be enabled
or disabled during an incident without a migration.  When enabled it is
fail-closed: an empty allowlist admits nobody.  This module is used at the API
boundary, before a credit debit or a Celery dispatch is possible.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select

from app.config import config
from app.core.launch import launch_status
from app.core.product_inventory import product_inventory
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit

_REEL = "reel"
_BROLL = "broll"
_VALID_KINDS = frozenset({_REEL, _BROLL})


def _enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _allowlist(value: Any) -> frozenset[str]:
    """Accept a TOML array or a comma-separated environment-style value."""
    if isinstance(value, str):
        values: Iterable[Any] = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        values = ()
    return frozenset(str(item).strip() for item in values if str(item).strip())


def pilot_enabled() -> bool:
    return _enabled(config.app.get("pilot_enabled", False))


def _limit(name: str, default: int) -> int:
    try:
        return max(0, int(config.app.get(name, default)))
    except (TypeError, ValueError):
        return default


def _pilot_spend(session: Any, user_id: str) -> int:
    """Return gross pilot credits already debited by this user.

    Gross spend intentionally does not decrease on a provider refund: the cap
    is an operational provider-cost ceiling, not a customer balance.  It also
    makes the limit conservative if a refund worker is temporarily unavailable.
    """
    from app.models.db.models import CreditLedger

    spent = session.execute(
        select(func.coalesce(func.sum(-CreditLedger.delta), 0)).where(
            CreditLedger.user_id == user_id,
            CreditLedger.workspace_id.is_(None),
            CreditLedger.delta < 0,
            CreditLedger.reason.in_(("pilot_reel_debit", "pilot_broll_debit")),
        )
    ).scalar_one()
    return int(spent or 0)


def _lock_user(session: Any, user_id: str) -> None:
    """Serialize cap evaluation with the following ledger debit on Postgres."""
    from app.models.db.models import User

    # SQLite ignores ``FOR UPDATE``; production Neon serializes this with the
    # same user-row lock used by CreditRepository.debit.
    session.execute(select(User.id).where(User.id == user_id).with_for_update()).first()


def _approved_beta_user(session: Any, user_id: str) -> bool:
    """Whether this account's email holds an operator-approved beta invite.

    Approved beta users get the same pilot rate and credit caps as allowlisted
    users (enforced below); this only widens WHO is admitted. Fails closed.
    """
    try:
        from app.core.launch.policy import beta_email_approved
        from app.models.db.models import User

        email = session.execute(select(User.email).where(User.id == user_id)).scalar_one_or_none()
        return beta_email_approved(session, str(email or ""))
    except Exception:  # noqa: BLE001 - fail closed
        return False


def require_generation_access(
    request: Any,
    session: Any,
    user_id: str,
    kind: str,
    credits: int,
    request_id: str,
) -> None:
    """Enforce pilot allowlist, rate, and spend caps before a debit.

    Disabled pilot mode preserves the existing product behavior.  In pilot mode
    invalid/empty configuration cannot accidentally open generation access.
    """
    if kind not in _VALID_KINDS:
        raise ValueError(f"unknown generation kind: {kind}")
    if not pilot_enabled():
        return

    allowed = _allowlist(config.app.get("pilot_allowlist", ()))
    if user_id not in allowed and not _approved_beta_user(session, user_id):
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: generation is restricted to internal pilot users",
        )

    rate_limit = _limit(f"pilot_{kind}_rate_limit", 5 if kind == _REEL else 3)
    window_s = _limit("pilot_rate_window_s", 3600)
    # A zero limit is an intentional circuit breaker, not a fail-open typo.
    if rate_limit <= 0 or window_s <= 0:
        raise HttpException(
            task_id=request_id,
            status_code=429,
            message=f"{request_id}: {kind} generation is temporarily rate limited",
        )
    enforce_rate_limit(
        request,
        f"pilot:{kind}:{user_id}",
        limit=rate_limit,
        window_s=window_s,
    )

    requested = max(0, int(credits))
    per_request_cap = _limit("pilot_max_credits_per_request", 5)
    if requested > per_request_cap:
        raise HttpException(
            task_id=request_id,
            status_code=402,
            message=(
                f"{request_id}: request costs {requested} credits, above the "
                "internal-pilot per-request cap"
            ),
        )

    total_cap = _limit("pilot_max_credits_per_user", 10)
    _lock_user(session, user_id)
    if _pilot_spend(session, user_id) + requested > total_cap:
        raise HttpException(
            task_id=request_id,
            status_code=402,
            message=f"{request_id}: internal-pilot credit allocation is exhausted",
        )


def capabilities_for_user(user_id: str, session: Any = None) -> dict[str, Any]:
    """Public, non-sensitive capability document for every client."""
    enabled = pilot_enabled()
    admitted = (
        not enabled
        or user_id in _allowlist(config.app.get("pilot_allowlist", ()))
        or (session is not None and _approved_beta_user(session, user_id))
    )
    launch = launch_status()
    from app.domains.broll.workflows import product_engine_capability

    return {
        "mode": "internal_pilot" if enabled else "standard",
        "generation": {"reels": admitted, "broll": admitted},
        "engine": product_engine_capability(),
        "product": product_inventory(),
        "launch": launch,
        "canonical_routes": {
            "reels": "/api/v1/jobs",
            "broll": "/api/v1/generation/broll",
        },
        "limits": {
            "pilot_enabled": enabled,
            "max_credits_per_request": _limit("pilot_max_credits_per_request", 5)
            if enabled
            else None,
        },
    }


def pilot_debit_reason(kind: str, default: str) -> str:
    """Return a ledger reason that makes pilot provider spend auditable."""
    if not pilot_enabled():
        return default
    return "pilot_reel_debit" if kind == _REEL else "pilot_broll_debit"
