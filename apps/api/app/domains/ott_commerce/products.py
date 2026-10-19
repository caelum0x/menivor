"""Offers on the creator's own payment account through Mint seller-own payments (MV13, contract 5.5).

* The creator connects **their own** Dodo (or Stripe, when the operator turned
  Stripe Connect on) on Mint's connect page. Menivor never shows a key field:
  ``connect`` returns Mint's one-time link.
* Each offer becomes a product on the creator's account
  (``POST /mint/v1/sellers/{seller}/products``); a checkout is a hosted page on
  the creator's processor (``/checkout-sessions``). The buyer pays the creator
  directly; Menivor never receives or forwards viewer funds.

Env: ``MINT_URL`` (or ``MINT_SERVER_URL``) and ``MINT_SELLER_KEY`` (Menivor's
product key in Mint's ``MINT_SELLER_PRODUCTS_JSON``).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.ott.models import OttChannel, OttTitle

from .models import KIND_RENTAL, KIND_SVOD, KIND_TVOD, OFFER_KINDS, OttCoupon, OttOffer

KEY_ENV = "MINT_SELLER_KEY"
TIMEOUT_S = 10.0
DEFAULT_RENTAL_HOURS = 48
MAX_RENTAL_HOURS = 24 * 30
DEFAULT_CURRENCY = "USD"
_SKU = re.compile(r"[^a-z0-9._-]+")

Transport = Callable[[str, str, Optional[Mapping[str, Any]], Mapping[str, str]], tuple[int, dict]]


class CommerceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def seller_id(channel_id: str) -> str:
    """The Mint seller id for a channel (letters, digits, dots, dashes, underscores)."""
    return f"menivor.ch_{channel_id}"


def channel_from_seller(seller: str) -> str:
    prefix = "menivor.ch_"
    return seller[len(prefix):] if seller.startswith(prefix) else ""


def _default_transport(method: str, url: str, body: Optional[Mapping[str, Any]],
                       headers: Mapping[str, str]) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - configured Mint URL
            return int(response.status), json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return int(exc.code), json.loads(exc.read() or b"{}")
        except ValueError:
            return int(exc.code), {}


class MintSellers:
    """The Menivor side of Mint's seller API."""

    def __init__(self, env: Optional[Mapping[str, str]] = None, transport: Optional[Transport] = None) -> None:
        from app.integrations.railyard import contract

        env = env if env is not None else os.environ
        self.base = contract.mint_target(env)[0]
        self.key = (env.get(KEY_ENV) or "").strip()
        self.transport = transport or _default_transport

    @property
    def configured(self) -> bool:
        return bool(self.base and self.key)

    def _call(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None) -> dict:
        if not self.configured:
            raise CommerceError(503, "mint_off", "Selling is not available right now.")
        try:
            status, data = self.transport(method, f"{self.base}{path}", body, {"x-api-key": self.key})
        except OSError as exc:
            raise CommerceError(502, "mint_unreachable", "The payment connection did not answer. Try again.") from exc
        if status >= 400:
            error = (data or {}).get("error") or {}
            code = str(error.get("code") or "mint_error")
            message = {
                "not_connected": "Connect your payment account first.",
                "unknown_sku": "This offer is not set up on your payment account yet.",
                "refused_by_payment_account": "Your payment account refused this. Check it and try again.",
            }.get(code, "The payment connection refused this. Try again.")
            raise CommerceError(409 if code == "not_connected" else 502, code, message)
        return data or {}

    def connect(self, seller: str, return_url: str) -> dict:
        return self._call("POST", f"/mint/v1/sellers/{seller}/connect", {"return_url": return_url})

    def seller(self, seller: str) -> dict:
        return self._call("GET", f"/mint/v1/sellers/{seller}")

    def create_product(self, seller: str, offer: OttOffer) -> dict:
        body: dict[str, Any] = {"sku": offer.sku, "name": offer.name, "price_cents": int(offer.price_cents),
                                "currency": offer.currency}
        if offer.interval:
            body["interval"] = offer.interval
        return self._call("POST", f"/mint/v1/sellers/{seller}/products", body)

    def checkout(self, seller: str, *, sku: str, buyer_ref: str, success_url: str, cancel_url: str,
                 discount_code: Optional[str] = None) -> dict:
        body: dict[str, Any] = {"sku": sku, "buyer_ref": buyer_ref, "success_url": success_url,
                                "cancel_url": cancel_url}
        if discount_code:
            # Only the code: the discount itself lives on the creator's processor (QM1.3).
            body["discount_code"] = discount_code
        return self._call("POST", f"/mint/v1/sellers/{seller}/checkout-sessions", body)

    def entitlements(self, seller: str, limit: int = 100) -> list[dict]:
        return list(self._call("GET", f"/mint/v1/sellers/{seller}/entitlements?limit={int(limit)}").get(
            "entitlements") or [])


# --------------------------------------------------------------------------- #
# Offers
# --------------------------------------------------------------------------- #
def _sku(kind: str, title_id: Optional[str], interval: str) -> str:
    base = f"{kind}.{title_id or interval or 'all'}"
    return _SKU.sub("-", base.lower())[:64]


def create_offer(session: Session, channel: OttChannel, body: Mapping[str, Any], *,
                 mint: Optional[MintSellers] = None) -> OttOffer:
    """Create an offer and its product on the creator's payment account (one call, idempotent per sku)."""
    from app.domains.presets_hub.catalog import vendor_hits

    kind = str(body.get("kind") or "")
    if kind not in OFFER_KINDS:
        raise CommerceError(400, "kind", f"kind is one of {', '.join(OFFER_KINDS)}")
    price = int(body.get("price_cents") or 0)
    if not 50 <= price <= 100_000_000:
        raise CommerceError(400, "price", "prices are between 0.50 and 1,000,000")
    currency = str(body.get("currency") or "USD").upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise CommerceError(400, "currency", "currency is a code such as USD")
    title_id = body.get("title_id") or None
    interval = ""
    rental_hours = 0
    if kind == KIND_SVOD:
        interval = str(body.get("interval") or "month")
        if interval not in ("month", "year"):
            raise CommerceError(400, "interval", "a subscription renews every month or year")
        title_id = None
    else:
        title = session.get(OttTitle, str(title_id or ""))
        if title is None or title.channel_id != channel.id:
            raise CommerceError(404, "title", "title not found")
        if kind == KIND_RENTAL:
            rental_hours = int(body.get("rental_hours") or DEFAULT_RENTAL_HOURS)
            if not 1 <= rental_hours <= MAX_RENTAL_HOURS:
                raise CommerceError(400, "rental_hours", "a rental lasts 1 hour to 30 days")
    name = " ".join(str(body.get("name") or "").split())[:120]
    if not name:
        raise CommerceError(400, "name", "give the offer a name")
    if vendor_hits(name):
        raise CommerceError(400, "copy_vendor", "offer names cannot name tools or models")
    sku = _sku(kind, title_id, interval)
    offer = session.execute(select(OttOffer).where(OttOffer.channel_id == channel.id, OttOffer.sku == sku)
                            ).scalar_one_or_none()
    if offer is None:
        offer = OttOffer(channel_id=channel.id, kind=kind, title_id=title_id, sku=sku)
        session.add(offer)
    offer.name, offer.price_cents, offer.currency = name, price, currency
    offer.interval, offer.rental_hours, offer.active = interval, rental_hours, True
    session.flush()
    (mint or MintSellers()).create_product(seller_id(channel.id), offer)
    return offer


def offer_view(offer: OttOffer) -> dict[str, Any]:
    return {"id": offer.id, "kind": offer.kind, "title_id": offer.title_id, "sku": offer.sku, "name": offer.name,
            "price_cents": offer.price_cents, "currency": offer.currency, "interval": offer.interval or None,
            "rental_hours": offer.rental_hours or None, "active": offer.active}


def offers_for(session: Session, channel_id: str, *, active_only: bool = True) -> list[OttOffer]:
    query = select(OttOffer).where(OttOffer.channel_id == channel_id)
    if active_only:
        query = query.where(OttOffer.active.is_(True))
    return list(session.execute(query.order_by(OttOffer.kind, OttOffer.price_cents)).scalars())


# --------------------------------------------------------------------------- #
# Coupons (Wave Q QM1.3): the creator's own processor discounts, stored as a code reference
# --------------------------------------------------------------------------- #
_CODE = re.compile(r"^[A-Z0-9]{3,16}$")
COUPON_KINDS = ("percent", "amount")


def _parse_expiry(raw: Any) -> datetime:
    try:
        moment = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise CommerceError(400, "expires_at", "give the coupon an end date") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _coupon_currency(raw: Any, offer_currencies: Iterable[str]) -> str:
    """A flat coupon's currency: the channel's price currency, never a silent USD next to EUR prices."""
    prices = sorted({str(c).upper() for c in offer_currencies if c})
    listed = ", ".join(prices)
    currency = str(raw or "").strip().upper()
    if not currency:
        if len(prices) > 1:
            raise CommerceError(400, "currency",
                                f"your prices use more than one currency ({listed}); choose one for this coupon")
        return prices[0] if prices else DEFAULT_CURRENCY
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise CommerceError(400, "currency", "currency is a code such as USD")
    if prices and currency not in prices:
        raise CommerceError(400, "currency", f"this coupon's currency must match your prices ({listed})")
    return currency


def coupon_spec(body: Mapping[str, Any], *, at: Optional[datetime] = None,
                offer_currencies: Iterable[str] = ()) -> dict[str, Any]:
    """Validate a coupon form: a code, percent or amount (never both), and a future end date.

    A flat (amount) coupon takes the currency of the channel's active offers:
    omitted means that currency, a different one is refused, and a channel
    priced in several currencies must name one of them.
    """
    code = str(body.get("code") or "").strip().upper()
    if not _CODE.match(code):
        raise CommerceError(400, "code", "a code is 3 to 16 letters or digits")
    kind = str(body.get("kind") or "")
    percent, amount = body.get("percent"), body.get("amount_cents")
    if kind not in COUPON_KINDS or (percent is not None and amount is not None):
        raise CommerceError(400, "kind", "a coupon takes a percent or an amount, not both")
    expires = _parse_expiry(body.get("expires_at"))
    if expires <= (at or datetime.now(timezone.utc)):
        raise CommerceError(400, "expires_at", "the end date has passed")
    spec: dict[str, Any] = {"code": code, "expires_at": expires.astimezone(timezone.utc).isoformat()
                            .replace("+00:00", "Z")}
    if kind == "percent":
        basis_points = int(round(float(percent or 0) * 100))
        # Dodo takes basis points 1..10000; a percent that rounds to 0 is refused here.
        if not 1 <= basis_points <= 10_000:
            raise CommerceError(400, "percent", "a percent is between 0.01 and 100")
        spec.update(type="percentage", amount=basis_points)
    else:
        cents = int(amount or 0)
        if not 1 <= cents <= 100_000_000:
            raise CommerceError(400, "amount_cents", "an amount is at least one cent")
        currency = _coupon_currency(body.get("currency"), offer_currencies)
        spec.update(type="flat", amount=cents, currency=currency)
    return {**spec, "_expires": expires}


def _find_coupon(session: Session, channel_id: str, code: str) -> Optional[OttCoupon]:
    return session.execute(select(OttCoupon).where(OttCoupon.channel_id == channel_id, OttCoupon.code == code)
                           ).scalar_one_or_none()


def create_coupon(session: Session, channel: OttChannel, body: Mapping[str, Any], *, processor: Any) -> OttCoupon:
    """Create the discount on the creator's processor first, then keep only its code, id and end date.

    A stopped code that already has a processor discount is switched back on in
    place (``update_discount``): Dodo refuses a second discount with the same
    code. A stopped legacy row (no discount id) gets a new discount.
    """
    currencies = [o.currency for o in offers_for(session, channel.id)]
    spec = coupon_spec(body, offer_currencies=currencies)
    expires = spec.pop("_expires")
    existing = _find_coupon(session, channel.id, spec["code"])
    if existing is not None and existing.active:
        raise CommerceError(409, "code_taken", "this code is already in use on your channel")
    request = {**spec, "seller": seller_id(channel.id), "name": f"{channel.handle} {spec['code']}"}
    if existing is not None and existing.processor_discount_id:
        stored = processor.update_discount({**request, "discount_id": existing.processor_discount_id})
    else:
        stored = processor.create_discount(request)
    code = str(stored.get("code") or spec["code"]).upper()
    row = existing or OttCoupon(channel_id=channel.id, code=code)
    row.code, row.expires_at, row.active = code, expires, True
    row.processor_discount_id = str(stored.get("discount_id") or row.processor_discount_id or "") or None
    session.add(row)
    session.flush()
    return row


def stop_coupon(session: Session, channel: OttChannel, raw_code: str, *, processor: Any,
                at: Optional[datetime] = None) -> OttCoupon:
    """Stop a code here and on the creator's processor.

    The processor discount is ended (``expires_at`` set to now), not deleted, so
    it can be switched back on later. If the processor does not confirm, the
    code stays on here and the creator sees a 503 to try again: a code that
    still works at checkout is never shown as stopped. A legacy row with no
    processor discount id is only switched off here.
    """
    row = _find_coupon(session, channel.id, str(raw_code or "").strip().upper())
    if row is None:
        raise CommerceError(404, "not_found", "coupon not found")
    if row.active and row.processor_discount_id:
        now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            processor.update_discount({"seller": seller_id(channel.id), "discount_id": row.processor_discount_id,
                                       "expires_at": now.isoformat().replace("+00:00", "Z")})
        except CommerceError as exc:
            raise CommerceError(503, "coupon_not_stopped",
                                "This code is still on in your payment account. Try again in a moment.") from exc
    row.active = False
    session.flush()
    return row


def coupon_view(coupon: OttCoupon) -> dict[str, Any]:
    return {"code": coupon.code, "expires_at": _aware(coupon.expires_at).isoformat(), "active": coupon.active}


def coupons_for(session: Session, channel_id: str) -> list[OttCoupon]:
    return list(session.execute(select(OttCoupon).where(OttCoupon.channel_id == channel_id)
                                .order_by(OttCoupon.code)).scalars())


def usable_coupon(session: Session, channel_id: str, raw_code: str, *, at: Optional[datetime] = None) -> str:
    """The stored code for a checkout, or 404 when it is unknown, stopped or past its end date."""
    code = str(raw_code or "").strip().upper()
    row = session.execute(select(OttCoupon).where(OttCoupon.channel_id == channel_id, OttCoupon.code == code)
                          ).scalar_one_or_none() if _CODE.match(code) else None
    if row is None or not row.active or _aware(row.expires_at) <= (at or datetime.now(timezone.utc)):
        raise CommerceError(404, "coupon", "This code is not valid on this channel.")
    return row.code


__all__ = ["COUPON_KINDS", "CommerceError", "coupon_spec", "coupon_view", "coupons_for", "create_coupon", "stop_coupon", "usable_coupon", "DEFAULT_RENTAL_HOURS", "KEY_ENV", "KIND_RENTAL", "KIND_SVOD", "KIND_TVOD",
           "MintSellers", "channel_from_seller", "create_offer", "offer_view", "offers_for", "seller_id"]
