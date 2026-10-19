"""Seller discounts when Mint's contract has no discount type (Wave Q QM1.3).

Wave P 5.5 lets a creator sell through their own processor, but its routes are
connect, products, checkout and entitlements. Dodo discounts (percent or a flat
amount, plus an expiry) are created on the creator's own account through this
small client. Menivor keeps only the code reference and the processor's
discount id (so a stopped code can be switched back on without a duplicate).

The live client is refused here. A connected Dodo test purchase, refund, rental
and renewal is owner-only and is not called from this process.

:class:`MintDiscounts` is the production client. It asks Mint to act on the
creator's connected account (Mint holds the creator's key, so Menivor never
does), in the shapes Dodo's discount API takes.

Mint seller discounts contract (served by Railyard Mint since main 6200c2e; see apps/mint/README)
-----------------------------------------------------------------------------------------------
Both calls carry Menivor's ``x-api-key`` (``MINT_SELLER_KEY``). Mint forwards the
body unchanged to the seller's connected Dodo account.

* ``POST /mint/v1/sellers/{seller}/discounts``
  Body: Dodo ``POST /discounts`` (:func:`dodo_discount_body`): ``code``,
  ``type`` (``percentage`` or ``flat``), ``amount`` (basis points, or the
  smallest currency unit for flat), ``expires_at`` (ISO 8601 UTC), ``name``,
  and for flat ``currency_options`` (``[{currency, max_amount_possible,
  is_default}]``); optional ``restricted_to`` (SKUs).
  Answer: ``201 {"discount": {"discount_id": "dsc_...", "code": "SAVE20", ...}}``.
* ``PATCH /mint/v1/sellers/{seller}/discounts/{discount_id}``
  Body: a partial Dodo ``PATCH /discounts/{discount_id}``
  (:func:`dodo_discount_patch`): any of ``amount``, ``type``, ``code``,
  ``currency_options``, ``expires_at``, ``name``.
  Answer: ``200 {"discount": {"discount_id": "dsc_...", "code": ...}}``.
  Stopping a coupon sends only ``{"expires_at": <now>}``; switching it back on
  sends the new ``type``/``amount``/``currency_options``/``expires_at``/``name``.
  Menivor never calls Dodo's ``DELETE`` (a soft delete that cannot be undone).

Errors :class:`MintDiscounts` maps (never a fake code):

* ``404 unknown_discount`` (an unknown or another seller's ``discount_id``) ->
  ``404 unknown_discount``: that coupon is gone; distinct from "unavailable".
* ``409 discounts_unsupported`` (a Stripe seller) -> ``409 discounts_unsupported``.
* An older Mint without the routes answers 404 (``unknown``/``not_found``, or no
  error code, which reads as ``mint_error``) -> ``503 discounts_unavailable``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Optional, Protocol


class LiveProcessorRefused(RuntimeError):
    """A live Dodo call is owner-only (QM1.3 item 5) and is not made from here."""


class SellerProcessor(Protocol):
    """What Menivor asks the creator's processor to do. No funds come back."""

    def create_discount(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        """Create a percent or flat discount. Returns ``{"code", "discount_id"}``."""

    def update_discount(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        """Change an existing discount (``spec["discount_id"]``) in place. Returns ``{"code", "discount_id"}``."""

    def purchase(self, sku: str) -> dict[str, Any]: ...

    def refund(self, charge_id: str) -> dict[str, Any]: ...

    def rent(self, sku: str, *, hours: int) -> dict[str, Any]: ...

    def renew(self, sku: str, *, expires_at_ms: int) -> dict[str, Any]: ...


def dodo_discount_body(spec: Mapping[str, Any]) -> dict[str, Any]:
    """The body Dodo's ``POST /discounts`` takes for a Menivor coupon spec.

    ``spec`` holds ``code``, ``type`` (``percentage`` or ``flat``), ``amount``
    (basis points for a percentage, the smallest currency unit for flat),
    ``expires_at`` (ISO 8601, UTC) and, for flat, ``currency``. ``restricted_to``
    (product SKUs) is optional.
    """
    kind = str(spec["type"])
    amount = int(spec["amount"])
    if kind not in ("percentage", "flat"):
        raise ValueError("a discount is a percentage or a flat amount")
    if kind == "percentage" and not 1 <= amount <= 10_000:
        raise ValueError("a percentage is between 0.01 and 100")
    if kind == "flat" and amount < 1:
        raise ValueError("a flat discount takes at least one cent")
    body: dict[str, Any] = {"code": str(spec["code"]), "type": kind, "amount": amount,
                            "expires_at": spec.get("expires_at"), "name": str(spec.get("name") or spec["code"])}
    if kind == "flat":
        currency = str(spec.get("currency") or "USD").upper()
        body["currency_options"] = [{"currency": currency, "max_amount_possible": amount, "is_default": True}]
    if spec.get("restricted_to"):
        body["restricted_to"] = [str(x) for x in spec["restricted_to"]]
    return body


_PATCH_FIELDS = ("amount", "type", "code", "currency_options", "expires_at", "name")


def dodo_discount_patch(spec: Mapping[str, Any]) -> dict[str, Any]:
    """The partial body Dodo's ``PATCH /discounts/{discount_id}`` takes.

    With ``type`` and ``amount`` it is the full re-enable shape (validated like
    :func:`dodo_discount_body`); with only ``expires_at`` it is the stop shape.
    """
    if "type" in spec or "amount" in spec:
        full = dodo_discount_body({"code": spec.get("code") or "", **spec})
        return {k: full[k] for k in _PATCH_FIELDS if k in full and full[k] is not None}
    body = {k: spec[k] for k in ("code", "expires_at", "name") if spec.get(k) is not None}
    if not body:
        raise ValueError("nothing to change on this discount")
    return body


def _discount_answer(answer: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    found = answer.get("discount") or answer
    discount_id = found.get("discount_id") or found.get("id") or spec.get("discount_id")
    return {"code": str(found.get("code") or spec.get("code") or ""),
            "discount_id": str(discount_id) if discount_id else None}


class MintDiscounts:
    """Creates discounts on the creator's own account through Mint (no key ever reaches Menivor)."""

    def __init__(self, mint: Any) -> None:
        self.mint = mint

    def _send(self, method: str, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        from .products import CommerceError

        try:
            return self.mint._call(method, path, body)
        except CommerceError as exc:
            if exc.code == "unknown_discount":
                raise CommerceError(404, "unknown_discount",
                                    "This coupon no longer exists on your payment connection.") from exc
            if exc.code == "discounts_unsupported":
                raise CommerceError(409, "discounts_unsupported",
                                    "Coupons are not supported by your payment provider.") from exc
            if exc.code in ("mint_error", "unknown", "not_found"):
                raise CommerceError(503, "discounts_unavailable",
                                    "Coupons are not available on your payment connection yet.") from exc
            raise

    @staticmethod
    def _seller(spec: Mapping[str, Any]) -> str:
        from .products import CommerceError

        seller = str(spec.get("seller") or "")
        if not seller:
            raise CommerceError(400, "seller", "no seller for this discount")
        return seller

    def create_discount(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        seller = self._seller(spec)
        answer = self._send("POST", f"/mint/v1/sellers/{seller}/discounts", dodo_discount_body(spec))
        return _discount_answer(answer, spec)

    def update_discount(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        from .products import CommerceError

        seller = self._seller(spec)
        discount_id = str(spec.get("discount_id") or "")
        if not discount_id:
            raise CommerceError(400, "discount_id", "no discount to change")
        answer = self._send("PATCH", f"/mint/v1/sellers/{seller}/discounts/{discount_id}",
                            dodo_discount_patch(spec))
        return _discount_answer(answer, spec)

    def _no_charges(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        raise LiveProcessorRefused("buyers pay on the creator's hosted checkout; Menivor starts no charge")

    purchase = refund = _no_charges

    def rent(self, sku: str, *, hours: int) -> dict[str, Any]:
        return self._no_charges(sku, hours)

    def renew(self, sku: str, *, expires_at_ms: int) -> dict[str, Any]:
        return self._no_charges(sku, expires_at_ms)


def iso_utc(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


class FakeProcessor:
    """An in-memory stand-in. ``live_calls`` stays 0; nothing leaves the process."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.fail_updates = False
        self.charges: dict[str, dict[str, Any]] = {}
        self.live_calls = 0

    def create_discount(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        stored = {"code": str(spec["code"]), "type": str(spec["type"]), "amount": int(spec["amount"]),
                  "expires_at": spec.get("expires_at"), "currency": spec.get("currency")}
        stored["discount_id"] = f"dsc_fake_{len(self.created) + 1}"
        self.created.append(stored)
        return {"code": stored["code"], "discount_id": stored["discount_id"]}

    def update_discount(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        from .products import CommerceError

        if self.fail_updates:
            raise CommerceError(502, "mint_unreachable", "The payment connection did not answer. Try again.")
        known = {c["discount_id"] for c in self.created}
        if spec.get("discount_id") not in known:
            raise CommerceError(404, "not_found", "no such discount")
        body = dodo_discount_patch(spec)
        self.updated.append({"discount_id": spec["discount_id"], **body})
        return {"code": str(spec.get("code") or ""), "discount_id": str(spec["discount_id"])}

    def _charge(self, sku: str, kind: str) -> dict[str, Any]:
        charge_id = uuid.uuid4().hex[:12]
        event_id = f"ent_{charge_id}"
        row = {"id": charge_id, "sku": sku, "kind": kind, "status": "paid", "event_id": event_id}
        self.charges[charge_id] = row
        return dict(row)

    def purchase(self, sku: str) -> dict[str, Any]:
        return self._charge(sku, "purchase")

    def refund(self, charge_id: str) -> dict[str, Any]:
        row = self.charges[charge_id]
        row["status"] = "refunded"
        row["event_id"] = f"ent_refund_{charge_id}"
        return dict(row)

    def rent(self, sku: str, *, hours: int) -> dict[str, Any]:
        row = self._charge(sku, "rental")
        row["hours"] = hours
        return row

    def renew(self, sku: str, *, expires_at_ms: int) -> dict[str, Any]:
        row = self._charge(sku, "renewal")
        row["expires_at_ms"] = expires_at_ms
        return row

    def purchase_live(self, sku: str) -> dict[str, Any]:
        raise LiveProcessorRefused(f"live Dodo purchase of {sku} is owner-only and was not run")


__all__ = ["FakeProcessor", "LiveProcessorRefused", "MintDiscounts", "SellerProcessor", "dodo_discount_body",
           "dodo_discount_patch", "iso_utc"]
