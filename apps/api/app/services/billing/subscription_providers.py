"""Provider transport for recurring WORKSPACE subscriptions (Stripe, Creem, Polar).

Three jobs per provider, nothing else (no DB writes, no credit grants):

1. :func:`open_checkout` — hosted checkout for a recurring plan, threading the
   workspace provenance (``kind=subscription``, workspace, plan, interval, seats,
   period credits) into provider metadata so every later event can be routed.
2. :func:`cancel` / :func:`change_plan` — mutate the LIVE provider subscription so
   the local row never diverges from what the customer is actually billed for.
3. :func:`parse_event` — normalize a VERIFIED provider event into one shape the
   idempotent :mod:`app.services.subscriptions` applier understands, or ``None``
   for events that are not about a workspace subscription.

Every recurring id comes from :mod:`app.services.billing.workspace_plans`, never
from the one-time pack ids. Secrets are read from config via the existing
provider adapters; a missing secret/id raises ``RuntimeError``/``ValueError`` with
a clear message instead of guessing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from loguru import logger

from app.services.billing import workspace_plans as wp

KIND_SUBSCRIPTION: str = "subscription"
_HTTP_TIMEOUT: tuple[int, int] = (5, 20)
_CREEM_DEFAULT_BASE: str = "https://api.creem.io"

_STATUS_MAP: dict[str, str] = {
    "active": "active",
    "paid": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "unpaid": "past_due",
    "incomplete": "past_due",
    "canceled": "canceled",
    "cancelled": "canceled",
    "expired": "canceled",
    "revoked": "canceled",
    "incomplete_expired": "canceled",
}

_STRIPE_SUB_EVENTS: frozenset[str] = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.paid",
        "invoice.payment_failed",
    }
)
_CREEM_LIVE_EVENTS: frozenset[str] = frozenset(
    {"subscription.active", "subscription.paid", "subscription.update", "subscription.trialing"}
)
_CREEM_END_EVENTS: frozenset[str] = frozenset({"subscription.canceled", "subscription.expired"})
_CREEM_PAST_DUE_EVENTS: frozenset[str] = frozenset({"subscription.past_due", "subscription.unpaid"})
_POLAR_SUB_EVENTS: frozenset[str] = frozenset(
    {
        "subscription.created",
        "subscription.active",
        "subscription.updated",
        "subscription.canceled",
        "subscription.uncanceled",
        "subscription.revoked",
    }
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping, a Stripe object, or an attribute."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:  # pragma: no cover - non-standard get
            pass
    return getattr(obj, key, default)


def _path(obj: Any, *keys: str) -> Any:
    for key in keys:
        obj = _get(obj, key)
        if obj is None:
            return None
    return obj


def _first_item(obj: Any, *keys: str) -> Any:
    data = _path(obj, *keys)
    if isinstance(data, (list, tuple)) and data:
        return data[0]
    try:
        return data[0] if data else None
    except (TypeError, KeyError, IndexError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    """Unix seconds or an ISO-8601 string -> aware UTC datetime (else ``None``)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return _to_datetime(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _canonical_status(raw: Any, default: str = "active") -> str:
    return _STATUS_MAP.get(str(raw or "").strip().lower(), default)


def _metadata(
    *, user_id: str, workspace_id: str, plan: wp.WorkspacePlan, interval: str, seats: int
) -> dict[str, str]:
    return {
        "kind": KIND_SUBSCRIPTION,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "plan_key": plan.key,
        "interval": interval,
        "seats": str(seats),
        "credits": str(plan.period_credits(interval)),
    }


def _require_ref(provider: str, plan: wp.WorkspacePlan, interval: str) -> str:
    ref = wp.provider_ref(provider, plan.key, interval)
    if not ref:
        raise RuntimeError(
            f"{provider} has no recurring id configured for workspace plan "
            f"{plan.key!r} ({interval}ly)."
        )
    return ref


def _http(method: str, url: str, *, headers: dict[str, str], body: Any = None) -> dict:
    """JSON request with clean ``RuntimeError`` on transport/HTTP failures."""
    try:
        import requests
    except Exception as exc:  # pragma: no cover - requests is a hard dep
        raise RuntimeError(f"'requests' is required for billing: {exc}") from exc
    try:
        response = requests.request(
            method, url, headers=headers, json=body, timeout=_HTTP_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 - normalize transport errors
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        text = str(getattr(response, "text", "") or "")[:400]
        raise RuntimeError(f"{method} {url} rejected (HTTP {status}): {text}")
    if status == 204 or not getattr(response, "content", b""):
        return {}
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 - body is optional for mutations
        return {}
    return data if isinstance(data, dict) else {}


def _creem_base() -> str:
    from app.services.billing import creem_client

    base = str(creem_client._creem_config().get("base_url", "") or "").strip()
    return (base or _CREEM_DEFAULT_BASE).rstrip("/")


def _creem_headers() -> dict[str, str]:
    from app.services.billing import creem_client

    return {
        "x-api-key": creem_client._require_api_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _polar_base() -> str:
    from app.services.billing import polar_client

    return polar_client._base_url().rstrip("/")


def _polar_headers() -> dict[str, str]:
    from app.services.billing import polar_client

    return {
        "Authorization": f"Bearer {polar_client._require_access_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
def open_checkout(
    provider: str,
    *,
    user_id: str,
    user_email: str,
    workspace_id: str,
    plan: wp.WorkspacePlan,
    interval: str,
    seats: int,
) -> dict[str, str]:
    """Open a hosted recurring checkout; returns ``{checkout_url, session_id}``."""
    ref = _require_ref(provider, plan, interval)
    metadata = _metadata(
        user_id=user_id, workspace_id=workspace_id, plan=plan, interval=interval, seats=seats
    )
    if provider == wp.STRIPE:
        return _stripe_checkout(ref, metadata, user_id=user_id, user_email=user_email)
    if provider == wp.CREEM:
        return _creem_checkout(ref, metadata, user_id=user_id, user_email=user_email)
    if provider == wp.POLAR:
        return _polar_checkout(ref, metadata, user_email=user_email)
    raise ValueError(f"unsupported subscription provider {provider!r}")


def _stripe_checkout(
    price_id: str, metadata: dict[str, str], *, user_id: str, user_email: str
) -> dict[str, str]:
    from app.services.billing import stripe_client

    stripe_client._require_sdk()
    stripe = stripe_client.stripe
    stripe.api_key = stripe_client._require_secret_key()
    cfg = stripe_client._stripe_config()
    success_url = str(cfg.get("success_url", "") or "").strip()
    cancel_url = str(cfg.get("cancel_url", "") or "").strip()
    if not success_url or not cancel_url:
        raise RuntimeError(
            "Stripe is not configured: missing config.stripe.success_url/cancel_url."
        )
    kwargs: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": user_id,
        "metadata": metadata,
        "subscription_data": {"metadata": dict(metadata)},
    }
    if user_email:
        kwargs["customer_email"] = user_email
    session = stripe.checkout.Session.create(**kwargs)
    session_id = str(_get(session, "id", "") or "")
    url = str(_get(session, "url", "") or "")
    if not session_id or not url:
        raise RuntimeError("Stripe returned a subscription checkout without an id/url.")
    return {"checkout_url": url, "session_id": session_id}


def _creem_checkout(
    product_id: str, metadata: dict[str, str], *, user_id: str, user_email: str
) -> dict[str, str]:
    from app.services.billing import creem_client

    body: dict[str, Any] = {
        "product_id": product_id,
        "success_url": creem_client._success_url(),
        "request_id": f"sub:{metadata['workspace_id']}:{user_id}",
        "metadata": metadata,
    }
    if user_email:
        body["customer"] = {"email": user_email}
    data = _http("POST", f"{_creem_base()}/v1/checkouts", headers=_creem_headers(), body=body)
    session_id = str(data.get("id", "") or "").strip()
    url = str(data.get("checkout_url", "") or data.get("url", "") or "").strip()
    if not session_id or not url:
        raise RuntimeError("Creem returned a subscription checkout without an id/url.")
    return {"checkout_url": url, "session_id": session_id}


def _polar_checkout(
    product_id: str, metadata: dict[str, str], *, user_email: str
) -> dict[str, str]:
    from app.services.billing import polar_client

    success_url = str(polar_client._polar_config().get("success_url", "") or "").strip()
    if not success_url:
        raise RuntimeError("Polar is not configured: missing config.polar.success_url.")
    body: dict[str, Any] = {
        "products": [product_id],
        "success_url": success_url,
        "metadata": metadata,
    }
    if user_email:
        body["customer_email"] = user_email
    data = _http("POST", f"{_polar_base()}/v1/checkouts/", headers=_polar_headers(), body=body)
    session_id = str(data.get("id", "") or "").strip()
    url = str(data.get("url", "") or "").strip()
    if not session_id or not url:
        raise RuntimeError("Polar returned a subscription checkout without an id/url.")
    return {"checkout_url": url, "session_id": session_id}


# --------------------------------------------------------------------------- #
# Cancel / change plan (mutate the LIVE provider subscription)
# --------------------------------------------------------------------------- #
def cancel(provider: str, provider_ref: str) -> None:
    """Cancel the provider subscription NOW so no further renewal is charged."""
    ref = (provider_ref or "").strip()
    if not ref:
        raise ValueError("subscription has no provider reference to cancel")
    if provider == wp.STRIPE:
        from app.services.billing import stripe_client

        stripe_client._require_sdk()
        stripe = stripe_client.stripe
        stripe.api_key = stripe_client._require_secret_key()
        try:
            stripe.Subscription.cancel(ref)
        except Exception as exc:  # noqa: BLE001 - already-canceled is success
            if "canceled" in str(exc).lower() or "no such subscription" in str(exc).lower():
                logger.info(f"stripe subscription {ref} already canceled: {exc}")
                return
            raise
        return
    if provider == wp.CREEM:
        _http(
            "POST",
            f"{_creem_base()}/v1/subscriptions/{ref}/cancel",
            headers=_creem_headers(),
            body={},
        )
        return
    if provider == wp.POLAR:
        _http("DELETE", f"{_polar_base()}/v1/subscriptions/{ref}", headers=_polar_headers())
        return
    raise ValueError(f"unsupported subscription provider {provider!r}")


def change_plan(
    provider: str,
    provider_ref: str,
    *,
    plan: wp.WorkspacePlan,
    interval: str,
    metadata: dict[str, str],
) -> None:
    """Move the provider subscription to ``plan`` (prorated, charged now)."""
    ref = (provider_ref or "").strip()
    if not ref:
        raise ValueError("subscription has no provider reference to change")
    target = _require_ref(provider, plan, interval)
    if provider == wp.STRIPE:
        from app.services.billing import stripe_client

        stripe_client._require_sdk()
        stripe = stripe_client.stripe
        stripe.api_key = stripe_client._require_secret_key()
        current = stripe.Subscription.retrieve(ref)
        item = _first_item(current, "items", "data")
        item_id = str(_get(item, "id", "") or "")
        if not item_id:
            raise RuntimeError(f"Stripe subscription {ref} has no line item to change.")
        stripe.Subscription.modify(
            ref,
            items=[{"id": item_id, "price": target}],
            proration_behavior="always_invoice",
            metadata=metadata,
        )
        return
    if provider == wp.CREEM:
        _http(
            "POST",
            f"{_creem_base()}/v1/subscriptions/{ref}/upgrade",
            headers=_creem_headers(),
            body={"product_id": target, "update_behavior": "proration-charge-immediately"},
        )
        return
    if provider == wp.POLAR:
        _http(
            "PATCH",
            f"{_polar_base()}/v1/subscriptions/{ref}",
            headers=_polar_headers(),
            body={"product_id": target, "proration_behavior": "invoice"},
        )
        return
    raise ValueError(f"unsupported subscription provider {provider!r}")


# --------------------------------------------------------------------------- #
# Event normalization
# --------------------------------------------------------------------------- #
def _normalized(
    *,
    provider: str,
    event_id: str,
    metadata: Any,
    provider_ref: str,
    status: str,
    period_end: Any,
    product_ref: str = "",
    grant_allowed: bool = True,
) -> dict[str, Any] | None:
    """Build the shared event shape; plan is resolved from the product first."""
    metadata = metadata or {}
    mapped = wp.plan_for_provider_ref(provider, product_ref) if product_ref else None
    plan_key = (mapped[0] if mapped else str(_get(metadata, "plan_key", "") or "")).strip().lower()
    raw_interval = mapped[1] if mapped else str(_get(metadata, "interval", "") or "")
    # ``None`` = unknown from this event: the applier keeps the stored value.
    interval = raw_interval.strip().lower() if raw_interval.strip().lower() in wp.INTERVALS else None
    plan = wp.get_workspace_plan(plan_key)
    credits = plan.period_credits(interval or wp.MONTH) if plan else 0
    raw_seats = _get(metadata, "seats", None)
    try:
        seats = max(1, int(str(raw_seats))) if raw_seats not in (None, "") else None
    except (TypeError, ValueError):
        seats = None
    period_dt = _to_datetime(period_end)
    return {
        "provider": provider,
        "event_id": event_id or provider_ref,
        "workspace_id": str(_get(metadata, "workspace_id", "") or "").strip(),
        "user_id": str(_get(metadata, "user_id", "") or "").strip(),
        "plan_key": plan_key or "free",
        "interval": interval,
        "seats": seats,
        "provider_ref": provider_ref,
        "status": status,
        "current_period_end": period_dt,
        # Unix seconds: identical to the historical Stripe key format so a period
        # that was already granted before this module existed is never re-granted.
        "period_key": str(int(period_dt.timestamp())) if period_dt else "",
        "credits": credits,
        # Whether this event type may fund a period at all (the applier still
        # requires a live status, a resolvable plan and a period marker).
        "grant_allowed": grant_allowed,
    }


def is_subscription_metadata(metadata: Any) -> bool:
    """True when checkout/order metadata belongs to a workspace SUBSCRIPTION."""
    return str(_get(metadata or {}, "kind", "") or "").strip().lower() == KIND_SUBSCRIPTION


def parse_event(provider: str, event: Any) -> dict[str, Any] | None:
    """Normalize a verified provider event, or ``None`` when it is not ours."""
    if provider == wp.STRIPE:
        return _parse_stripe(event)
    if provider == wp.CREEM:
        return _parse_creem(event)
    if provider == wp.POLAR:
        return _parse_polar(event)
    return None


def _parse_stripe(event: Any) -> dict[str, Any] | None:
    event_type = str(_get(event, "type", "") or "")
    if event_type not in _STRIPE_SUB_EVENTS:
        return None
    obj = _path(event, "data", "object") or {}
    event_id = str(_get(event, "id", "") or "")
    if event_type.startswith("invoice."):
        provider_ref = str(
            _get(obj, "subscription", "")
            or _path(obj, "parent", "subscription_details", "subscription")
            or ""
        )
        if not provider_ref:
            return None  # a one-off invoice, not a subscription renewal
        metadata = (
            _path(obj, "subscription_details", "metadata")
            or _path(obj, "parent", "subscription_details", "metadata")
            or {}
        )
        line = _first_item(obj, "lines", "data")
        price_id = str(_path(line, "price", "id") or _path(line, "pricing", "price_details", "price") or "")
        failed = event_type == "invoice.payment_failed"
        return _normalized(
            provider=wp.STRIPE,
            event_id=event_id,
            metadata=metadata,
            provider_ref=provider_ref,
            status="past_due" if failed else "active",
            period_end=_path(line, "period", "end"),
            product_ref=price_id,
        )
    item = _first_item(obj, "items", "data")
    deleted = event_type == "customer.subscription.deleted"
    return _normalized(
        provider=wp.STRIPE,
        event_id=event_id,
        metadata=_get(obj, "metadata", {}),
        provider_ref=str(_get(obj, "id", "") or ""),
        status="canceled" if deleted else _canonical_status(_get(obj, "status")),
        period_end=_get(obj, "current_period_end") or _get(item, "current_period_end"),
        product_ref=str(_path(item, "price", "id") or ""),
    )


def _creem_object(event: Any) -> Any:
    return _get(event, "object") or _path(event, "data", "object") or _get(event, "data") or {}


def _parse_creem(event: Any) -> dict[str, Any] | None:
    event_type = str(
        _get(event, "eventType", "") or _get(event, "event_type", "") or _get(event, "type", "")
    ).strip()
    obj = _creem_object(event)
    event_id = str(_get(event, "id", "") or "")
    if event_type in {"checkout.completed", "checkout.paid"}:
        if not is_subscription_metadata(_get(obj, "metadata")):
            return None
        sub = _get(obj, "subscription")
        sub_id = str(_get(sub, "id", "") if isinstance(sub, Mapping) else sub or "")
        if not sub_id:
            return None
        # Link the row only; the period grant comes from subscription.paid.
        return _normalized(
            provider=wp.CREEM,
            event_id=event_id,
            metadata=_get(obj, "metadata"),
            provider_ref=sub_id,
            status="active",
            period_end=_get(sub, "current_period_end_date") if isinstance(sub, Mapping) else None,
            product_ref=str(_path(obj, "product", "id") or _get(obj, "product_id", "") or ""),
            grant_allowed=False,
        )
    if event_type in _CREEM_LIVE_EVENTS:
        status = _canonical_status(_get(obj, "status"), default="active")
    elif event_type in _CREEM_END_EVENTS:
        status = "canceled"
    elif event_type in _CREEM_PAST_DUE_EVENTS:
        status = "past_due"
    else:
        return None
    product = _get(obj, "product")
    product_ref = str(_get(product, "id", "") if isinstance(product, Mapping) else product or "")
    return _normalized(
        provider=wp.CREEM,
        event_id=event_id,
        metadata=_get(obj, "metadata"),
        provider_ref=str(_get(obj, "id", "") or ""),
        status=status,
        period_end=_get(obj, "current_period_end_date") or _get(obj, "current_period_end"),
        product_ref=product_ref,
    )


def _parse_polar(event: Any) -> dict[str, Any] | None:
    event_type = str(_get(event, "type", "") or "")
    if event_type not in _POLAR_SUB_EVENTS:
        return None
    data = _get(event, "data", {}) or {}
    status = (
        "canceled"
        if event_type == "subscription.revoked"
        else _canonical_status(_get(data, "status"), default="past_due")
    )
    return _normalized(
        provider=wp.POLAR,
        event_id=str(_get(event, "id", "") or _get(data, "id", "") or ""),
        metadata=_get(data, "metadata"),
        provider_ref=str(_get(data, "id", "") or ""),
        status=status,
        period_end=_get(data, "current_period_end"),
        product_ref=str(_get(data, "product_id", "") or _path(data, "product", "id") or ""),
    )


__all__ = [
    "KIND_SUBSCRIPTION",
    "cancel",
    "change_plan",
    "is_subscription_metadata",
    "open_checkout",
    "parse_event",
]
