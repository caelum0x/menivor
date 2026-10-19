"""Shared types for the Meta / TikTok ads clients.

Money is carried in account-currency MINOR units (cents for USD) everywhere in
Menivor; each client converts at its boundary (Meta takes minor units, TikTok
takes decimal currency units).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import httpx

HTTP_TIMEOUT_S = 30.0

# ISO 4217 currencies with no minor unit (Meta and TikTok both follow this).
_ZERO_DECIMAL = frozenset({"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"})

GENDERS = ("all", "male", "female")
OBJECTIVES = ("traffic", "leads")
CTAS = ("SHOP_NOW", "LEARN_MORE", "SIGN_UP", "ORDER_NOW", "GET_OFFER", "CONTACT_US")


class AdsApiError(Exception):
    """A platform call failed; ``message`` is safe to show the advertiser."""

    def __init__(self, platform: str, message: str, *, status_code: int = 502, code: str = "") -> None:
        super().__init__(message)
        self.platform = platform
        self.message = message
        self.status_code = status_code
        self.code = code


def minor_factor(currency: str) -> int:
    return 1 if (currency or "").upper() in _ZERO_DECIMAL else 100


def to_minor(amount: float | str | None, currency: str) -> int:
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        return 0
    return int(round(value * minor_factor(currency)))


def from_minor(minor: int, currency: str) -> float:
    factor = minor_factor(currency)
    return round(int(minor) / factor, 2 if factor == 100 else 0)


@dataclass(frozen=True)
class Audience:
    countries: tuple[str, ...] = ("US",)
    age_min: int = 18
    age_max: int = 65
    gender: str = "all"

    def to_record(self) -> dict:
        return {"countries": list(self.countries), "age_min": self.age_min, "age_max": self.age_max, "gender": self.gender}

    @classmethod
    def from_record(cls, data: dict | None) -> "Audience":
        data = data or {}
        countries = tuple(str(c).upper() for c in (data.get("countries") or ["US"]))
        return cls(countries=countries, age_min=int(data.get("age_min") or 18),
                   age_max=int(data.get("age_max") or 65), gender=str(data.get("gender") or "all"))


@dataclass(frozen=True)
class AccountRef:
    """The advertiser's selected ad account plus the posting identity.

    Meta: ``account_id`` = ``act_<id>``, ``identity_id`` = Facebook Page id.
    TikTok: ``account_id`` = advertiser id, ``identity_id`` = custom identity id.
    """

    account_id: str
    identity_id: str = ""
    currency: str = "USD"


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    expires_at: datetime | None = None
    scopes: str = ""
    account_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AdCreativeInput:
    name: str
    video_id: str
    thumbnail_url: str
    primary_text: str
    headline: str
    landing_url: str
    cta: str = "SHOP_NOW"


@dataclass(frozen=True)
class AdStats:
    ad_id: str
    spend_minor: int = 0
    impressions: int = 0
    clicks: int = 0
    leads: int | None = None  # None => the platform reported no lead metric


@dataclass(frozen=True)
class VideoState:
    ready: bool
    failed: bool = False
    thumbnail_url: str = ""
    detail: str = ""


def new_http() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=False)


__all__ = [
    "AccountRef", "AdCreativeInput", "AdStats", "AdsApiError", "Audience", "CTAS", "GENDERS", "OBJECTIVES",
    "TokenGrant", "VideoState", "from_minor", "minor_factor", "new_http", "to_minor",
]
