"""Server-authoritative RevenueCat entitlement verification.

The mobile SDK owns purchase and restore UX. Protected backend actions still
verify the same App User ID through RevenueCat's subscriber API so a modified
client cannot bypass the export/share gate. The backend user id is the App User
ID; no client-provided billing identity is accepted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from time import monotonic
from typing import Any, Callable
from urllib.parse import quote

from app.config import config

try:  # pragma: no cover - exercised through the explicit missing-SDK branch
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

_DEFAULT_BASE_URL = "https://api.revenuecat.com/v1"
_DEFAULT_ENTITLEMENT_ID = "pro"
_DEFAULT_TIMEOUT_SECONDS = 5.0
_ACTIVE_CACHE_SECONDS = 60.0
_INACTIVE_CACHE_SECONDS = 1.0


class RevenueCatConfigurationError(RuntimeError):
    """The server cannot verify entitlements because configuration is missing."""


class RevenueCatUnavailableError(RuntimeError):
    """RevenueCat did not return a trustworthy subscriber decision."""


class RevenueCatAccessDenied(PermissionError):
    """The customer does not currently own the required entitlement."""


@dataclass(frozen=True)
class EntitlementDecision:
    active: bool
    entitlement_id: str
    app_user_id: str
    expires_at: datetime | None
    in_grace_period: bool = False


@dataclass(frozen=True)
class _CachedEntitlement:
    decision: EntitlementDecision
    expires_at_monotonic: float


_entitlement_cache: dict[str, _CachedEntitlement] = {}
_entitlement_cache_lock = RLock()


def _cached_decision(app_user_id: str) -> EntitlementDecision | None:
    with _entitlement_cache_lock:
        cached = _entitlement_cache.get(app_user_id)
        if cached is None:
            return None
        if cached.expires_at_monotonic <= monotonic():
            _entitlement_cache.pop(app_user_id, None)
            return None
        return cached.decision


def _cache_decision(decision: EntitlementDecision) -> None:
    ttl = _ACTIVE_CACHE_SECONDS if decision.active else _INACTIVE_CACHE_SECONDS
    with _entitlement_cache_lock:
        _entitlement_cache[decision.app_user_id] = _CachedEntitlement(
            decision=decision,
            expires_at_monotonic=monotonic() + ttl,
        )


def clear_entitlement_cache(app_user_id: str | None = None) -> None:
    """Drop one cached decision, or all decisions when no user is supplied."""

    with _entitlement_cache_lock:
        if app_user_id is None:
            _entitlement_cache.clear()
        else:
            _entitlement_cache.pop(app_user_id.strip(), None)


def _section() -> dict[str, Any]:
    return dict(getattr(config, "revenuecat", {}) or {})


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise RevenueCatUnavailableError(
            "RevenueCat returned a malformed entitlement timestamp."
        )
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RevenueCatUnavailableError(
            "RevenueCat returned a malformed entitlement timestamp."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate_subscriber_entitlement(
    payload: Any,
    *,
    app_user_id: str,
    entitlement_id: str,
    now: datetime | None = None,
) -> EntitlementDecision:
    """Normalize a RevenueCat v1 subscriber response into an access decision."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not isinstance(payload, dict):
        raise RevenueCatUnavailableError("RevenueCat returned a malformed response.")
    subscriber = payload.get("subscriber")
    if not isinstance(subscriber, dict):
        raise RevenueCatUnavailableError("RevenueCat returned a malformed response.")
    entitlements = subscriber.get("entitlements")
    if not isinstance(entitlements, dict):
        raise RevenueCatUnavailableError("RevenueCat returned a malformed response.")

    raw = entitlements.get(entitlement_id)
    if raw is None:
        return EntitlementDecision(
            active=False,
            entitlement_id=entitlement_id,
            app_user_id=app_user_id,
            expires_at=None,
        )
    if not isinstance(raw, dict):
        raise RevenueCatUnavailableError("RevenueCat returned a malformed entitlement.")

    expires_at = _parse_datetime(raw.get("expires_date"))
    grace_expires_at = _parse_datetime(raw.get("grace_period_expires_date"))
    in_grace_period = grace_expires_at is not None and grace_expires_at > current

    # RevenueCat represents lifetime/non-consumable access with no expiration.
    active = expires_at is None or expires_at > current or in_grace_period
    effective_expiration = grace_expires_at if in_grace_period else expires_at
    return EntitlementDecision(
        active=active,
        entitlement_id=entitlement_id,
        app_user_id=app_user_id,
        expires_at=effective_expiration,
        in_grace_period=in_grace_period,
    )


def get_entitlement(
    app_user_id: str,
    *,
    now: datetime | None = None,
    request_get: Callable[..., Any] | None = None,
) -> EntitlementDecision:
    """Fetch and evaluate one server-owned subscriber entitlement.

    Configuration, transport, HTTP, JSON, and response-shape failures all fail
    closed. The secret key is sent only in the server-side Authorization header.
    """

    user_id = (app_user_id or "").strip()
    if not user_id:
        raise RevenueCatUnavailableError("A backend user id is required.")

    # Injected transports are used by deterministic callers and must always see
    # their supplied response. Normal server traffic shares a short cache so a
    # three-second job poll does not become a RevenueCat API poll.
    use_cache = request_get is None
    if use_cache:
        cached = _cached_decision(user_id)
        if cached is not None:
            return cached

    section = _section()
    secret = str(section.get("secret_api_key", "") or "").strip()
    if not secret:
        raise RevenueCatConfigurationError(
            "RevenueCat server verification is not configured."
        )
    entitlement_id = str(
        section.get("entitlement_id", _DEFAULT_ENTITLEMENT_ID)
        or _DEFAULT_ENTITLEMENT_ID
    ).strip()
    if not entitlement_id:
        raise RevenueCatConfigurationError(
            "RevenueCat entitlement id is not configured."
        )

    base_url = str(section.get("api_base_url", _DEFAULT_BASE_URL) or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise RevenueCatConfigurationError("RevenueCat API URL must use HTTPS.")
    try:
        timeout = float(section.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError) as exc:
        raise RevenueCatConfigurationError(
            "RevenueCat timeout must be a number."
        ) from exc
    if timeout <= 0 or timeout > 15:
        raise RevenueCatConfigurationError(
            "RevenueCat timeout must be between 0 and 15 seconds."
        )

    if request_get is None:
        if requests is None:
            raise RevenueCatConfigurationError(
                "The requests package is required for RevenueCat verification."
            )
        request_get = requests.get

    url = f"{base_url}/subscribers/{quote(user_id, safe='')}"
    try:
        response = request_get(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {secret}",
            },
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - transport implementations vary
        raise RevenueCatUnavailableError(
            "RevenueCat subscriber verification is unavailable."
        ) from exc

    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code not in {200, 201}:
        raise RevenueCatUnavailableError(
            "RevenueCat subscriber verification returned an error."
        )
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - response implementations vary
        raise RevenueCatUnavailableError(
            "RevenueCat returned invalid JSON."
        ) from exc

    decision = evaluate_subscriber_entitlement(
        payload,
        app_user_id=user_id,
        entitlement_id=entitlement_id,
        now=now,
    )
    if use_cache:
        _cache_decision(decision)
    return decision


def require_pro_entitlement(app_user_id: str) -> EntitlementDecision:
    """Return the active Pro decision or raise a typed, fail-closed error."""

    decision = get_entitlement(app_user_id)
    if not decision.active:
        raise RevenueCatAccessDenied("An active Pro entitlement is required.")
    return decision


__all__ = [
    "EntitlementDecision",
    "RevenueCatAccessDenied",
    "RevenueCatConfigurationError",
    "RevenueCatUnavailableError",
    "clear_entitlement_cache",
    "evaluate_subscriber_entitlement",
    "get_entitlement",
    "require_pro_entitlement",
]
