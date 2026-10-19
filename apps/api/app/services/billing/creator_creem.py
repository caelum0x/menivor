"""Creem transport for personal monthly plans (no DB writes, no grants).

* :func:`open_checkout` — hosted checkout for a recurring plan product, with
  ``request_id`` = the user id (signed into the success redirect) and
  ``kind=creator_plan`` metadata so every later webhook routes back here.
* :func:`fetch_subscription` — the live subscription (period dates, status),
  used when the signed redirect lands before the webhook and to self-heal a
  renewal whose webhook was missed.
* :func:`cancel` — turn renewal off (scheduled: access runs to period end).
* :func:`change_product` — switch a live subscription to another plan.
* :func:`portal_link` — Creem customer portal (card, invoices, cancel).

Secrets come from ``config.creem`` via :mod:`creem_client`. Every call sends an
explicit User-Agent (Creem sits behind Cloudflare) and raises ``RuntimeError``
with a short, key-free detail on transport/HTTP failure.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.services.billing import creator_plans as cp

USER_AGENT: str = "menivor-api/1.0 (+https://menivor.com)"
_TIMEOUT: tuple[int, int] = (5, 20)


class CreemHttpError(RuntimeError):
    """Creem answered with a non-2xx status."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Creem rejected the request (HTTP {status}): {detail}")
        self.status = status


def _base() -> str:
    from app.services.billing import creem_client

    return creem_client._api_base().rstrip("/")


def _headers() -> dict[str, str]:
    from app.services.billing import creem_client

    return {
        "x-api-key": creem_client._require_api_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _request(method: str, path: str, *, body: Any = None, params: dict | None = None) -> dict:
    try:
        import requests
    except Exception as exc:  # pragma: no cover - requests is a hard dep
        raise RuntimeError(f"'requests' is required for billing: {exc}") from exc
    url = f"{_base()}{path}"
    try:
        response = requests.request(
            method, url, headers=_headers(), json=body, params=params, timeout=_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 - normalize transport errors
        raise RuntimeError(f"Creem {method} {path} failed: {exc}") from exc
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        detail = str(getattr(response, "text", "") or "")[:300]
        raise CreemHttpError(status, detail)
    if not getattr(response, "content", b""):
        return {}
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 - body optional for mutations
        return {}
    return data if isinstance(data, dict) else {}


def success_url() -> str:
    """Where Creem returns a new subscriber (the billing page confirms it)."""
    from app.services.billing import card_check

    return f"{card_check.web_base_url()}/billing?checkout=return"


def open_checkout(
    *, user_id: str, user_email: str, plan: cp.CreatorPlan, interval: str
) -> dict[str, str]:
    """Open a recurring Creem checkout; returns ``{checkout_url, session_id}``."""
    product = cp.product_id(plan.key, interval, "creem")
    if not product:
        raise RuntimeError(
            f"Creem product for {plan.display_name} ({interval}ly) is not configured: "
            f"set {cp.env_name(plan.key, interval, 'creem')}."
        )
    body: dict[str, Any] = {
        "product_id": product,
        "success_url": success_url(),
        # Signed into the success redirect: identifies the subscriber.
        "request_id": user_id,
        "metadata": {
            "kind": cp.KIND,
            "user_id": user_id,
            "plan_key": plan.key,
            "interval": interval,
        },
    }
    if user_email:
        body["customer"] = {"email": user_email}
    data = _request("POST", "/v1/checkouts", body=body)
    session_id = str(data.get("id", "") or "").strip()
    url = str(data.get("checkout_url", "") or data.get("url", "") or "").strip()
    if not session_id or not url:
        raise RuntimeError("Creem returned a subscription checkout without an id/url.")
    logger.info(f"creator plans: checkout {session_id} user={user_id} plan={plan.key}/{interval}")
    return {"checkout_url": url, "session_id": session_id}


def fetch_subscription(subscription_id: str) -> dict:
    """The Creem subscription object for ``subscription_id``."""
    ref = (subscription_id or "").strip()
    if not ref:
        raise ValueError("subscription id is required")
    return _request("GET", "/v1/subscriptions", params={"subscription_id": ref})


def cancel(subscription_id: str) -> str:
    """Turn renewal off. Returns ``"scheduled"`` (runs to period end) or ``"immediate"``.

    Asks Creem for a scheduled cancel so the subscriber keeps what they paid
    for; an API that does not accept ``mode`` falls back to the plain cancel.
    """
    ref = (subscription_id or "").strip()
    if not ref:
        raise ValueError("subscription has no Creem id to cancel")
    path = f"/v1/subscriptions/{ref}/cancel"
    try:
        _request("POST", path, body={"mode": "scheduled"})
        return "scheduled"
    except CreemHttpError as exc:
        if exc.status not in (400, 422):
            raise
        logger.info(f"creator plans: scheduled cancel rejected for {ref}; canceling now")
    _request("POST", path, body={})
    return "immediate"


def change_product(subscription_id: str, product_id: str, *, upgrade: bool) -> None:
    """Move a live subscription to ``product_id`` (upgrades are charged pro rata now)."""
    ref = (subscription_id or "").strip()
    if not ref or not product_id:
        raise ValueError("subscription id and product id are required")
    behavior = "proration-charge-immediately" if upgrade else "proration-none"
    _request(
        "POST",
        f"/v1/subscriptions/{ref}/upgrade",
        body={"product_id": product_id, "update_behavior": behavior},
    )


def portal_link(customer_id: str) -> str:
    """A Creem customer-portal URL where the subscriber manages billing."""
    ref = (customer_id or "").strip()
    if not ref:
        raise ValueError("no Creem customer id on file")
    data = _request("POST", "/v1/customers/billing", body={"customer_id": ref})
    url = str(data.get("customer_portal_link", "") or data.get("url", "") or "").strip()
    if not url:
        raise RuntimeError("Creem returned no customer portal link.")
    return url


__all__ = [
    "CreemHttpError",
    "USER_AGENT",
    "cancel",
    "change_product",
    "fetch_subscription",
    "open_checkout",
    "portal_link",
    "success_url",
]
