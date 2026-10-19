"""Per-API-key rate-limit + monthly-quota enforcement (POWER-USER TIER).

This is the pure, framework-agnostic policy layer that sits behind the
``x-api-key`` caller-resolution path in ``app.controllers.v1.base``. It answers
one question for a resolved :class:`~app.models.db.models.UserApiKey`: *may this
request proceed?* — via two independent controls:

* **Per-minute rate limit** (:func:`enforce_rate_limit`) — delegates to the
  existing fixed-window limiter (:mod:`app.services.ratelimit`), keyed by the
  key's non-secret ``prefix``. Like that limiter it **fails closed**: without
  Redis the same limit is enforced by an in-process bucket.
* **Monthly quota** (:func:`check_and_consume`) — atomically increments the
  key's counter for the given calendar month (via
  :class:`~app.models.db.repositories.ApiKeyUsageRepository`) and rejects the
  request once the count exceeds the key's ``monthly_quota``.

Design:

* **Deterministic + testable.** No wall-clock is read inside the quota path:
  callers pass an explicit ``now_ym`` (``'YYYY-MM'``) string so tests are
  deterministic. :func:`current_period_ym` derives that token for production
  callers (the only place ``datetime.now`` is read, and it is injectable).
* **Nullable columns = plan defaults.** ``rate_limit_per_min`` NULL falls back
  to the config/plan default; ``monthly_quota`` NULL means UNLIMITED (no cap).
* **Small, typed breaches.** A breach raises :class:`ApiKeyLimitError` (base) —
  :class:`RateLimitExceeded` or :class:`QuotaExceeded` — which the API layer maps
  to a single HTTP ``429``. No hardcoded secrets; no framework imports.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import config

# --------------------------------------------------------------------------- #
# Tunables (config-overridable).
# --------------------------------------------------------------------------- #
#: Fallback per-minute rate limit for a key whose ``rate_limit_per_min`` is NULL
#: (i.e. inherits the plan default). Config key ``reelforge_api_key_rate_limit``.
DEFAULT_RATE_LIMIT_PER_MIN: int = 60

#: The rate-limit window, in seconds. A per-minute limit is a 60s fixed window.
_RATE_WINDOW_S: int = 60

#: Namespace so a key's rate bucket never collides with other limiter buckets.
_RATE_BUCKET_PREFIX: str = "apikey"


class ApiKeyLimitError(Exception):
    """Base class for a per-key limit breach (the API layer maps this to 429)."""


class RateLimitExceeded(ApiKeyLimitError):
    """Raised when a key exceeds its per-minute request rate limit."""

    def __init__(self, message: str, *, limit: int, reset_s: int) -> None:
        super().__init__(message)
        self.limit = limit
        self.reset_s = reset_s


class QuotaExceeded(ApiKeyLimitError):
    """Raised when a key exceeds its monthly request quota."""

    def __init__(
        self, message: str, *, limit: int, used: int, period_ym: str
    ) -> None:
        super().__init__(message)
        self.limit = limit
        self.used = used
        self.period_ym = period_ym


def current_period_ym(now: datetime | None = None) -> str:
    """Return the current calendar month as a ``'YYYY-MM'`` token.

    ``now`` is injectable so callers/tests can pin the month; production callers
    omit it and get the current UTC month. This is the ONLY place a wall-clock is
    read, keeping :func:`check_and_consume` fully deterministic.
    """
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m")


def _default_rate_limit_per_min() -> int:
    """Resolve the plan/config default per-minute limit (safe on bad config)."""
    try:
        return int(
            config.app.get("reelforge_api_key_rate_limit", DEFAULT_RATE_LIMIT_PER_MIN)
        )
    except (TypeError, ValueError):
        return DEFAULT_RATE_LIMIT_PER_MIN


def _bucket_identity(api_key_row: object) -> str:
    """Stable, non-secret bucket id for a key (its ``prefix``, else its ``id``).

    The ``prefix`` is a short non-secret display label (never the raw key), so it
    is safe to use directly as a limiter bucket. Falls back to the row ``id`` when
    a prefix is absent so a key is always bucketed to itself.
    """
    prefix = str(getattr(api_key_row, "prefix", "") or "").strip()
    if prefix:
        return prefix
    return str(getattr(api_key_row, "id", "") or "").strip() or "unknown"


def enforce_rate_limit(api_key_row: object) -> None:
    """Enforce a key's per-minute rate limit; raise :class:`RateLimitExceeded`.

    The effective limit is the key's ``rate_limit_per_min`` or, when NULL, the
    plan/config default. A non-positive effective limit disables the control
    (treated as unlimited). Delegates to :func:`app.services.ratelimit.rate_limit`
    keyed by the key's non-secret ``prefix`` — which keeps enforcing the limit
    in-process when Redis is down, so an outage never means unlimited calls.
    """
    raw_limit = getattr(api_key_row, "rate_limit_per_min", None)
    limit = _default_rate_limit_per_min() if raw_limit is None else int(raw_limit)
    if limit <= 0:
        # Non-positive => the per-minute control is disabled for this key.
        return

    # Imported lazily so this module stays import-safe even if the limiter (or
    # its optional redis dep) is unavailable.
    from app.services.ratelimit import rate_limit

    key = f"{_RATE_BUCKET_PREFIX}:{_bucket_identity(api_key_row)}"
    result = rate_limit(key, limit, _RATE_WINDOW_S)
    if not result.allowed:
        raise RateLimitExceeded(
            f"api key rate limit exceeded: {limit} requests/min; "
            f"retry in {result.reset_s}s",
            limit=limit,
            reset_s=result.reset_s,
        )


def check_and_consume(session: object, api_key_row: object, now_ym: str) -> int:
    """Consume one unit of a key's monthly quota; return the new month count.

    Atomically increments the key's counter for ``now_ym`` (an explicit
    ``'YYYY-MM'`` token so the check is deterministic) via
    :class:`ApiKeyUsageRepository`. When the key's ``monthly_quota`` is set and
    the new count exceeds it, raises :class:`QuotaExceeded`. When ``monthly_quota``
    is ``None`` the key is UNLIMITED — the counter is still incremented (for usage
    history) but the request is never rejected. Returns the post-increment count.
    """
    # Imported lazily to keep this module import-safe (mirrors the guarded
    # persistence imports elsewhere in the controllers).
    from app.models.db.repositories import ApiKeyUsageRepository

    key_id = str(getattr(api_key_row, "id", "") or "")
    quota = getattr(api_key_row, "monthly_quota", None)

    repo = ApiKeyUsageRepository(session)  # type: ignore[arg-type]
    new_count = repo.increment(key_id, now_ym)

    if quota is not None and new_count > int(quota):
        raise QuotaExceeded(
            f"monthly api quota exceeded: {int(quota)} requests for {now_ym}",
            limit=int(quota),
            used=new_count,
            period_ym=now_ym,
        )
    return new_count


__all__ = [
    "ApiKeyLimitError",
    "RateLimitExceeded",
    "QuotaExceeded",
    "DEFAULT_RATE_LIMIT_PER_MIN",
    "current_period_ym",
    "enforce_rate_limit",
    "check_and_consume",
]
